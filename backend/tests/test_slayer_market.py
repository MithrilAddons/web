import base64
import gzip
import json
import struct
import zlib
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.slayer_market import (
    MAX_BODY,
    SlayerMarket,
    choose_quote,
    decode_item,
    fetch_json,
    pet_listing,
    pet_quotes,
)


def nbt_item(name="Warden Heart", pet=None):
    def string(value):
        data = value.encode()
        return struct.pack(">H", len(data)) + data

    def compound(name, content):
        return b"\x0a" + string(name) + content + b"\x00"

    display = compound("display", b"\x08" + string("Name") + string(name))
    extra = compound("ExtraAttributes", b"\x08" + string("petInfo") + string(json.dumps(pet)))
    item = compound("tag", display + extra) + b"\x00"
    root = compound("", b"\x09" + string("i") + b"\x0a" + struct.pack(">i", 1) + item)
    return base64.b64encode(gzip.compress(root)).decode()


def page(number=0, pages=1, generation=1000, prices=(100, 101, 102)):
    return {
        "page": number,
        "totalPages": pages,
        "lastUpdated": generation,
        "auctions": [{"bin": True, "item_name": "Warden Heart", "starting_bid": p} for p in prices],
    }


def market_loader(path):
    if path == "skyblock/bazaar":
        return {"products": {"REVENANT_FLESH": {"quick_status": {"sellPrice": 10, "buyPrice": 20}}}}
    if path == "resources/skyblock/items":
        return {"items": [{"id": "FOUL_FLESH", "npc_sell_price": 25000}]}
    if path == "skyblock/auctions_ended":
        return {"auctions": []}
    return page()


@pytest.mark.parametrize(
    "bins,sales,source,price",
    [
        ([100, 102, 104], [500, 500, 500], "BIN", 102),
        ([100, 200, 300], [120, 120, 120], "Recent sales", 120),
        ([100], [], "Unstable BIN", 100),
        ([], [150], "Recent sales", 150),
    ],
)
def test_quote_selection_matches_original(bins, sales, source, price):
    result = choose_quote(bins, sales)
    assert result["source"] == source
    assert result["price"] == price
    assert choose_quote([], []) is None


def test_nbt_and_pet_experience_are_decoded_without_player_data():
    encoded = nbt_item("[Lvl 150] Golden Dragon", {"tier": "LEGENDARY", "exp": 100000000})
    assert decode_item(encoded)["display"]["Name"] == "[Lvl 150] Golden Dragon"
    pet = pet_listing(
        {
            "item_name": "[Lvl 150] Golden Dragon",
            "item_lore": "§6Combat Pet",
            "item_bytes": encoded,
            "starting_bid": 1000000000,
        }
    )
    assert pet["xp"] == 100000000
    pairs = pet_quotes([pet, {**pet, "level": 200, "price": 2000000000}])
    assert pairs[0]["requiredXp"] == 114023230
    assert pairs[0]["startLevel"] == 150


@pytest.mark.parametrize(
    "encoded",
    [
        "!not-base64!",
        base64.b64encode(gzip.compress(b"bad")).decode(),
        base64.b64encode(gzip.compress(b"a" * (2 * 1024 * 1024 + 1))).decode(),
    ],
)
def test_invalid_or_oversized_item_rejected(encoded):
    with pytest.raises((ValueError, OSError)):
        decode_item(encoded)


def test_pet_pairs_use_lowest_three_and_reject_losses():
    pets = [
        {"name": "Synthetic Pet", "rarity": "LEGENDARY", "level": level, "price": price, "xp": 0}
        for level, price in [(1, 100), (1, 110), (1, 120), (1, 99999), (100, 1000)]
    ]
    assert pet_quotes(pets)[0]["startPrice"] == 110
    assert pet_quotes(pets)[0]["requiredXp"] == 25353230
    assert pet_quotes([{**p, "price": 1 if p["level"] == 100 else 100} for p in pets]) == []


def test_cache_single_refresh_cadence_failures_and_expiry():
    now = [100000]
    loader = Mock(side_effect=market_loader)
    cache = SlayerMarket(loader=loader, clock=lambda: now[0])
    assert cache.get()["feeds"]["bazaar"]["status"] == "loading"
    cache.refresh()
    assert loader.call_count == 4
    result = cache.get()
    assert result["bazaar"]["REVENANT_FLESH"] == {"instant": 10, "offer": 20}
    assert result["npc"]["FOUL_FLESH"] == 25000
    assert result["auctions"]["Warden Heart"]["price"] == 101
    cache.refresh()
    assert loader.call_count == 4
    now[0] += 901
    loader.side_effect = ValueError("upstream outage")
    cache.refresh()
    assert cache.get()["feeds"]["bazaar"]["status"] == "stale"
    assert cache.get()["bazaar"] == result["bazaar"]
    attempts = loader.call_count
    cache.refresh()
    assert loader.call_count == attempts
    now[0] += 86401
    assert cache.get()["bazaar"] == {}
    assert cache.get()["auctions"] == {}


def test_missing_upstream_prices_are_not_fabricated():
    cache = SlayerMarket(loader=lambda _: {"wrong": []})
    cache.refresh()
    snapshot = cache.get()
    assert snapshot["bazaar"] == {}
    assert snapshot["auctions"] == {}
    assert all(feed["status"] == "unavailable" for feed in snapshot["feeds"].values())


def test_corrupt_compressed_feed_does_not_stop_future_refreshes():
    loader = Mock(side_effect=zlib.error("corrupt compression"))
    now = [100000]
    cache = SlayerMarket(loader=loader, clock=lambda: now[0])
    cache.refresh()
    assert cache.get()["feeds"]["bazaar"]["status"] == "unavailable"
    loader.side_effect = market_loader
    now[0] += 61
    cache.refresh()
    assert cache.get()["feeds"]["bazaar"]["status"] == "ready"


def test_auction_pages_must_belong_to_one_snapshot():
    cache = SlayerMarket(loader=lambda path: page(int(path[-1]), 2, 1000 + int(path[-1])))
    with pytest.raises(ValueError, match="snapshot changed"):
        cache.load_auctions()
    assert cache.bins == {}


def test_auction_scan_merges_pages_and_bounds_page_count():
    cache = SlayerMarket(loader=lambda path: page(int(path[-1]), 3, prices=[100 + int(path[-1])]))
    bins, _ = cache.load_auctions()
    assert bins["Warden Heart"] == [100, 101, 102]
    cache.loader = lambda _: page(pages=201)
    with pytest.raises(ValueError, match="page count"):
        cache.load_auctions()


def test_recent_sales_deduplicate_expire_and_bound_history():
    now = 100000
    auctions = [
        {
            "bin": True,
            "item_bytes": nbt_item(),
            "auction_id": str(i),
            "timestamp": (now - i) * 1000,
            "price": 100 + i,
        }
        for i in range(30)
    ]
    cache = SlayerMarket(loader=lambda _: {"auctions": auctions}, clock=lambda: now)
    cache.sales = cache.load_sales()
    assert len(cache.sales["Warden Heart"]) == 20
    assert cache.load_sales() == cache.sales
    cache.clock = lambda: now + 86401
    assert not cache.load_sales()["Warden Heart"]


@pytest.mark.parametrize(
    "status,body",
    [(429, b"{}"), (200, b"{broken"), (200, b"x" * (MAX_BODY + 1)), (200, b'{"success": false}')],
    ids=["throttled", "malformed", "oversized", "failed"],
)
def test_network_response_failures(monkeypatch, status, body):
    response = Mock(status=status)
    response.getheader.return_value = "identity"
    response.read.return_value = body
    connection = Mock()
    connection.getresponse.return_value = response
    monkeypatch.setattr(
        "mithril_web.slayer_market.http.client.HTTPSConnection", lambda *a, **k: connection
    )
    with pytest.raises(ValueError):
        fetch_json("skyblock/bazaar")
    connection.close.assert_called_once()


def test_price_endpoint_is_public_nonblocking_and_does_not_set_cookie(tmp_path):
    loader = Mock(side_effect=market_loader)
    app = create_app(database=tmp_path / "auth.db", slayer_loader=loader)
    with TestClient(app, base_url="https://mithril.foo") as client:
        response = client.get("/api/v1/slayer-prices")
        assert response.status_code == 200
        assert response.json()["version"] == 1
        assert "set-cookie" not in response.headers
        assert response.headers["cache-control"] == "no-store"
