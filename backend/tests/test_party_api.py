import time

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE
from mithril_web.player_card import CATACOMBS_XP

ORIGIN = "https://mithril.foo"
UUIDS = {"Noctis": "a" * 32, "Sable": "b" * 32, "Grim": "c" * 32}
SUMMARY = {
    "catacombs": {"level": 50.0, "experience": sum(CATACOMBS_XP) + 200_000_000},
    "class_levels": dict.fromkeys(("archer", "berserk", "healer", "mage", "tank"), 50.0),
    "magical_power": 1400,
    "floors": [{"floor": "F7", "s_plus_ms": 268_000}, {"floor": "M7", "s_plus_ms": 320_000}],
}
MOJANG = {"grim": ("c" * 32, "Grim"), "nomod": ("d" * 32, "NoMod")}
NO_RULES = {"shared": {}, "per_class": {}, "exempt": []}
PUBLISH = {
    "version": 1,
    "floor": "M7",
    "leader_class": "mage",
    "roles": ["archer", "berserk", "healer", "mage", "tank"],
    "allow_duplicates": False,
    "rules": NO_RULES,
    "block_names": [],
}


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    loads = []
    failing = set()

    def loader(uuid):
        loads.append(uuid)
        if uuid in failing:
            raise ValueError("Hypixel unavailable")
        return SUMMARY

    app = create_app(
        database=tmp_path / "auth.db",
        clock=lambda: now[0],
        profile_lookup=lambda name, _: {"id": UUIDS[name], "name": name},
        card_loader=loader,
        party_wait=0.05,
        name_lookup=lambda name: MOJANG.get(name),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, app, now, loads, failing


def login(client, name):
    proof = client.post(
        "/api/v1/auth/challenge", json={"version": 1, "uuid": UUIDS[name], "name": name}
    ).json()
    link = client.post("/api/v1/auth/verify", json={"challenge_id": proof["challenge_id"]}).json()
    response = client.post(
        "/api/v1/auth/complete",
        headers={"Origin": ORIGIN},
        json={"token": link["link_token"], "remember": False},
    )
    token = response.cookies[COOKIE]
    client.cookies.clear()
    return {"Origin": ORIGIN, "Cookie": f"{COOKIE}={token}"}, link


def state(client, headers, known=None):
    body = {"version": 1} if known is None else {"version": 1, "known": known}
    response = client.post("/api/v1/party/state", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_routes_require_a_session_and_the_site_origin(setup):
    client, *_ = setup
    headers, _ = login(client, "Sable")
    assert client.post("/api/v1/party/state", json={"version": 1}).status_code == 403
    assert (
        client.post(
            "/api/v1/party/state", headers={"Origin": ORIGIN}, json={"version": 1}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/party/listings", params={"floor": "M7"}).status_code == 401
    response = client.post(
        "/api/v1/party/state",
        headers={**headers, "Content-Length": "5000"},
        content=b"{" * 5000,
    )
    assert response.status_code == 413


def test_publish_then_looking_places_the_player_automatically(setup):
    client, *_ = setup
    leader, _ = login(client, "Noctis")
    joiner, _ = login(client, "Sable")
    published = client.post("/api/v1/party/publish", headers=leader, json=PUBLISH)
    assert published.status_code == 200, published.text
    party = published.json()["party"]
    assert party["you_lead"] and party["floor"] == "M7"
    looked = client.post(
        "/api/v1/party/look",
        headers=joiner,
        json={"version": 1, "floor": "M7", "classes": ["healer"], "max_team_s_plus_ms": 330_000},
    ).json()
    assert looked["party"]["id"] == party["id"]
    assert looked["you"]["looking"] is None
    assert looked["notices"][-1]["kind"] == "placed"
    seen = state(client, leader)["party"]
    assert [m["name"] for m in seen["members"]] == ["Sable", "Noctis"]
    assert seen["members"][0]["stats"]["catacombs"] == 51.0


def test_state_is_held_until_the_players_own_state_changes(setup):
    client, *_ = setup
    leader, _ = login(client, "Noctis")
    joiner, _ = login(client, "Sable")
    first = state(client, leader)
    started = time.monotonic()
    unchanged = state(client, leader, known=first["state_version"])
    assert unchanged == {"version": 1, "state_version": first["state_version"], "unchanged": True}
    assert time.monotonic() - started >= 0.04
    client.post("/api/v1/party/publish", headers=leader, json=PUBLISH)
    mine = state(client, leader)
    client.post(
        "/api/v1/party/reserve",
        headers=joiner,
        json={"party_id": mine["party"]["id"], "role": "healer"},
    )
    changed = state(client, leader, known=mine["state_version"])
    assert changed["notices"][-1]["kind"] == "member_joined"


def test_listings_are_shared_compact_hidden_when_blocked_and_cacheable(setup):
    client, *_ = setup
    leader, _ = login(client, "Noctis")
    viewer, _ = login(client, "Sable")
    blocked, _ = login(client, "Grim")
    party = client.post(
        "/api/v1/party/publish", headers=leader, json={**PUBLISH, "block_names": ["grim"]}
    ).json()["party"]
    response = client.get("/api/v1/party/listings", params={"floor": "M7"}, headers=viewer)
    rows = response.json()["parties"]
    assert [row["leader"] for row in rows] == ["Noctis"]
    assert "members" not in rows[0] and "blocked" not in rows[0]
    assert rows[0]["team"]["s_plus_ms_avg"] == 320_000
    again = client.get(
        "/api/v1/party/listings",
        params={"floor": "M7"},
        headers={**viewer, "If-None-Match": response.headers["etag"]},
    )
    assert again.status_code == 304
    hidden = client.get("/api/v1/party/listings", params={"floor": "M7"}, headers=blocked)
    assert hidden.json()["parties"] == []
    assert client.get(f"/api/v1/party/listings/{party['id']}", headers=blocked).status_code == 404
    detail = client.get(f"/api/v1/party/listings/{party['id']}", headers=viewer).json()
    assert detail["members"][0]["name"] == "Noctis" and detail["members"][0]["leader"]
    empty = client.get("/api/v1/party/listings", params={"floor": "F7"}, headers=viewer)
    assert empty.json() == {"version": 1, "floor": "F7", "parties": []}


def test_refusals_use_stable_codes(setup):
    client, _, _, _, failing = setup
    headers, _ = login(client, "Sable")
    missing = client.post(
        "/api/v1/party/reserve", headers=headers, json={"party_id": "x" * 12, "role": "tank"}
    )
    assert (missing.status_code, missing.json()["detail"]) == (404, "not_found")
    bad = client.post(
        "/api/v1/party/publish",
        headers=headers,
        json={**PUBLISH, "rules": {**NO_RULES, "shared": {"catacombs": 0}}},
    )
    assert (bad.status_code, bad.json()["detail"]) == (422, "invalid_rules")
    wrong_shape = client.post(
        "/api/v1/party/publish", headers=headers, json={**PUBLISH, "roles": ["tank"]}
    )
    assert wrong_shape.status_code == 422


def test_party_cards_require_sign_in_and_visible_membership(setup):
    client, app, _, loads, _ = setup
    leader, _ = login(client, "Noctis")
    viewer, _ = login(client, "Sable")
    blocked, _ = login(client, "Grim")
    party = client.post(
        "/api/v1/party/publish", headers=leader, json={**PUBLISH, "block_names": ["grim"]}
    ).json()["party"]
    url = f"/api/v1/party/player-card/{UUIDS['Noctis']}"
    before = len(loads)
    assert client.get(url).status_code == 401
    assert client.get(url, headers=blocked).status_code == 404
    assert client.get("/api/v1/party/player-card/invalid", headers=viewer).status_code == 404
    assert (
        client.get(f"/api/v1/party/player-card/{UUIDS['Grim']}", headers=viewer).status_code == 404
    )
    assert len(loads) == before
    card = client.get(url, headers=viewer)
    assert card.status_code == 200
    assert card.json()["user"] == {"uuid": UUIDS["Noctis"], "name": "Noctis"}
    assert card.json()["catacombs"] == SUMMARY["catacombs"]
    assert "blocked" not in card.json()
    client.get(url, headers=viewer)
    assert len(loads) == before + 1  # Shared card cache, not a fetch on every click.
    client.post("/api/v1/party/pause", headers=leader, json={"paused": True})
    assert client.get(url, headers=viewer).status_code == 404
    assert client.get(url, headers=leader).status_code == 200
    client.post("/api/v1/party/pause", headers=leader, json={"paused": False})
    client.post(
        "/api/v1/party/reserve", headers=viewer, json={"party_id": party["id"], "role": "tank"}
    )
    app.state.finder.parties[party["id"]].full_since = 1000
    assert client.get(url, headers=viewer).status_code == 200
    client.post("/api/v1/party/unlist", headers=leader, json={})
    assert client.get(url, headers=viewer).status_code == 404


def test_party_card_upstream_failure_is_safe(setup):
    client, _, _, _, failing = setup
    leader, _ = login(client, "Noctis")
    viewer, _ = login(client, "Sable")
    client.post("/api/v1/party/publish", headers=leader, json=PUBLISH)
    failing.add(UUIDS["Noctis"])
    response = client.get(f"/api/v1/party/player-card/{UUIDS['Noctis']}", headers=viewer)
    assert response.status_code == 503
    assert response.json()["detail"] == "Player stats unavailable. Try again shortly."
    failing.add(UUIDS["Grim"])
    grim, _ = login(client, "Grim")
    unavailable = client.post(
        "/api/v1/party/look",
        headers=grim,
        json={"version": 1, "floor": "M7", "classes": ["tank"]},
    )
    assert (unavailable.status_code, unavailable.json()["detail"]) == (503, "stats_unavailable")


def test_game_presence_uses_the_scoped_mod_credential(setup):
    client, app, *_ = setup
    headers, link = login(client, "Sable")
    proof = client.post(
        "/api/v1/auth/party-challenge",
        json={
            "version": 1,
            "uuid": UUIDS["Sable"],
            "name": "Sable",
            "receipt_token": link["receipt_token"],
        },
    ).json()
    token = client.post(
        "/api/v1/auth/party-verify",
        json={"challenge_id": proof["challenge_id"], "receipt_token": link["receipt_token"]},
    ).json()["party_token"]
    bearer = {"Authorization": f"Bearer {token}"}
    url = "/api/v1/party/mod/presence"
    assert client.post(url, json={"version": 1}).status_code == 401
    assert (
        client.post(url, headers={**bearer, "Origin": ORIGIN}, json={"version": 1}).status_code
        == 403
    )
    untracked = client.post(url, headers=bearer, json={"version": 1}).json()
    assert untracked == {"version": 1, "interval_seconds": 120, "party": None}
    assert state(client, headers)["you"]["in_game"] is False
    tracked = client.post(url, headers=bearer, json={"version": 1}).json()
    assert tracked["interval_seconds"] == 25
    assert state(client, headers)["you"]["in_game"] is True
    assert app.state.finder.players[UUIDS["Sable"]].in_game
    client.post(url, headers=bearer, json={"version": 1, "online": False})
    assert not state(client, headers)["you"]["in_game"]


def test_hypixel_profiles_are_fetched_once_and_reused(setup):
    client, _, _, loads, _ = setup
    headers, _ = login(client, "Sable")
    for _ in range(3):
        state(client, headers)
        client.post(
            "/api/v1/party/look",
            headers=headers,
            json={"version": 1, "floor": "M7", "classes": ["tank"]},
        )
        client.post("/api/v1/party/stop-looking", headers=headers, json={})
    assert loads == [UUIDS["Sable"]]


def test_block_names_resolve_to_uuids_and_unknown_names_are_refused(setup):
    client, app, *_ = setup
    leader, _ = login(client, "Noctis")
    joiner, _ = login(client, "Sable")
    state(client, joiner)  # Sable is a finder user, so no Mojang lookup is needed
    unknown = client.post(
        "/api/v1/party/publish", headers=leader, json={**PUBLISH, "block_names": ["Ghost"]}
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == {"code": "unknown_names", "names": ["ghost"]}
    party = client.post(
        "/api/v1/party/publish",
        headers=leader,
        json={**PUBLISH, "block_names": ["sable", "NoMod"]},
    ).json()["party"]
    assert party["blocked"] == [
        {"uuid": "d" * 32, "name": "NoMod"},
        {"uuid": UUIDS["Sable"], "name": "Sable"},
    ]
    edited = client.post(
        "/api/v1/party/edit",
        headers=leader,
        json={"rules": NO_RULES, "blocked": ["d" * 32], "block_names": []},
    ).json()["party"]
    assert edited["blocked"] == [{"uuid": "d" * 32, "name": "NoMod"}]
    too_many = client.post(
        "/api/v1/party/edit",
        headers=leader,
        json={"rules": NO_RULES, "block_names": [f"n{i}" for i in range(11)]},
    )
    assert (too_many.status_code, too_many.json()["detail"]) == (422, "too_many_names")


def test_block_lookups_happen_only_after_authentication_and_leader_checks(tmp_path):
    calls = []
    app = create_app(
        database=tmp_path / "auth.db",
        profile_lookup=lambda name, _: {"id": UUIDS[name], "name": name},
        card_loader=lambda _: SUMMARY,
        name_lookup=lambda name: calls.append(name),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        body = {**PUBLISH, "block_names": ["Unknown"]}
        assert client.post("/api/v1/party/publish", json=body).status_code == 403
        assert (
            client.post("/api/v1/party/publish", headers={"Origin": ORIGIN}, json=body).status_code
            == 401
        )
        headers, _ = login(client, "Sable")
        edit = client.post(
            "/api/v1/party/edit",
            headers=headers,
            json={"rules": NO_RULES, "block_names": ["Unknown"]},
        )
        assert edit.status_code == 409 and edit.json()["detail"] == "not_leader"
        assert calls == []


def test_new_generation_is_returned_even_when_the_revision_matches(setup):
    client, app, *_ = setup
    headers, _ = login(client, "Sable")
    first = state(client, headers)
    app.state.finder.players.pop(UUIDS["Sable"])
    response = client.post(
        "/api/v1/party/state",
        headers=headers,
        json={"version": 1, "known": first["state_version"], "state_id": first["state_id"]},
    ).json()
    assert "unchanged" not in response
    assert response["state_id"] != first["state_id"]
