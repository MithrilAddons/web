import base64
import gzip
import json
import struct
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY
from mithril_web.curator_data import day, market_prices
from mithril_web.curator_game import points, streaks

NOW = 1_800_000_000.0
OWNER, ALICE, BOB = (char * 32 for char in "abc")
ORIGIN = "https://mithril.foo"


def nbt(identifier, count=1):
    def string(value):
        data = value.encode()
        return struct.pack(">H", len(data)) + data

    def compound(name, content):
        return b"\x0a" + string(name) + content + b"\x00"

    extra = compound("ExtraAttributes", b"\x08" + string("id") + string(identifier))
    item = compound("tag", extra) + b"\x01" + string("Count") + struct.pack("b", count) + b"\x00"
    root = compound("", b"\x09" + string("i") + b"\x0a" + struct.pack(">i", 1) + item)
    return base64.b64encode(gzip.compress(root)).decode()


def synth(version, stage, npc):
    parent = {f"SYNTHESIZER_V{version}": f"SYNTHESIZER_V{version + 1}"} if version < 3 else {}
    return {
        "id": f"SYNTHESIZER_V{version}",
        "name": f"Synthesizer v{version}",
        "tier": "EPIC",
        "category": "NECKLACE",
        "material": "PAPER",
        "npc_sell_price": npc,
        "requirements": [{"type": "SKILL", "skill": "COMBAT", "level": 22}],
        "museum_data": {"category": "COMBAT", "game_stage": stage, "parent": parent},
    }


ITEMS = {
    "lastUpdated": 1,
    "items": [
        *(
            {"id": f"FILLER_{n:04}", "name": f"Filler {n}", "tier": "RARE", "npc_sell_price": n + 1}
            for n in range(1000)
        ),
        synth(2, "EXPERT", 9280),
        synth(3, "PROFESSIONAL", 17440),
        {
            "id": "HYPERION",
            "name": "Hyperion",
            "tier": "LEGENDARY",
            "category": "SWORD",
            "material": "IRON_SWORD",
        },
    ],
}


def auction(identifier, price, count=1):
    return {"bin": True, "starting_bid": price, "item_bytes": nbt(identifier, count)}


def feeds():
    return {
        "resources/skyblock/items": ITEMS,
        "skyblock/auctions_ended": {"auctions": []},
        "skyblock/auctions?page=0": {
            "page": 0,
            "totalPages": 2,
            "lastUpdated": 7,
            "auctions": [
                auction("SYNTHESIZER_V3", 5_400_000),
                auction("SYNTHESIZER_V3", 6_000_000),
                {"bin": False, "starting_bid": 1, "item_bytes": nbt("SYNTHESIZER_V3")},
            ],
        },
        "skyblock/auctions?page=1": {
            "page": 1,
            "totalPages": 2,
            "lastUpdated": 7,
            "auctions": [
                auction("SYNTHESIZER_V2", 3_100_000),
                auction("FILLER_0001", 400, count=4),
                {"bin": True, "starting_bid": 5, "item_bytes": "broken"},
            ],
        },
        "skyblock/bazaar": {
            "products": {"FILLER_0002": {"quick_status": {"buyPrice": 12.5}}, "EMPTY": {}}
        },
    }


@pytest.fixture
def game(tmp_path):
    now = [NOW]
    sources = feeds()

    def loader(path):
        # Only the test drives Hypixel reads, so the background refresh never picks a day.
        if threading.current_thread().name.startswith("asyncio"):
            raise ValueError("Background refresh disabled in this test")
        return sources[path]

    app = create_app(
        database=tmp_path / "auth.db",
        clock=lambda: now[0],
        owner_uuid=OWNER,
        curator_loader=loader,
    )
    with TestClient(app, base_url="https://mithril.foo") as client:
        data = app.state.curator
        data.load_catalog()
        tokens = {
            uuid: app.state.auth.issue("device", uuid, name, 30 * DAY)
            for uuid, name in ((ALICE, "Alice"), (BOB, "Bob"), (OWNER, "Owner"))
        }
        headers = {uuid: {"Authorization": f"Bearer {token}"} for uuid, token in tokens.items()}

        def plan(item, date=None):
            with data.lock, data.db:
                data.db.execute(
                    "INSERT OR REPLACE INTO curator_days VALUES (?, ?, NULL, ?)",
                    (date or day(now[0]), item, now[0]),
                )

        yield client, app, now, headers, plan


def guess(client, headers, item, date=None):
    return client.post(
        "/api/v1/games/curator/guess",
        headers=headers,
        json={"version": 1, "day": date or day(NOW), "item": item},
    )


def test_market_prices_take_the_lowest_unit_bin_and_bazaar_buy_price():
    prices = market_prices(feeds().get)
    assert prices == {
        "SYNTHESIZER_V3": 5_400_000,
        "SYNTHESIZER_V2": 3_100_000,
        "FILLER_0001": 100,
        "FILLER_0002": 12.5,
    }
    broken = feeds()
    broken["skyblock/auctions?page=1"]["lastUpdated"] = 8
    with pytest.raises(ValueError):
        market_prices(broken.get)
    broken["skyblock/auctions?page=0"]["totalPages"] = 201
    with pytest.raises(ValueError):
        market_prices(broken.get)


def test_streaks_and_points():
    assert streaks([]) == (0, 0)
    assert streaks(["2027-01-01", "2027-01-02", "2027-01-04"]) == (1, 2)
    assert points(1, True) == 10
    assert points(10, True) == 1
    assert points(3, False) == 0


def test_round_is_prepared_then_played_to_a_solve(game):
    client, app, _, headers, plan = game
    alice = headers[ALICE]
    today = client.get("/api/v1/games/curator/today", headers=alice).json()
    assert today["state"] == "preparing"
    assert today["resets_at"] == int(NOW // DAY + 1) * DAY
    assert guess(client, alice, "SYNTHESIZER_V2").status_code == 409
    plan("SYNTHESIZER_V3")
    app.state.curator.load_lock()
    app.state.curator.load_lock()
    today = client.get("/api/v1/games/curator/today", headers=alice).json()
    assert (today["state"], today["number"], today["limit"], today["guesses"]) == (
        "playing",
        1,
        10,
        [],
    )
    sibling = guess(client, alice, "SYNTHESIZER_V2").json()["guesses"][0]
    assert sibling["family"] is True
    assert sibling["values"]["market"] == 3_100_000
    assert sibling["feedback"]["market"] == {"match": "none", "arrow": "up"}
    assert sibling["feedback"]["stage"] == {"match": "none", "arrow": "up"}
    assert guess(client, alice, "SYNTHESIZER_V2").status_code == 409
    assert guess(client, alice, "MISSING").status_code == 404
    assert guess(client, alice, "HYPERION", day(NOW - DAY)).status_code == 409
    other = guess(client, alice, "HYPERION").json()["guesses"][1]
    assert other["family"] is False
    assert other["values"]["market"] is None
    solved = guess(client, alice, "SYNTHESIZER_V3").json()
    assert solved["state"] == "solved"
    assert solved["answer"]["name"] == "Synthesizer v3"
    assert solved["answer"]["icon"] == {"material": "PAPER"}
    assert solved["answer"]["values"]["market"] == 5_400_000
    assert solved["stats"] == {"played": 1, "solved": 1, "streak": 1, "best_streak": 1}
    assert guess(client, alice, "FILLER_0003").status_code == 409


def test_ten_wrong_guesses_end_the_round(game):
    client, app, _, headers, plan = game
    plan("SYNTHESIZER_V3")
    app.state.curator.load_lock()
    for n in range(10):
        result = guess(client, headers[BOB], f"FILLER_{n:04}").json()
    assert result["state"] == "failed"
    assert result["answer"]["item"] == "SYNTHESIZER_V3"
    assert result["stats"]["solved"] == 0
    assert guess(client, headers[BOB], "SYNTHESIZER_V3").status_code == 409


def test_a_new_day_needs_its_own_lock(game):
    client, app, now, headers, plan = game
    plan("SYNTHESIZER_V3")
    app.state.curator.load_lock()
    now[0] += DAY
    assert (
        client.get("/api/v1/games/curator/today", headers=headers[ALICE]).json()["state"]
        == "preparing"
    )
    plan("SYNTHESIZER_V2")
    app.state.curator.load_lock()
    today = client.get("/api/v1/games/curator/today", headers=headers[ALICE]).json()
    assert today["number"] == 2
    assert guess(client, headers[ALICE], "HYPERION", day(NOW)).json()["detail"] == (
        "A new item is ready"
    )


def test_catalog_lists_each_name_once_and_skips_unchanged_downloads(game):
    client, app, _, headers, _ = game
    catalog = client.get("/api/v1/games/curator/catalog", headers=headers[ALICE]).json()
    assert ["SYNTHESIZER_V3", "Synthesizer v3"] in catalog["items"]
    assert len(catalog["items"]) == 1003
    again = client.get(
        f"/api/v1/games/curator/catalog?version={catalog['catalog']}", headers=headers[ALICE]
    ).json()
    assert again == {"version": 1, "catalog": catalog["catalog"], "unchanged": True}


def test_game_routes_need_a_mod_session_and_no_ban(game):
    client, app, _, headers, _ = game
    assert client.get("/api/v1/games/curator/today").status_code == 401
    browser = {**headers[ALICE], "Origin": ORIGIN}
    assert client.get("/api/v1/games/curator/today", headers=browser).status_code == 403
    session = app.state.auth.issue("session", OWNER, "Owner", DAY)
    response = client.post(
        "/api/v1/moderation/sanction",
        headers={"Cookie": f"{COOKIE}={session}", "Origin": ORIGIN},
        json={"version": 1, "reason": "Synthetic", "uuid": BOB, "kind": "ban"},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/games/curator/today", headers=headers[BOB]).status_code == 403


def test_leaderboard_ranks_the_season_and_pins_your_row(game):
    client, app, _, headers, plan = game
    plan("SYNTHESIZER_V3")
    app.state.curator.load_lock()
    records = app.state.records
    with records.lock, records.db:
        for n in range(11):
            used = [{"item": "X"}]
            records.db.execute(
                "INSERT INTO curator_results VALUES (?, ?, ?, ?, 1, ?)",
                (day(NOW), f"{n:032x}", f"Player{n}", json.dumps(used), NOW),
            )
        records.db.execute(
            "INSERT INTO curator_results VALUES (?, ?, 'Alice', ?, 0, ?)",
            (day(NOW - DAY), ALICE, json.dumps([{"item": "X"}] * 10), NOW - DAY),
        )
        # Last month's results don't count towards this season.
        records.db.execute(
            "INSERT INTO curator_results VALUES (?, ?, 'Alice', ?, 1, ?)",
            (day(NOW - 40 * DAY), ALICE, json.dumps([{"item": "X"}]), NOW - 40 * DAY),
        )
    for item in ("HYPERION", "FILLER_0001", "SYNTHESIZER_V3"):
        guess(client, headers[ALICE], item)
    board = client.get("/api/v1/games/curator/leaderboard", headers=headers[ALICE]).json()
    assert board["season"] == day(NOW)[:7]
    assert board["players"] == 12
    assert [row["points"] for row in board["top"][:3]] == [10, 10, 10]
    assert board["top"][0]["name"] == "Player0"
    assert board["you"]["name"] == "Alice"
    assert board["you"]["rank"] == 12
    assert board["you"]["points"] == 8
    assert board["you"]["played"] == 2
    stats = board["stats"]
    assert stats["histogram"][2] == 1
    assert stats["failed"] == 1
    assert (stats["points"], stats["average"], stats["streak"]) == (8, 3.0, 1)
    top = client.get("/api/v1/games/curator/leaderboard", headers=headers[BOB]).json()
    assert top["you"] is None
    assert top["stats"]["rank"] is None


def test_erasing_records_removes_curator_results(game):
    client, app, _, headers, plan = game
    plan("SYNTHESIZER_V3")
    app.state.curator.load_lock()
    guess(client, headers[ALICE], "HYPERION")
    response = client.post(
        "/api/v1/auth/device-erase",
        headers=headers[ALICE],
        json={"version": 1, "scope": "records", "confirmation": "DELETE"},
    )
    assert response.status_code == 200
    count = app.state.records.db.execute(
        "SELECT COUNT(*) FROM curator_results WHERE uuid=?", (ALICE,)
    ).fetchone()[0]
    assert count == 0


def contract_responses(client, headers):
    alice = headers[ALICE]
    playing = guess(client, alice, "SYNTHESIZER_V2").json()
    solved = guess(client, alice, "SYNTHESIZER_V3").json()
    board = client.get("/api/v1/games/curator/leaderboard", headers=alice).json()
    return {"playing": playing, "solved": solved, "leaderboard": board}


def test_responses_match_the_contract(game):
    client, app, _, headers, plan = game
    plan("SYNTHESIZER_V3")
    app.state.curator.load_lock()
    actual = contract_responses(client, headers)
    fixture = Path(__file__).resolve().parents[2] / "contracts/curator-v1.json"
    assert actual == json.loads(fixture.read_text())
