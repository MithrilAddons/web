import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.discord_api import create_internal
from mithril_web.leaderboards import snapshot

SECRET = "a" * 64
HEADERS = {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
def stores(tmp_path):
    app = create_app(database=tmp_path / "auth.sqlite3", clock=lambda: 100000)
    with TestClient(app, base_url="http://localhost") as public:
        yield app.state, app, public


def add(state, player, real=100000, ticks=1800, floor="M7", kind="terminals", status="eligible"):
    uuid = f"{player:032x}"
    with state.records.lock, state.records.db:
        record = state.records._record(uuid, floor, kind, real, ticks, "corroborated", None)
        state.records.db.execute("UPDATE pb_records SET status=? WHERE id=?", (status, record))
    return record


def test_terminal_best_uses_real_then_ticks_and_groups_all_ties(stores):
    state, _, _ = stores
    add(state, 1, 100000, 1900)
    add(state, 1, 101000, 1700)  # Must not combine independently minimized clocks.
    add(state, 2, 100000, 1900)
    add(state, 3, 100000, 1850)
    add(state, 4, 99000, 1800, floor="F7")
    rows = snapshot(state.records, state.auth)["boards"]["m7_terminals"]
    assert [(r["uuid"], r["rank"], r["ticks"]) for r in rows] == [
        (f"{3:032x}", 1, 1850),
        (f"{1:032x}", 2, 1900),
        (f"{2:032x}", 2, 1900),
    ]


def test_solo_uses_ticks_only_and_keeps_floors_separate(stores):
    state, _, _ = stores
    add(state, 1, 100000, 1900, kind="solo_clear")
    add(state, 1, 120000, 1800, kind="solo_clear")
    add(state, 2, 90000, 1850, kind="solo_clear")
    add(state, 3, 100000, 1700, floor="F7", kind="solo_clear")
    boards = snapshot(state.records, state.auth)["boards"]
    assert [r["ticks"] for r in boards["m7_solo"]] == [1800, 1850]
    assert boards["m7_solo"][0]["real_ms"] == 120000
    assert len(boards["f7_solo"]) == 1


def test_tenth_slot_includes_every_tie_but_not_eleventh(stores):
    state, _, _ = stores
    for player in range(1, 16):
        add(state, player, 100000 + min(player, 10), 1800)
        add(state, player, 100000, 1800 + player, kind="solo_clear")
    add(state, 16, 100011, 1800)
    boards = snapshot(state.records, state.auth)["boards"]
    assert len(boards["m7_terminals"]) == 15
    assert [r["rank"] for r in boards["m7_terminals"]][-6:] == [10] * 6
    assert len(boards["m7_solo"]) == 10


def test_moderation_deletion_and_verified_names(stores):
    state, _, _ = stores
    uuid = f"{1:032x}"
    token = state.auth.issue("session", uuid, "SyntheticOne", 100)
    state.auth.issue("challenge", uuid, "SpoofedName", 1000)
    best = add(state, 1)
    add(state, 1, 110000, 2000)

    def board():
        return snapshot(state.records, state.auth)["boards"]["m7_terminals"]

    assert board()[0]["name"] == "SyntheticOne"
    with state.records.db:
        state.records.db.execute("UPDATE pb_records SET status='invalidated' WHERE id=?", (best,))
    assert board()[0]["real_ms"] == 110000
    with state.records.db:
        state.records.db.execute(
            "INSERT INTO sanctions VALUES (?,?,?,0,NULL,NULL,'test','test',0,0,NULL)",
            ("test-ban", uuid, "ban"),
        )
    assert board() == []
    with state.records.db:
        state.records.db.execute("UPDATE sanctions SET expires=1")
    assert len(board()) == 1
    state.privacy.erase(token, "records")
    assert board() == []
    assert state.records.db.execute("SELECT * FROM record_names").fetchall() == []


def test_names_survive_logout_and_no_unverified_name_is_used(stores):
    state, _, _ = stores
    uuid = f"{1:032x}"
    add(state, 1)
    state.auth.issue("challenge", uuid, "SpoofedName", 1000)
    assert snapshot(state.records, state.auth)["boards"]["m7_terminals"][0]["name"] is None
    token = state.auth.issue("session", uuid, "SyntheticOne", 100)
    snapshot(state.records, state.auth)
    state.auth.revoke(token)
    assert (
        snapshot(state.records, state.auth)["boards"]["m7_terminals"][0]["name"] == "SyntheticOne"
    )


def test_internal_only_authenticated_contract(stores):
    state, app, public = stores
    fixture = json.loads(
        (Path(__file__).parents[2] / "contracts/discord-leaderboards-v1.json").read_text()
    )
    for key, rows in fixture["boards"].items():
        for row in rows:
            player = int(row["uuid"], 16)
            state.auth.issue("session", row["uuid"], row["name"], 100)
            add(
                state,
                player,
                row["real_ms"],
                row["ticks"],
                "F7" if key == "f7_solo" else "M7",
                "terminals" if key == "m7_terminals" else "solo_clear",
            )
    path = "/internal/v1/leaderboards"
    assert public.get(path, headers=HEADERS).status_code == 404
    with TestClient(create_internal(app, SECRET), client=("127.0.0.1", 1)) as bot:
        assert bot.get(path).status_code == 401
        response = bot.get(path, headers=HEADERS)
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == fixture


def test_capacity_fails_explicitly_without_truncating_ties(stores):
    state, app, _ = stores
    for player in range(1001):
        add(state, player)
    with TestClient(create_internal(app, SECRET), client=("127.0.0.1", 1)) as bot:
        assert bot.get("/internal/v1/leaderboards", headers=HEADERS).status_code == 503
