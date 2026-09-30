import asyncio
import sqlite3
from unittest.mock import Mock

import pytest
from mithril_web.pet_market import kat_cost, pet_quotes, price_history
from mithril_web.slayer_market import SlayerMarket, pet_listing
from test_slayer_market import nbt_item


def listings(*, rarity="LEGENDARY", start=100, end=1000, kind="SYNTHETIC"):
    return [
        {
            "name": "Synthetic pet",
            "rarity": rarity,
            "kind": kind,
            "level": level,
            "price": price,
            "xp": 0,
        }
        for level, price in [(1, start), (100, end)]
        for _ in range(3)
    ]


def test_weekly_history_survives_restart_deduplicates_and_expires(tmp_path):
    path = tmp_path / "prices.sqlite3"
    for hour in range(24):
        quotes = pet_quotes(listings(), history_path=path, now=hour * 3600)
    assert quotes[0]["historyHours"] == 24
    assert pet_quotes(listings(), history_path=path, now=23 * 3600)[0]["historyHours"] == 24
    # Each call opens a new connection, including after the service restarts.
    for hour in range(24, 200):
        quotes = pet_quotes(listings(), history_path=path, now=hour * 3600)
    assert quotes[0]["historyHours"] == 168
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM pet_prices").fetchone()[0] == 336
        assert db.execute("SELECT MIN(hour) FROM pet_prices").fetchone()[0] == 32
    assert pet_quotes(listings(), history_path=path, now=400 * 3600)[0]["historyHours"] == 1


def test_spike_is_excluded_without_poisoning_the_running_average(tmp_path):
    path = tmp_path / "prices.sqlite3"
    for hour in range(24):
        pet_quotes(listings(), history_path=path, now=hour * 3600)
    assert pet_quotes(listings(end=10000), history_path=path, now=24 * 3600) == []
    assert pet_quotes(listings(start=10), history_path=path, now=25 * 3600) == []
    recovered = pet_quotes(listings(), history_path=path, now=26 * 3600)[0]
    assert recovered["endPrice"] == 1000
    assert recovered["startPrice"] == 100


def test_provisional_prices_and_conservative_current_price_bounds(tmp_path):
    path = tmp_path / "prices.sqlite3"
    first = pet_quotes(listings(), history_path=path, now=0)[0]
    assert first["historyHours"] == 1  # Immediate estimate, no invented history.
    changed = pet_quotes(listings(start=120, end=1200), history_path=path, now=3600)[0]
    assert changed["startPrice"] == 120
    assert changed["endPrice"] == 1000
    falling = pet_quotes(listings(start=90, end=900), history_path=path, now=7200)[0]
    assert falling["startPrice"] == 110
    assert falling["endPrice"] == 900


def test_divergent_initial_prices_do_not_break_collection(tmp_path):
    path = tmp_path / "prices.sqlite3"
    for hour, end in enumerate([1000, 100000, 1000, 1000]):
        pet_quotes(listings(end=end), history_path=path, now=hour * 3600)


def test_sparse_spread_and_nonprofitable_pairs_are_excluded():
    pets = listings()
    assert pet_quotes(pets[1:]) == []
    pets[2]["price"] = 10000
    assert pet_quotes(pets) == []
    assert pet_quotes(listings(start=1000, end=100)) == []
    assert pet_quotes(listings(rarity="COMMON")) == []


@pytest.fixture
def recipe(monkeypatch):
    upgrades = [
        {"coins": 1000, "seconds": seconds, "items": {"SYNTHETIC_MATERIAL": 2}}
        for seconds in (10, 86400, 86401, 172800)
    ]
    monkeypatch.setattr("mithril_web.pet_market.KAT_RECIPES", {"SYNTHETIC": {"upgrades": upgrades}})
    return {"SYNTHETIC_MATERIAL": {"instant": 1, "offer": 100}}


def test_common_route_uses_legendary_xp_all_fees_materials_and_rounded_flowers(recipe):
    cost = kat_cost("SYNTHETIC", recipe, 200)
    assert cost == {
        "coins": 2800,
        "materials": 800,
        "flowers": 6,
        "flowerCost": 1200,
        "total": 4800,
    }
    pets = listings(rarity="COMMON", end=100000) + listings(end=10000)
    quotes = pet_quotes(pets, bazaar=recipe, flower_price=200)
    common = next(q for q in quotes if q["rarity"] == "COMMON")
    assert common["requiredXp"] == 25353230
    assert common["endRarity"] == "LEGENDARY"
    assert common["endPrice"] == 10000  # Never the expensive level 100 Common.
    assert common["kat"] == cost
    assert quotes[0]["rarity"] == "LEGENDARY"  # Upgrade costs affect ranking.


def test_kat_excludes_missing_prices_unknown_recipes_and_losses(recipe):
    assert kat_cost("SYNTHETIC", {}, 200) is None
    assert kat_cost("SYNTHETIC", recipe, 0) is None
    assert kat_cost("UNKNOWN", recipe, 200) is None
    quotes = pet_quotes(listings(rarity="COMMON") + listings(), bazaar=recipe, flower_price=200)
    assert all(q["rarity"] != "COMMON" for q in quotes)


@pytest.mark.parametrize("extra", [{"skin": "SYNTHETIC_SKIN"}, {"heldItem": "PET_ITEM_TIER_BOOST"}])
def test_cosmetics_and_tier_boost_are_not_leveling_profit(extra):
    assert (
        pet_listing(
            {
                "item_name": "[Lvl 100] Synthetic pet",
                "item_lore": "Combat Pet",
                "starting_bid": 1000,
                "item_bytes": nbt_item(pet={"tier": "LEGENDARY", "exp": 25353230, **extra}),
            }
        )
        is None
    )


def test_history_contains_only_aggregate_prices(tmp_path):
    path = tmp_path / "prices.sqlite3"
    pet_quotes(listings(), history_path=path)
    with sqlite3.connect(path) as db:
        columns = [r[1] for r in db.execute("PRAGMA table_info(pet_prices)")]
        assert columns == ["name", "rarity", "level", "hour", "price"]
    price_history({}, path, 8 * 86400)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM pet_prices").fetchone()[0] == 0


def test_history_collects_without_visitors(tmp_path):
    cache = SlayerMarket()
    cache.history_path = tmp_path / "prices.sqlite3"
    cache.refresh = Mock()

    async def run():
        task = asyncio.create_task(cache.run())
        for _ in range(100):
            if cache.refresh.called:
                break
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    cache.refresh.assert_called_once_with(background=True)


def test_idle_collection_only_refreshes_pet_price_feeds():
    cache = SlayerMarket()
    cache.load_bazaar = Mock(return_value={})
    cache.load_auctions = Mock(return_value=({}, []))
    cache.load_npc = Mock()
    cache.load_sales = Mock()
    cache.refresh(background=True)
    cache.load_bazaar.assert_called_once()
    cache.load_auctions.assert_called_once()
    cache.load_npc.assert_not_called()
    cache.load_sales.assert_not_called()
