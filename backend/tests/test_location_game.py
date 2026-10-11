import io
import math

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY
from mithril_web.capture import new_id
from mithril_web.location_game import ROUNDS, TIMER
from mithril_web.location_world import CELL, MAX_POINTS, build
from PIL import Image

NOW = 1_800_000_000.0
OWNER, ALICE = "a" * 32, "b" * 32
ORIGIN = "https://mithril.foo"
SITE = {"Origin": ORIGIN}
GREEN, BLUE = (60, 160, 60, 255), (40, 80, 200, 255)


def hub_map():
    """The Hub at 0..63 with a glimpse of the Bayou's ground at 100..115, as seen from the Hub."""
    image = Image.new("RGBA", (128, 64))
    image.paste(Image.new("RGBA", (64, 64), GREEN), (0, 0))
    image.paste(Image.new("RGBA", (16, 16), BLUE), (100, 0))
    return image


def bayou_map():
    return Image.new("RGBA", (16, 16), BLUE)


# The Bayou lives in its own world; its offset (287, 4) puts it at 100..115 beside the Hub.
BAYOU_MIN = (100 - 287, 0 - 4)


def png_bytes(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr("mithril_web.location_game.FACE", 8)
    now = [NOW]
    app = create_app(database=tmp_path / "auth.db", clock=lambda: now[0], owner_uuid=OWNER)
    with TestClient(app, base_url="https://mithril.foo") as client:
        store, db = app.state.captures, app.state.records.db

        def add_map(island, name, image, min_x, min_z, status="approved"):
            map_id = new_id()
            store.map_path(map_id).parent.mkdir(parents=True, exist_ok=True)
            store.map_path(map_id).write_bytes(png_bytes(image))
            with db:
                db.execute(
                    "INSERT INTO capture_maps VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)",
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
                        status,
                        now[0],
                        now[0],
                    ),
                )
            return map_id

        def add_location(island, x, z, status="approved", by="Alice"):
            location_id = new_id()
            for face in range(6):
                path = store.face_path(location_id, face)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png_bytes(Image.new("RGB", (16, 16), (face * 40, 90, 120))))
            with db:
                db.execute(
                    "INSERT INTO capture_locations VALUES "
                    "(?,?,?,?,?,?,?,64,?,0,'',16,63,?,NULL,NULL,?,?)",
                    (
                        location_id,
                        new_id(),
                        ALICE,
                        by,
                        island,
                        island,
                        x,
                        z,
                        status,
                        now[0],
                        now[0],
                    ),
                )
            return location_id

        add_map("hub", "Hub", hub_map(), 0, 0)
        add_map("fishing_1", "Backwater Bayou", bayou_map(), *BAYOU_MIN)
        hub_spots = [add_location("hub", 10.0 + 8 * n, 10.0 + 6 * n) for n in range(6)]
        bayou_spot = add_location("fishing_1", BAYOU_MIN[0] + 8, BAYOU_MIN[1] + 8)
        app.state.locations.refresh()
        session = app.state.auth.issue("session", ALICE, "Alice", DAY)
        linked = {"Cookie": f"{COOKIE}={session}", **SITE}
        yield client, app, now, add_location, hub_spots, bayou_spot, linked


def start(client, headers=SITE):
    return client.post("/api/v1/games/locations/solo", headers=headers, json={"version": 1})


def step(client, run, action, number, headers=SITE, **extra):
    return client.post(
        f"/api/v1/games/locations/solo/{run}/{action}",
        headers=headers,
        json={"version": 1, "round": number, **extra},
    )


def test_neighbour_scenery_belongs_to_its_own_island():
    world = build(
        [
            {"island": "hub", "island_name": "Hub", "image": hub_map(), "min_x": 0, "min_z": 0},
            {
                "island": "fishing_1",
                "island_name": "Backwater Bayou",
                "image": bayou_map(),
                "min_x": BAYOU_MIN[0],
                "min_z": BAYOU_MIN[1],
            },
        ]
    )
    assert world.islands["hub"].box == (0, 0, 64, 64)
    assert world.islands["fishing_1"].box == (100, 0, 116, 16)
    assert world.island_at(30, 30) == "hub"
    assert world.island_at(105, 5) == "fishing_1"
    # The void counts as the nearest island, even beyond the map's edge.
    assert world.island_at(70, 40) == "hub"
    assert world.island_at(95, 4) == "fishing_1"
    assert world.island_at(10_000, -10_000) == "fishing_1"
    assert world.spot("fishing_1", BAYOU_MIN[0] + 8, BAYOU_MIN[1] + 8) == (108, 8)
    assert world.score("hub", 20, 20, 21, 22) == (MAX_POINTS, math.hypot(1, 2), "hub")
    scale = math.hypot(64, 64) / 10
    points, distance, _ = world.score("hub", 20, 20, 20, 40)
    assert (points, distance) == (round(MAX_POINTS * math.exp(-20 / scale)), 20)
    assert world.score("hub", 20, 20, 105, 5) == (0, None, "fishing_1")
    assert world.width % CELL == 0
    with Image.open(io.BytesIO(world.png)) as image:
        # The Bayou's own map, not the Hub's view of it, is drawn there.
        assert image.getpixel((105 - world.x0, 5 - world.z0)) == BLUE
        assert image.getpixel((70 - world.x0, 40 - world.z0))[3] == 0


def test_the_world_map_is_public_and_versioned(game):
    client, app, *_ = game
    world = client.get("/api/v1/games/locations/world").json()
    assert [island["key"] for island in world["islands"]] == ["hub", "fishing_1"]
    image = client.get(world["image"])
    assert image.headers["content-type"] == "image/png"
    assert "immutable" in image.headers["cache-control"]
    assert client.get("/api/v1/games/locations/world/0123456789abcdef.png").status_code == 404


def test_the_pool_holds_only_live_spots_on_their_own_island(game):
    client, app, _, add_location, hub_spots, bayou_spot, _ = game
    add_location("hub", 12.0, 12.0, status="submitted")
    retired = add_location("hub", 14.0, 14.0, status="retired")
    stranded = add_location("hub", 105.0, 5.0)  # the Hub's capture of ground the Bayou owns
    app.state.locations.refresh()
    pool = app.state.locations.pool
    assert set(pool) == {*hub_spots, bayou_spot}
    assert stranded not in pool and retired not in pool
    assert (pool[bayou_spot].x, pool[bayou_spot].z) == (108, 8)
    folder = app.state.captures.folder / "game"
    assert {path.stem for path in folder.glob("*.webp")} == set(pool)
    with Image.open(folder / f"{bayou_spot}.webp") as atlas:
        assert atlas.size == (8 * 3, 8 * 2)


def test_a_guest_plays_a_solo_run_to_the_end(game):
    client, app, now, _, hub_spots, bayou_spot, _ = game
    first = start(client)
    assert first.status_code == 200
    assert "mithril_guest" in first.cookies
    run = first.json()
    assert (run["state"], run["round"], run["rounds"], run["timer"]) == ("loading", 1, 5, TIMER)
    panorama = client.get(run["panorama"])
    assert panorama.headers["content-type"] == "image/webp"
    assert "private" in panorama.headers["cache-control"]
    assert step(client, run["id"], "guess", 1, x=0.0, z=0.0).status_code == 409
    playing = step(client, run["id"], "ready", 1).json()
    assert (playing["state"], playing["deadline"]) == ("playing", NOW + TIMER)
    location = app.state.locations.runs[run["id"]].rounds[0].location
    now[0] += 5
    revealed = step(client, run["id"], "guess", 1, x=location.x, z=location.z).json()
    assert revealed["state"] == "revealed"
    result = revealed["results"][0]
    assert (result["score"], result["distance"], result["guessed"]) == (
        MAX_POINTS,
        0.0,
        location.island,
    )
    assert result["answer"]["island"] == location.island
    assert result["captured_by"] == "Alice"
    assert "panorama" not in revealed
    assert step(client, run["id"], "guess", 1, x=1.0, z=1.0).status_code == 409
    second = step(client, run["id"], "next", 1).json()
    assert (second["round"], second["state"]) == (2, "loading")
    assert second["panorama"] != run["panorama"]
    # Last round's image name never works again.
    assert client.get(run["panorama"]).status_code == 404
    # A round whose panorama never reports loaded starts by itself, then runs out.
    now[0] += 20 + TIMER + 2
    timed_out = client.get(f"/api/v1/games/locations/solo/{run['id']}").json()
    assert timed_out["state"] == "revealed"
    assert timed_out["results"][1]["score"] == 0
    assert timed_out["results"][1]["pin"] is None
    for number in range(3, ROUNDS + 1):
        step(client, run["id"], "next", number - 1)
        step(client, run["id"], "ready", number)
        final = step(client, run["id"], "guess", number, x=-50.0, z=-50.0).json()
    assert final["state"] == "finished"
    assert final["total"] == sum(result["score"] for result in final["results"])
    assert "best" not in final  # guests keep their best in the browser
    assert step(client, run["id"], "next", ROUNDS).status_code == 409
    seen = app.state.records.db.execute("SELECT COUNT(*) FROM location_seen").fetchone()[0]
    assert seen == ROUNDS


def test_guesses_respect_the_clock_and_the_round(game):
    client, app, now, *_ = game
    run = start(client).json()
    step(client, run["id"], "ready", 1)
    assert step(client, run["id"], "guess", 2, x=1.0, z=1.0).status_code == 409
    now[0] += TIMER + 0.5  # inside the grace second
    assert step(client, run["id"], "guess", 1, x=1.0, z=1.0).json()["state"] == "revealed"
    step(client, run["id"], "next", 1)
    step(client, run["id"], "ready", 2)
    now[0] += TIMER + 1.5
    late = step(client, run["id"], "guess", 2, x=1.0, z=1.0)
    assert (late.status_code, late.json()["detail"]) == (409, "Time's up for this round")


def test_linked_players_keep_a_best_and_see_new_spots_first(game):
    client, app, now, _, hub_spots, bayou_spot, linked = game
    totals = []
    for _ in range(2):
        run = start(client, linked).json()
        assert "mithril_guest" not in client.cookies
        for number in range(1, ROUNDS + 1):
            if number > 1:
                step(client, run["id"], "next", number - 1, linked)
            step(client, run["id"], "ready", number, linked)
            location = app.state.locations.runs[run["id"]].rounds[number - 1].location
            pin = (location.x, location.z) if totals == [] else (location.x + 30, location.z)
            final = step(client, run["id"], "guess", number, linked, x=pin[0], z=pin[1]).json()
        totals.append(final["total"])
        best = final["best"]
    assert totals[0] == ROUNDS * MAX_POINTS
    assert best == {
        "best": totals[0],
        "runs": 2,
        "average": round(sum(totals) / 2),
        "new_best": False,
    }
    me = client.get("/api/v1/games/locations/me", headers=linked).json()
    assert (me["kind"], me["name"], me["solo"]["best"]) == ("linked", "Alice", totals[0])
    # Seven spots: the second run must include the two the first left unseen.
    first_run = app.state.records.db.execute(
        "SELECT location FROM location_seen WHERE player=? ORDER BY seen", ("u:" + ALICE,)
    ).fetchall()
    assert len(first_run) == 7


def test_runs_belong_to_their_player_and_one_runs_at_a_time(game):
    client, app, *_, linked = game
    guest_run = start(client).json()
    other = TestClient(app, base_url="https://mithril.foo")
    assert other.get(f"/api/v1/games/locations/solo/{guest_run['id']}").status_code == 401
    other_run = start(other).json()
    assert other.get(f"/api/v1/games/locations/solo/{guest_run['id']}").status_code == 404
    again = start(client).json()
    assert client.get(f"/api/v1/games/locations/solo/{guest_run['id']}").status_code == 404
    assert client.get(f"/api/v1/games/locations/solo/{again['id']}").status_code == 200
    assert other_run["id"] != again["id"]
    # The website only: other sites and Origin-less starts are refused.
    assert start(client, {"Origin": "https://example.com"}).status_code == 403
    assert client.post("/api/v1/games/locations/solo", json={"version": 1}).status_code == 403
    me = client.get("/api/v1/games/locations/me").json()
    assert me["kind"] == "guest" and me["name"].startswith("Guest #")


def test_too_few_locations_or_no_map_says_so(game):
    client, app, *_ = game
    with app.state.records.db as db:
        db.execute("UPDATE capture_locations SET status='retired'")
    app.state.locations.refresh()
    assert start(client).json()["detail"] == "Not enough locations yet. Check back soon."
    with app.state.records.db as db:
        db.execute("UPDATE capture_maps SET status='rejected'")
    app.state.locations.refresh()
    assert client.get("/api/v1/games/locations/world").status_code == 503
    assert start(client).status_code == 503


def test_retiring_takes_a_live_location_out_of_the_game(game):
    client, app, _, _, hub_spots, *_ = game
    owner = {"Cookie": f"{COOKIE}={app.state.auth.issue('session', OWNER, 'Owner', DAY)}", **SITE}

    def decide(item, decision, kind="locations"):
        return client.post(
            "/api/v1/moderation/captures/decide",
            headers=owner,
            json={"version": 1, "kind": kind, "id": item, "decision": decision, "note": ""},
        )

    assert decide(hub_spots[0], "retire").status_code == 200
    assert hub_spots[0] not in app.state.locations.pool
    assert decide(hub_spots[0], "retire").status_code == 409
    assert decide(hub_spots[0], "approve").status_code == 200
    assert hub_spots[0] in app.state.locations.pool
    queue = client.get("/api/v1/moderation/captures?status=retired", headers=owner)
    assert queue.status_code == 200


def test_erasing_records_removes_location_progress(game):
    client, app, _, _, _, _, linked = game
    run = start(client, linked).json()
    step(client, run["id"], "ready", 1, linked)
    step(client, run["id"], "guess", 1, linked, x=1.0, z=1.0)
    db = app.state.records.db
    with db:
        db.execute("INSERT INTO location_solo_best VALUES (?, 1, 1, 1, 0)", (ALICE,))
    response = client.post(
        "/api/v1/auth/erase",
        headers=linked,
        json={"version": 1, "scope": "records", "confirmation": "DELETE"},
    )
    assert response.status_code == 200, response.text
    assert db.execute("SELECT COUNT(*) FROM location_seen").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM location_solo_best").fetchone()[0] == 0


def test_cleanup_ends_old_runs_and_forgets_old_guests(game):
    client, app, now, *_, linked = game
    assert client.get("/api/v1/games/locations/me").json() == {
        "version": 1,
        "kind": "guest",
        "name": None,
        "solo": None,
    }
    guest_run = start(client).json()
    step(client, guest_run["id"], "ready", 1)
    step(client, guest_run["id"], "guess", 1, x=1.0, z=1.0)
    linked_run = start(client, linked).json()
    step(client, linked_run["id"], "ready", 1, linked)
    step(client, linked_run["id"], "guess", 1, linked, x=1.0, z=1.0)
    now[0] += 31 * DAY
    app.state.locations.cleanup()
    assert app.state.locations.runs == {}
    assert client.get(f"/api/v1/games/locations/solo/{guest_run['id']}").status_code == 404
    players = [row[0] for row in app.state.records.db.execute("SELECT player FROM location_seen")]
    assert players == ["u:" + ALICE]
