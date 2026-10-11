import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY
from mithril_web.capture import new_id
from mithril_web.glicko import Rating, idle, soften, update
from mithril_web.location_duels import (
    CHALLENGE_KEPT,
    COUNTDOWN,
    CUT,
    HEALTH,
    LOADING,
    RECONNECT,
    REVEAL,
    TIMER,
    multiplier,
)
from test_location_game import BAYOU_MIN, bayou_map, hub_map, png_bytes

NOW = 1_800_000_000.0  # 2027-01-15
OWNER, ALICE, BOB = "a" * 32, "b" * 32, "c" * 32
SITE = {"Origin": "https://mithril.foo"}
BASE = "/api/v1/games/locations/duels"


@pytest.fixture
def duel(tmp_path, monkeypatch):
    monkeypatch.setattr("mithril_web.location_game.FACE", 8)
    now = [NOW]
    app = create_app(
        database=tmp_path / "auth.db", clock=lambda: now[0], owner_uuid=OWNER, party_wait=0.05
    )
    with TestClient(app, base_url="https://mithril.foo") as client:
        store, db = app.state.captures, app.state.records.db
        for island, name, image, (min_x, min_z) in (
            ("hub", "Hub", hub_map(), (0, 0)),
            ("fishing_1", "Backwater Bayou", bayou_map(), BAYOU_MIN),
        ):
            map_id = new_id()
            store.map_path(map_id).parent.mkdir(parents=True, exist_ok=True)
            store.map_path(map_id).write_bytes(png_bytes(image))
            with db:
                db.execute(
                    "INSERT INTO capture_maps VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,'approved',NULL,NULL,?,?)",
                    (
                        map_id,
                        new_id(),
                        OWNER,
                        "Owner",
                        island,
                        name,
                        min_x,
                        min_z,
                        min_x + image.width - 1,
                        min_z + image.height - 1,
                        NOW,
                        NOW,
                    ),
                )
        for n in range(6):
            location_id = new_id()
            for face in range(6):
                path = store.face_path(location_id, face)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png_bytes(hub_map().convert("RGB").resize((16, 16))))
            with db:
                db.execute(
                    "INSERT INTO capture_locations VALUES "
                    "(?,?,?,?,?,'Hub',?,64,?,0,'',16,63,'approved',NULL,NULL,?,?)",
                    (
                        location_id,
                        new_id(),
                        ALICE,
                        "Alice",
                        "hub",
                        10.0 + 8 * n,
                        10.0 + 6 * n,
                        NOW,
                        NOW,
                    ),
                )
        app.state.locations.refresh()
        auth = app.state.auth
        linked = {
            who: {"Cookie": f"{COOKIE}={auth.issue('session', who, name, DAY)}", **SITE}
            for who, name in ((ALICE, "Alice"), (BOB, "Bob"))
        }

        def tick(seconds=0.0):
            now[0] += seconds
            client.portal.call(app.state.duels.advance)

        yield client, app, now, linked, tick


def inbox(client, headers=SITE, after=-1):
    return client.get(f"{BASE}/inbox?after={after}", headers=headers).json()


def view(client, duel_id, headers=SITE):
    return client.get(f"{BASE}/{duel_id}", headers=headers).json()


def post(client, path, headers=SITE, **body):
    return client.post(f"{BASE}/{path}", headers=headers, json={"version": 1, **body})


def spot(app, duel_id):
    location = app.state.duels.duels[duel_id].rounds[-1].location
    return location.x, location.z


def start_round(client, app, tick, duel_id, players, first=False):
    number = view(client, duel_id, players[0])["round"]
    for headers in players:
        post(client, f"{duel_id}/ready", headers, round=number)
    if first:
        tick(COUNTDOWN)
    return number


def test_damage_grows_so_long_duels_end():
    assert [multiplier(n) for n in (1, 3, 4, 5, 6, 7)] == [1, 1, 1.5, 2, 2.5, 3]


def test_glicko_matches_the_published_example_and_the_monthly_reset():
    after = update(
        Rating(1500, 200, 0.06),
        [(Rating(1400, 30), 1), (Rating(1550, 100), 0), (Rating(1700, 300), 0)],
    )
    assert (round(after.rating, 2), round(after.rd, 2)) == (1464.05, 151.52)
    assert round(after.volatility, 4) == 0.06
    assert soften(Rating(2100, 80)) == Rating(1950, 180)
    assert soften(Rating(1500, 300)).rd == 350
    assert idle(Rating(1500, 50), 0) == Rating(1500, 50)
    assert idle(Rating(1500, 50), 52).rd > 50


def test_guests_duel_through_an_invite_link(duel):
    client, app, now, _, tick = duel
    host = TestClient(app, base_url="https://mithril.foo")
    guest = TestClient(app, base_url="https://mithril.foo")
    assert inbox(host)["duel"] is None
    code = post(host, "invite").json()["code"]
    assert len(code) == 6
    assert inbox(host)["outgoing"][0]["kind"] == "invite"
    assert post(host, "join", code=code).json()["detail"] == "You can't duel yourself"
    duel_id = post(guest, "join", code=code.lower()).json()["duel"]
    assert inbox(host)["duel"] == duel_id
    assert post(guest, "join", code=code).status_code == 404  # used up
    start = view(host, duel_id)
    assert (start["state"], start["round"], start["me"]["health"]) == ("loading", 1, HEALTH)
    assert start["opponent"]["guest"] is True
    assert host.get(start["panorama"]).headers["content-type"] == "image/webp"
    post(host, f"{duel_id}/ready", round=1)
    assert view(host, duel_id)["state"] == "loading"
    post(guest, f"{duel_id}/ready", round=1)
    counting = view(host, duel_id)
    assert counting["countdown"] == NOW + COUNTDOWN
    assert post(host, f"{duel_id}/guess", round=1, x=1.0, z=1.0).status_code == 409
    tick(COUNTDOWN)
    playing = view(host, duel_id)
    assert (playing["state"], playing["deadline"]) == ("playing", NOW + COUNTDOWN + TIMER)
    x, z = spot(app, duel_id)
    now[0] += 2
    first = post(host, f"{duel_id}/guess", round=1, x=x, z=z).json()
    assert first["me"]["guessed"] is True
    assert post(host, f"{duel_id}/guess", round=1, x=x, z=z).status_code == 409
    cut = view(guest, duel_id)
    assert cut["deadline"] == now[0] + CUT
    assert cut["opponent"]["guessed"] is True
    revealed = post(guest, f"{duel_id}/guess", round=1, x=105.0, z=5.0).json()
    assert revealed["state"] == "revealed"
    result = revealed["results"][0]
    assert (result["me"]["score"], result["opponent"]["score"]) == (0, 5000)
    assert (result["lost"], result["damage"]) == (True, 5000)
    assert result["me"]["guessed"] == "fishing_1"
    assert revealed["me"]["health"] == HEALTH - 5000
    assert view(host, duel_id)["results"][0]["lost"] is False
    tick(REVEAL)
    second = view(host, duel_id)
    assert (second["state"], second["round"]) == ("loading", 2)
    assert second["panorama"] != start["panorama"]
    assert host.get(start["panorama"]).status_code == 404
    assert post(guest, f"{duel_id}/leave").status_code == 200
    done = view(host, duel_id)
    assert done["finished"] == {"result": "win", "reason": "forfeit", "rating": None}
    assert view(guest, duel_id)["finished"]["result"] == "loss"
    # Guest-only duels leave nothing behind.
    count = app.state.records.db.execute("SELECT COUNT(*) FROM location_duels").fetchone()[0]
    assert count == 0


def play_to_the_end(client, app, tick, duel_id, players, aim):
    """Plays rounds until the duel ends; aim(seat, x, z) gives each player's pin."""
    first = True
    while True:
        number = start_round(client, app, tick, duel_id, players, first)
        first = False
        x, z = spot(app, duel_id)
        for seat, headers in enumerate(players):
            pin = aim(seat, x, z)
            post(client, f"{duel_id}/guess", headers, round=number, x=pin[0], z=pin[1])
        state = view(client, duel_id, players[0])
        if state["state"] == "finished":
            return state
        tick(REVEAL)


def challenge_and_accept(client, linked, sender=ALICE, target=BOB, name="Bob"):
    inbox(client, linked[target])  # the target has the game open
    challenge = post(client, "challenge", linked[sender], name=name).json()
    incoming = inbox(client, linked[target])["incoming"]
    assert incoming[0]["from"] == ("Alice" if sender == ALICE else "Bob")
    return post(client, f"challenges/{challenge['id']}/accept", linked[target]).json()["duel"]


def test_linked_players_duel_for_rating_and_history(duel):
    client, app, now, linked, tick = duel
    players = [linked[ALICE], linked[BOB]]
    duel_id = challenge_and_accept(client, linked)

    def aim(seat, x, z):
        return (x, z) if seat == 0 else (105.0, 5.0)  # Bob always picks the wrong island

    final = play_to_the_end(client, app, tick, duel_id, players, aim)
    assert final["round"] == 2  # 5,000 damage twice empties 6,000 health
    assert final["finished"]["result"] == "win"
    assert final["finished"]["reason"] == "health"
    change = final["finished"]["rating"]
    assert change["before"] == 1500 and change["after"] > 1500 and change["provisional"]
    bob = view(client, duel_id, linked[BOB])["finished"]["rating"]
    assert bob["after"] < 1500
    me = client.get("/api/v1/games/locations/me", headers=linked[ALICE]).json()
    assert me["rating"]["wins"] == 1 and me["rating"]["provisional"] is True
    history = client.get(f"{BASE}/history", headers=linked[BOB]).json()
    assert history["total"] == 1
    past = history["duels"][0]
    assert (past["opponent"], past["result"], past["rated"]) == ("Alice", "loss", True)
    assert past["rounds"][0]["me"]["score"] == 0
    # Provisional players stay off the leaderboard.
    board = client.get("/api/v1/games/locations/leaderboard").json()
    assert (board["season"], board["players"], board["top"]) == ("2027-01", 0, [])
    assert post(client, f"{duel_id}/rematch", linked[BOB]).status_code == 200
    assert inbox(client, linked[ALICE])["incoming"][0]["from"] == "Bob"


def test_only_three_duels_a_day_between_a_pair_are_rated(duel):
    client, app, now, linked, tick = duel
    players = [linked[ALICE], linked[BOB]]
    rated = []
    for _ in range(4):
        duel_id = challenge_and_accept(client, linked)
        final = play_to_the_end(
            client, app, tick, duel_id, players, lambda seat, x, z: (x, z) if seat else (105.0, 5.0)
        )
        rated.append(final["finished"]["rating"] is not None)
        tick(REVEAL)
    assert rated == [True, True, True, False]
    stored = app.state.records.db.execute(
        "SELECT rated FROM location_duels ORDER BY finished"
    ).fetchall()
    assert [row[0] for row in stored] == [1, 1, 1, 0]


def test_equal_play_through_every_round_is_a_draw(duel):
    client, app, now, linked, tick = duel
    players = [linked[ALICE], linked[BOB]]
    duel_id = challenge_and_accept(client, linked)
    final = play_to_the_end(client, app, tick, duel_id, players, lambda seat, x, z: (x, z))
    assert final["round"] == final["rounds"] == 6  # the whole pool, never repeated
    assert final["finished"]["result"] == "draw"
    assert final["finished"]["reason"] == "rounds"
    assert final["me"]["health"] == HEALTH


def test_rounds_run_out_and_players_who_vanish_forfeit(duel):
    client, app, now, linked, tick = duel
    players = [linked[ALICE], linked[BOB]]
    duel_id = challenge_and_accept(client, linked)

    # Nobody reports the panorama loaded: the round starts anyway, then runs out.
    def both_check_in(seconds):
        tick(seconds)
        return [view(client, duel_id, headers) for headers in players][0]

    both_check_in(LOADING)
    assert both_check_in(COUNTDOWN)["state"] == "playing"
    revealed = both_check_in(TIMER + 2)
    assert revealed["state"] == "revealed"
    assert revealed["results"][0]["damage"] == 0
    tick(REVEAL)
    # Bob stops checking in; Alice keeps the duel open.
    for _ in range(4):
        now[0] += RECONNECT / 3
        view(client, duel_id, players[0])
        tick()
    finished = view(client, duel_id, players[0])["finished"]
    assert (finished["result"], finished["reason"]) == ("win", "forfeit")


def test_a_duel_both_players_abandon_is_cancelled(duel):
    client, app, now, linked, tick = duel
    duel_id = challenge_and_accept(client, linked)
    tick(RECONNECT + 1)
    finished = view(client, duel_id, linked[ALICE])["finished"]
    assert (finished["reason"], finished["rating"]) == ("cancelled", None)
    assert app.state.records.db.execute("SELECT COUNT(*) FROM location_duels").fetchone()[0] == 0


def test_challenges_explain_what_went_wrong(duel):
    client, app, now, linked, tick = duel
    missing = post(client, "challenge", linked[ALICE], name="Bob")
    assert (missing.status_code, missing.json()["detail"]) == (
        404,
        "Bob doesn't have the game open right now",
    )
    inbox(client, linked[ALICE])
    assert post(client, "challenge", linked[ALICE], name="alice").status_code == 422
    inbox(client, linked[BOB])
    sent = post(client, "challenge", linked[ALICE], name="bob").json()
    assert inbox(client, linked[ALICE])["outgoing"][0]["to"] == "Bob"
    post(client, f"challenges/{sent['id']}/decline", linked[BOB])
    assert inbox(client, linked[BOB])["incoming"] == []
    again = post(client, "challenge", linked[ALICE], name="Bob").json()
    now[0] += CHALLENGE_KEPT + 1
    late = post(client, f"challenges/{again['id']}/accept", linked[BOB])
    assert (late.status_code, late.json()["detail"]) == (404, "This challenge has expired")
    duel_id = challenge_and_accept(client, linked)
    busy = post(client, "invite", linked[ALICE])
    assert (busy.status_code, busy.json()["detail"]) == (409, "Finish your current duel first")
    stranger = TestClient(app, base_url="https://mithril.foo")
    inbox(stranger)
    assert stranger.get(f"{BASE}/{duel_id}", headers=SITE).status_code == 404
    assert client.get(f"{BASE}/{'x' * 22}", headers=linked[ALICE]).status_code == 404
    assert post(client, f"{duel_id}/rematch", linked[ALICE]).status_code == 409
    assert post(client, f"{duel_id}/guess", linked[ALICE], round=1, x=1.0, z=1.0).status_code == 409
    assert post(client, f"{duel_id}/ready", linked[ALICE], round=5).status_code == 409


def test_waiting_requests_return_on_change_or_after_the_wait(duel):
    client, app, now, linked, tick = duel
    first = inbox(client, linked[BOB])
    held = inbox(client, linked[BOB], after=first["revision"])
    assert held["revision"] == first["revision"]
    duel_id = challenge_and_accept(client, linked)
    state = view(client, duel_id, linked[ALICE])
    same = client.get(f"{BASE}/{duel_id}?after={state['version']}", headers=linked[ALICE]).json()
    assert same["version"] == state["version"]


def test_seasons_soften_ratings_and_keep_the_last_top_ten(duel):
    client, app, now, linked, tick = duel
    db = app.state.records.db
    with db:
        for uuid, name, rating in ((ALICE, "Alice", 2100.0), (BOB, "Bob", 1700.0)):
            db.execute(
                "INSERT INTO location_ratings VALUES (?,?,?,80,0.06,'2026-12',9,1,0,?,?)",
                (uuid, name, rating, rating, NOW - DAY),
            )
    me = client.get("/api/v1/games/locations/me", headers=linked[ALICE]).json()["rating"]
    assert (me["rating"], me["wins"], me["peak"]) == (1950, 0, None)
    duel_id = challenge_and_accept(client, linked)
    play_to_the_end(
        client,
        app,
        tick,
        duel_id,
        [linked[ALICE], linked[BOB]],
        lambda seat, x, z: (x, z) if seat == 0 else (105.0, 5.0),
    )
    board = client.get("/api/v1/games/locations/leaderboard", headers=linked[BOB]).json()
    assert board["past"] == [
        {
            "season": "2026-12",
            "top": [
                {"rank": 1, "name": "Alice", "rating": 2100},
                {"rank": 2, "name": "Bob", "rating": 1700},
            ],
        }
    ]
    # The reset made both less certain, so they are provisional again until they play more.
    assert board["top"] == []
    assert board["you"] is None


def test_erasing_records_removes_ratings_but_keeps_the_opponents_history(duel):
    client, app, now, linked, tick = duel
    duel_id = challenge_and_accept(client, linked)
    play_to_the_end(
        client,
        app,
        tick,
        duel_id,
        [linked[ALICE], linked[BOB]],
        lambda seat, x, z: (x, z) if seat == 0 else (105.0, 5.0),
    )
    response = client.post(
        "/api/v1/auth/erase",
        headers=linked[BOB],
        json={"version": 1, "scope": "records", "confirmation": "DELETE"},
    )
    assert response.status_code == 200, response.text
    db = app.state.records.db
    assert (
        db.execute("SELECT COUNT(*) FROM location_ratings WHERE uuid=?", (BOB,)).fetchone()[0] == 0
    )
    history = client.get(f"{BASE}/history", headers=linked[ALICE]).json()
    assert history["duels"][0]["opponent"] == "Erased player"
