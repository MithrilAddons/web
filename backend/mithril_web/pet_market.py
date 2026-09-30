"""Aggregate pet prices, bounded weekly history, and fully costed Kat routes."""

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from statistics import mean, median

KAT_DATA = json.loads(Path(__file__).with_name("kat_data.json").read_text())
KAT_RECIPES = KAT_DATA["pets"]
KAT_ITEMS = {
    item for pet in KAT_RECIPES.values() for step in pet["upgrades"] for item in step["items"]
}
XP_100 = dict(
    zip(
        ("COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC"),
        (5624785, 8644220, 12626665, 18608500, 25353230, 25353230),
        strict=True,
    )
)
WEEK_HOURS = 168


def price_history(points, path, now):
    """One aggregate per endpoint/hour; no listings, identifiers, or player data.

    Keep outliers in history so sustained market changes can eventually establish
    a new baseline. A median filter prevents brief spikes inflating that baseline.
    Connections belong to this background call and close before returning.
    """
    hour = int(now // 3600)
    with closing(sqlite3.connect(path or ":memory:")) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS pet_prices ("
            "name TEXT, rarity TEXT, level INTEGER, hour INTEGER, price REAL, "
            "PRIMARY KEY (name, rarity, level, hour))"
        )
        db.execute("DELETE FROM pet_prices WHERE hour <= ? OR hour > ?", (hour - WEEK_HOURS, hour))
        result = {}
        for key, point in points.items():
            prices = [
                row[0]
                for row in db.execute(
                    "SELECT price FROM pet_prices WHERE name=? AND rarity=? AND level=? "
                    "AND hour < ? ORDER BY hour",
                    (*key, hour),
                )
            ]
            # Never overwrite a bucket on refresh/restart or count it twice.
            db.execute(
                "INSERT OR IGNORE INTO pet_prices VALUES (?, ?, ?, ?, ?)",
                (*key, hour, point["price"]),
            )
            current_bucket = db.execute(
                "SELECT price FROM pet_prices WHERE name=? AND rarity=? AND level=? AND hour=?",
                (*key, hour),
            ).fetchone()[0]
            reference = prices or [current_bucket]
            middle = median(reference)
            filtered = [p for p in reference if middle / 1.5 <= p <= middle * 1.5]
            average = mean(filtered) if filtered else middle
            # Protect against both inflated sale prices and implausibly cheap buys.
            if len(prices) >= 24 and not average / 1.5 <= point["price"] <= average * 1.5:
                continue
            result[key] = {**point, "average": average, "historyHours": len(prices) + 1}
        return result


def kat_cost(kind, bazaar, flower_price):
    recipe = KAT_RECIPES.get(kind)
    if not recipe or not flower_price or flower_price <= 0:
        return None
    fees = materials = 0
    flowers = 0
    for step in recipe["upgrades"]:
        # Full Legendary XP makes the pet level 100 at every intermediate rarity.
        fees += step["coins"] * 0.7
        flowers += math.ceil(step["seconds"] / 86400)
        for item, amount in step["items"].items():
            price = bazaar.get(item, {}).get("offer", 0)  # Instant-buy cost.
            if not price or price <= 0:
                return None
            materials += amount * price
    return {
        "coins": fees,
        "materials": materials,
        "flowers": flowers,
        "flowerCost": flowers * flower_price,
        "total": fees + materials + flowers * flower_price,
    }


def pet_quotes(listings, *, bazaar=None, flower_price=None, history_path=None, now=0):
    groups = {}
    for item in listings:
        groups.setdefault((item["name"], item["rarity"], item["level"]), []).append(item)
    points = {}
    for key, group in groups.items():
        lowest = sorted(group, key=lambda p: p["price"])[:3]
        # Sparse or widely separated asks cannot support a leveling recommendation.
        if len(lowest) < 3 or lowest[-1]["price"] > lowest[0]["price"] * 1.25:
            continue
        experiences = [p["xp"] for p in lowest if p["xp"] is not None]
        points[key] = {
            "price": mean(p["price"] for p in lowest),
            "xp": mean(experiences) if len(experiences) == len(lowest) else None,
            "kind": lowest[0].get("kind", ""),
            "samples": len(lowest),
        }
    stable = price_history(points, history_path, now)
    result = []
    for (name, rarity, level), start in stable.items():
        golden = name.lower() == "golden dragon"
        if (golden and not 100 <= level < 200) or (not golden and level != 1):
            continue
        end_rarity = "LEGENDARY" if rarity == "COMMON" else rarity
        end_level = 200 if golden else 100
        end = stable.get((name, end_rarity, end_level))
        if not end:
            continue
        kat = None
        if rarity == "COMMON":
            kat = kat_cost(start["kind"], bazaar or {}, flower_price)
            if kat is None:
                continue
        xp = XP_100[end_rarity]
        if golden:
            if start["xp"] is None and level != 100:
                continue
            xp = 214023230 - (start["xp"] if start["xp"] is not None else XP_100[rarity])
        # Historical cheap buys/high sales must not hide today's worse prices.
        start_price = max(start["price"], start["average"])
        end_price = min(end["price"], end["average"])
        cost = kat["total"] if kat else 0
        if xp > 0 and end_price > start_price + cost:
            result.append(
                {
                    "name": name,
                    "rarity": rarity,
                    "endRarity": end_rarity,
                    "startLevel": level,
                    "endLevel": end_level,
                    "startPrice": start_price,
                    "endPrice": end_price,
                    "requiredXp": xp,
                    "samples": start["samples"] + end["samples"],
                    "historyHours": min(start["historyHours"], end["historyHours"]),
                    "kat": kat,
                }
            )
    ranked = sorted(
        result,
        key=lambda p: (
            (p["endPrice"] - p["startPrice"] - (p["kat"]["total"] if p["kat"] else 0))
            / p["requiredXp"]
        ),
        reverse=True,
    )
    unique = {}
    for quote in ranked:
        unique.setdefault((quote["name"], quote["rarity"]), quote)
    return list(unique.values())[:100]
