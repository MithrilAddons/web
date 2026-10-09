import base64
import gzip
import struct

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.curator_data import CuratorData, sold_item

DAY = 86400
NOW = 1_800_000_000


def nbt(identifier):
    def string(value):
        data = value.encode()
        return struct.pack(">H", len(data)) + data

    def compound(name, content):
        return b"\x0a" + string(name) + content + b"\x00"

    extra = compound("ExtraAttributes", b"\x08" + string("id") + string(identifier))
    item = compound("tag", extra) + b"\x01" + string("Count") + struct.pack("b", 1) + b"\x00"
    root = compound("", b"\x09" + string("i") + b"\x0a" + struct.pack(">i", 1) + item)
    return base64.b64encode(gzip.compress(root)).decode()


def sale(auction, identifier, when=NOW):
    return {"auction_id": auction, "timestamp": int(when * 1000), "item_bytes": nbt(identifier)}


def items(count=1000, updated=1, **extra):
    listed = [
        {"id": f"FILLER_{n:04}", "name": f"Filler {n}", "tier": "RARE", "npc_sell_price": n + 1}
        for n in range(count)
    ]
    return {"lastUpdated": updated, "items": [*listed, *extra.values()]}


@pytest.fixture
def store(tmp_path):
    now = [NOW]
    feeds = {"skyblock/auctions_ended": {"auctions": []}, "resources/skyblock/items": items()}
    data = CuratorData(
        tmp_path / "curator.sqlite3", loader=lambda path: feeds[path], clock=lambda: now[0]
    )
    yield data, feeds, now
    data.close()


def test_sold_item_reads_the_skyblock_id_and_rejects_bad_payloads():
    assert sold_item({"item_bytes": nbt("HYPERION")}) == "HYPERION"
    assert sold_item({"item_bytes": "not base64!"}) is None
    assert sold_item({"item_bytes": nbt("X" * 200)}) is None
    assert sold_item({}) is None


def test_sales_are_counted_once_per_auction_and_day(store):
    data, feeds, now = store
    feeds["skyblock/auctions_ended"] = {
        "auctions": [
            sale("a1", "HYPERION"),
            sale("a2", "HYPERION", NOW - DAY),
            sale("a3", "SYNTHESIZER_V3"),
            sale("a4", "OLD", NOW - 2 * DAY),
            sale("a5", "FUTURE", NOW + 3600),
            {"auction_id": "a6", "timestamp": "soon", "item_bytes": nbt("BAD")},
            {"auction_id": 7, "timestamp": NOW * 1000, "item_bytes": nbt("BAD")},
            {"auction_id": "a8", "timestamp": NOW * 1000, "item_bytes": "broken"},
        ]
    }
    data.load_sales()
    data.load_sales()
    assert data.sales() == {"HYPERION": 2, "SYNTHESIZER_V3": 1}
    assert data.sales(days=1) == {"HYPERION": 1, "SYNTHESIZER_V3": 1}
    now[0] += 40 * DAY
    feeds["skyblock/auctions_ended"] = {"auctions": [sale("b1", "HYPERION", now[0])]}
    data.load_sales()
    assert data.sales() == {"HYPERION": 1}
    now[0] += 30 * DAY
    data.load_sales()
    rows = data.db.execute("SELECT COUNT(*) FROM curator_sales").fetchone()[0]
    assert rows == 1
    assert data.db.execute("SELECT COUNT(*) FROM curator_seen").fetchone()[0] == 0


def test_catalog_refreshes_only_when_hypixel_updates_it(store):
    data, feeds, now = store
    synth = {"id": "SYNTHESIZER_V3", "name": "Synthesizer v3", "tier": "EPIC", "npc_sell_price": 1}
    feeds["resources/skyblock/items"] = items(synth=synth)
    data.load_catalog()
    known = data.items()
    assert len(known) == 1001
    assert known["SYNTHESIZER_V3"]["candidate"]
    assert known["SYNTHESIZER_V3"]["clues"]["length"] == 14
    feeds["resources/skyblock/items"] = items(updated=1)
    data.load_catalog()
    assert "SYNTHESIZER_V3" in data.items()
    feeds["resources/skyblock/items"] = items(updated=2)
    data.load_catalog()
    assert "SYNTHESIZER_V3" not in data.items()
    first_seen = data.db.execute(
        "SELECT first_seen FROM curator_items WHERE id='SYNTHESIZER_V3'"
    ).fetchone()[0]
    assert first_seen == NOW


@pytest.mark.parametrize("response", [{"lastUpdated": 3, "items": []}, {"items": []}])
def test_invalid_catalogs_are_rejected(store, response):
    data, feeds, _ = store
    feeds["resources/skyblock/items"] = response
    with pytest.raises((ValueError, KeyError)):
        data.load_catalog()


def test_refresh_retries_failed_feeds_after_a_minute(store):
    data, feeds, now = store
    feeds["skyblock/auctions_ended"] = {"auctions": "broken"}
    data.refresh()
    assert data.next["sales"] == NOW + 60
    assert data.next["catalog"] == NOW + 6 * 3600
    feeds["skyblock/auctions_ended"] = {"auctions": [sale("c1", "HYPERION")]}
    data.refresh()
    assert data.sales() == {}
    now[0] += 60
    data.refresh()
    assert data.sales() == {"HYPERION": 1}


def test_app_collects_curator_data_beside_the_auth_database(tmp_path):
    calls = []

    def loader(path):
        calls.append(path)
        raise ValueError("offline")

    with TestClient(create_app(database=tmp_path / "auth.sqlite3", curator_loader=loader)):
        pass
    assert (tmp_path / "curator.sqlite3").exists()
