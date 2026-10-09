import random

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY
from mithril_web.curator_data import CuratorData, day

NOW = 1_800_000_000
OWNER, MOD, USER = (char * 32 for char in "abc")
ORIGIN = "https://mithril.foo"


def catalog_feed(updated=1, extra=()):
    filler = [
        {"id": f"FILLER_{n:04}", "name": f"Filler {n}", "tier": "RARE", "npc_sell_price": n + 1}
        for n in range(1000)
    ]
    specials = [
        {"id": "QUIET", "name": "Quiet Ring", "tier": "EPIC", "npc_sell_price": 9001},
        {"id": "HYPED", "name": "Hyped Blade", "tier": "LEGENDARY", "npc_sell_price": 9002},
        {"id": "SKIN", "name": "Fancy Skin", "tier": "EPIC", "category": "COSMETIC"},
        {"id": "TWIN_A", "name": "Twin One", "tier": "RARE", "npc_sell_price": 5000},
        {"id": "TWIN_B", "name": "Twin Two", "tier": "RARE", "npc_sell_price": 5000},
        {
            "id": "GAME_BREAKER",
            "name": "Game Breaker",
            "tier": "SPECIAL",
            "museum": True,
            "has_uuid": True,
        },
        *extra,
    ]
    return {"lastUpdated": updated, "items": [*filler, *specials]}


@pytest.fixture
def store(tmp_path):
    now = [NOW]
    feeds = {"resources/skyblock/items": catalog_feed()}
    data = CuratorData(tmp_path / "curator.sqlite3", loader=feeds.get, clock=lambda: now[0])
    data.load_catalog()
    with data.db:
        data.db.execute("INSERT INTO curator_sales VALUES ('HYPED', ?, 500)", (day(NOW),))
        data.db.execute("INSERT INTO curator_sales VALUES ('QUIET', ?, 3)", (day(NOW - DAY),))
    yield data, feeds, now
    data.close()


def status(data, item):
    return next(row for row in data.review("all", item)["items"] if row["id"] == item)


def test_items_get_a_curation_status(store):
    data, _, _ = store
    assert status(data, "QUIET")["status"] == "eligible"
    assert status(data, "QUIET")["sales"] == 3
    assert status(data, "HYPED")["status"] == "popular"
    assert status(data, "SKIN")["status"] == "cosmetic"
    assert status(data, "TWIN_A")["status"] == "not_unique"
    assert status(data, "GAME_BREAKER")["admin"]
    data.set_cutoff(1000)
    assert status(data, "HYPED")["status"] == "eligible"
    data.set_list("SKIN", "allow", OWNER)
    data.set_list("QUIET", "block", OWNER)
    data.set_list("TWIN_A", "allow", OWNER)
    assert status(data, "SKIN")["status"] == "allowed"
    assert status(data, "QUIET")["status"] == "blocked"
    assert status(data, "TWIN_A")["status"] == "not_unique"
    data.set_list("QUIET", None, OWNER)
    assert status(data, "QUIET")["list"] is None
    with pytest.raises(LookupError):
        data.set_list("MISSING", "allow", OWNER)


def test_review_groups_search_and_pages(store):
    data, feeds, now = store
    assert data.review("admin")["total"] == 1
    assert data.review("pool", "filler 99")["total"] == 11
    page = data.review("pool", offset=50)
    assert page["total"] == 1002 and len(page["items"]) == 50
    data.set_list("SKIN", "allow", OWNER)
    data.set_list("HYPED", "block", OWNER)
    assert [row["id"] for row in data.review("allowed")["items"]] == ["SKIN"]
    assert [row["id"] for row in data.review("blocked")["items"]] == ["HYPED"]
    assert data.review("new")["total"] == data.review("all")["total"]
    now[0] += 60
    data.mark_reviewed()
    now[0] += 60
    feeds["resources/skyblock/items"] = catalog_feed(
        2, [{"id": "FRESH", "name": "Fresh Charm", "tier": "RARE", "npc_sell_price": 77}]
    )
    data.load_catalog()
    assert [row["id"] for row in data.review("new")["items"]] == ["FRESH"]
    overview = data.overview()
    assert overview["new"] == 1
    assert overview["sales_since"] == day(NOW - DAY)
    assert overview["counts"]["not_unique"] == 2


def test_queue_fills_thirty_days_without_repeats_and_keeps_plans(store):
    data, _, now = store
    queue = data.queue(random.Random(1))
    assert len(queue) == 30
    assert queue[0]["day"] == day(NOW) and queue[0]["locked"]
    assert not any(entry["locked"] for entry in queue[1:])
    items = [entry["item"] for entry in queue]
    assert len(set(items)) == 30
    assert not {"HYPED", "SKIN", "TWIN_A", "TWIN_B"} & set(items)
    assert data.queue(random.Random(2)) == queue
    now[0] += DAY
    later = data.queue(random.Random(3))
    assert [entry["item"] for entry in later[:29]] == items[1:]
    assert later[29]["item"] not in items


def test_repeats_start_only_when_the_pool_runs_out(store):
    data, _, _ = store
    while page := data.review("pool", "filler")["items"]:
        for row in page:
            data.set_list(row["id"], "block", OWNER)
    assert {row["id"] for row in data.review("pool")["items"]} == {"QUIET", "GAME_BREAKER"}
    queue = data.queue(random.Random(1))
    assert {entry["item"] for entry in queue[:2]} == {"QUIET", "GAME_BREAKER"}
    assert all(entry["item"] is None for entry in queue[2:])
    with pytest.raises(LookupError):
        data.reroll(queue[1]["day"], OWNER)


def test_owner_can_reroll_or_schedule_coming_days_only(store):
    data, _, _ = store
    queue = data.queue(random.Random(1))
    tomorrow = queue[1]["day"]
    data.reroll(tomorrow, OWNER, random.Random(5))
    assert data.queue()[1]["item"] not in [entry["item"] for entry in queue]
    data.schedule(tomorrow, "GAME_BREAKER", OWNER)
    assert data.queue()[1]["item"] == "GAME_BREAKER"
    for date in (queue[0]["day"], day(NOW - DAY), day(NOW + 30 * DAY)):
        with pytest.raises(ValueError):
            data.schedule(date, "QUIET", OWNER)
    with pytest.raises(ValueError):
        data.schedule(tomorrow, "TWIN_A", OWNER)
    with pytest.raises(LookupError):
        data.schedule(tomorrow, "MISSING", OWNER)


def test_older_catalog_tables_gain_the_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "curator.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE curator_items (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, clues TEXT NOT NULL, family TEXT,
            guessable INTEGER NOT NULL, candidate INTEGER NOT NULL, first_seen REAL NOT NULL)""")
        db.execute("CREATE TABLE curator_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO curator_meta VALUES ('catalog_updated', '1')")
    db.close()
    data = CuratorData(path, loader={"resources/skyblock/items": catalog_feed()}.get)
    data.load_catalog()
    assert status(data, "GAME_BREAKER")["admin"]
    data.close()


@pytest.fixture
def api(tmp_path):
    now = [float(NOW)]
    feeds = {
        "resources/skyblock/items": catalog_feed(),
        "skyblock/auctions_ended": {"auctions": []},
    }
    app = create_app(
        database=tmp_path / "auth.db",
        clock=lambda: now[0],
        owner_uuid=OWNER,
        curator_loader=feeds.get,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.curator.load_catalog()
        headers = {}
        for uuid in (OWNER, MOD, USER):
            token = app.state.auth.issue("session", uuid, "Synthetic", 30 * DAY)
            headers[uuid] = {"Cookie": f"{COOKIE}={token}", "Origin": ORIGIN}
        app.state.moderation.grant(OWNER, MOD, True, "Trusted maintainer")
        yield client, headers


def test_review_api_is_owner_only_and_same_origin(api):
    client, headers = api
    assert client.get("/api/v1/moderation/curator").status_code == 401
    assert client.get("/api/v1/moderation/curator", headers=headers[USER]).status_code == 403
    assert client.get("/api/v1/moderation/curator", headers=headers[MOD]).status_code == 403
    overview = client.get("/api/v1/moderation/curator", headers=headers[OWNER]).json()
    assert len(overview["queue"]) == 30 and overview["sales_cutoff"] == 100
    foreign = {**headers[OWNER], "Origin": "https://example.invalid"}
    body = {"version": 1, "sales_cutoff": 10}
    assert (
        client.post("/api/v1/moderation/curator/settings", headers=foreign, json=body).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/moderation/curator/settings", headers=headers[MOD], json=body
        ).status_code
        == 403
    )


def test_review_api_changes(api):
    client, headers = api
    owner = headers[OWNER]

    def post(path, **body):
        return client.post(f"/api/v1/moderation/curator/{path}", headers=owner, json=body)

    assert post("settings", version=1, sales_cutoff=10).status_code == 200
    assert client.get("/api/v1/moderation/curator", headers=owner).json()["sales_cutoff"] == 10
    assert post("list", version=1, item="SKIN", list="allow").status_code == 200
    assert post("list", version=1, item="MISSING", list="allow").status_code == 404
    assert post("list", version=1, item="bad id!", list="allow").status_code == 422
    items = client.get("/api/v1/moderation/curator/items?group=allowed", headers=owner).json()[
        "items"
    ]
    assert [row["id"] for row in items] == ["SKIN"]
    queue = client.get("/api/v1/moderation/curator", headers=owner).json()["queue"]
    assert post("day", version=1, day=queue[1]["day"], item="GAME_BREAKER").status_code == 200
    assert post("day", version=1, day=queue[2]["day"], item=None).status_code == 200
    assert post("day", version=1, day=queue[0]["day"], item=None).status_code == 409
    assert post("day", version=1, day=queue[1]["day"], item="TWIN_A").status_code == 409
    assert post("reviewed", version=1).status_code == 200
    queue = client.get("/api/v1/moderation/curator", headers=owner).json()["queue"]
    assert queue[1]["item"] == "GAME_BREAKER" and queue[1]["name"] == "Game Breaker"
