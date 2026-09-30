"""Shared, keyless Hypixel prices for the Slayer calculator; no player lookups.

Only aggregate quotes leave this service. Drop sales are in memory;
aggregate pet prices persist.
"""

import asyncio
import base64
import gzip
import http.client
import io
import json
import math
import re
import sqlite3
import struct
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .pet_market import KAT_ITEMS, XP_100, pet_quotes

CATALOGUE = json.loads(Path(__file__).with_name("slayer_data.json").read_text())
DROPS = [d for s in CATALOGUE for t in s["tiers"] for d in t["drops"]]
TARGETS = sorted({d["auctionName"] for d in DROPS if not d["bazaarId"]}, key=len, reverse=True)
BAZAAR_IDS = {d["bazaarId"] for d in DROPS if d["bazaarId"]} | KAT_ITEMS | {"KAT_FLOWER"}
NPC_KEYS = BAZAAR_IDS | {d[k] for d in DROPS for k in ("name", "auctionName")}
FORMATTING = re.compile(r"§[0-9A-FK-OR]", re.I)
PET_NAME = re.compile(r"^\[Lvl (\d+)] (.+)$")
PERIODS = {"bazaar": 300, "npc": 3600, "auctions": 900, "sales": 60}
MAX_BODY = 16 * 1024 * 1024
KAT_FLOWER = "Kat Flower"


def positive(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def clean(value):
    return FORMATTING.sub("", value).strip() if isinstance(value, str) else ""


def target_name(value):
    name = clean(value).casefold()
    return next((target for target in TARGETS if target.casefold() in name), None)


def fetch_json(path):
    connection = http.client.HTTPSConnection("api.hypixel.net", timeout=8)
    try:
        connection.request(
            "GET",
            "/v2/" + path,
            headers={"User-Agent": "Mithril-Web/SlayerProfits", "Accept-Encoding": "gzip"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Market service unavailable")
        data = response.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            raise ValueError("Market response too large")
        encoding = response.getheader("Content-Encoding", "identity")
        if encoding == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as zipped:
                data = zipped.read(MAX_BODY + 1)
        elif encoding != "identity":
            raise ValueError("Unsupported response encoding")
        if len(data) > MAX_BODY:
            raise ValueError("Market response too large")
        result = json.loads(data)
        if not isinstance(result, dict) or result.get("success") is not True:
            raise ValueError("Invalid market response")
        return result
    finally:
        connection.close()


def decode_item(encoded, *, with_count=False):
    """Read bounded standard NBT from the official API's gzipped item payload."""
    if not isinstance(encoded, str) or len(encoded) > 3_000_000:
        raise ValueError("Invalid item")
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(encoded, validate=True))) as zipped:
        data = zipped.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Item too large")
    reader = _NbtReader(data)
    if reader.number(">B") != 10:
        raise ValueError("Expected NBT compound")
    reader.string()
    item = reader.tag(10)["i"][0]
    return (item["tag"], item["Count"]) if with_count else item["tag"]


class _NbtReader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.size = len(data)
        self.budget = 50000

    def read(self, size):
        if size < 0 or size > self.size:
            raise ValueError("Invalid NBT length")
        value = self.stream.read(size)
        if len(value) != size:
            raise ValueError("Truncated NBT")
        return value

    def number(self, fmt):
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))[0]

    def string(self):
        return self.read(self.number(">H")).decode("utf-8", errors="replace")

    def tag(self, kind, depth=0):
        self.budget -= 1
        if depth > 32 or self.budget < 0:
            raise ValueError("NBT too complex")
        if kind in (1, 2, 3, 4, 5, 6):
            return self.number({1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}[kind])
        if kind == 8:
            return self.string()
        if kind in (7, 11, 12):
            self.read(self.number(">i") * {7: 1, 11: 4, 12: 8}[kind])
            return None
        if kind == 9:
            return self.sequence(depth)
        if kind == 10:
            return self.compound(depth)
        raise ValueError("Invalid NBT tag")

    def sequence(self, depth):
        child, count = self.number(">B"), self.number(">i")
        if not 0 <= count <= self.budget:
            raise ValueError("NBT list too large")
        return [self.tag(child, depth + 1) for _ in range(count)]

    def compound(self, depth):
        result = {}
        while (child := self.number(">B")) != 0:
            name = self.string()
            result[name] = self.tag(child, depth + 1)
        return result


def choose_quote(bins, sales):
    lowest = sorted(p for p in bins if positive(p))[:3]
    sales = [p for p in sales if positive(p)]
    spread = (lowest[-1] - lowest[0]) / lowest[0] if len(lowest) >= 2 else 0
    if len(lowest) >= 3 and spread <= 0.05:
        samples, source = lowest, "BIN"
    elif len(sales) >= 3:
        samples, source = sales, "Recent sales"
    elif lowest:
        samples, source = lowest, "Unstable BIN"
    elif sales:
        samples, source = sales, "Recent sales"
    else:
        return None
    return {
        "price": sum(samples) / len(samples),
        "source": source,
        "samples": len(samples),
        "spread": spread,
    }


def pet_listing(auction):
    match = PET_NAME.fullmatch(clean(auction.get("item_name")))
    if (
        not match
        or "wisp" in match[2].lower()
        or "Combat Pet" not in clean(auction.get("item_lore"))
    ):
        return None
    level = int(match[1])
    if level != 1 and not 100 <= level <= 200:
        return None
    try:
        info = json.loads(decode_item(auction.get("item_bytes"))["ExtraAttributes"]["petInfo"])
        if info.get("skin") or info.get("heldItem") == "PET_ITEM_TIER_BOOST":
            return None
        rarity = info.get("tier") or auction.get("tier", "")
        xp = info.get("exp")
        if rarity not in XP_100 or (xp is not None and (not positive(xp) and xp != 0)):
            return None
        return {
            "name": match[2].strip(),
            "kind": info.get("type", ""),
            "rarity": rarity,
            "level": level,
            "price": auction["starting_bid"],
            "xp": xp,
        }
    except (
        ValueError,
        OSError,
        EOFError,
        zlib.error,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ):
        return None


def auction_unit_price(auction):
    name = clean(auction.get("item_name"))
    price = auction["starting_bid"]
    if name != KAT_FLOWER:
        return target_name(name), price
    try:
        _, count = decode_item(auction.get("item_bytes"), with_count=True)
        if not isinstance(count, int) or not 1 <= count <= 64:
            return None, price
        return name, price / count
    except (ValueError, OSError, EOFError, zlib.error, KeyError, IndexError, TypeError):
        return None, price


def collect_auction_page(page, expected, first, bins, pets):
    if (
        page["page"] != expected
        or page["totalPages"] != first["totalPages"]
        or page["lastUpdated"] != first["lastUpdated"]
    ):
        raise ValueError("Auction snapshot changed; retry later")
    auctions = page["auctions"]
    if not isinstance(auctions, list) or len(auctions) > 1000:
        raise ValueError("Invalid auction page")
    for auction in auctions:
        price = auction.get("starting_bid")
        if auction.get("bin") is not True or not positive(price):
            continue
        name, price = auction_unit_price(auction)
        if name:
            bins[name] = sorted([*bins.get(name, []), price])[:3]
        pet = pet_listing(auction)
        if pet:
            pets.append(pet)


class SlayerMarket:
    def __init__(self, loader=None, clock=time.time):
        self.loader, self.clock = loader or fetch_json, clock
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.active_until = 0
        self.next = dict.fromkeys(PERIODS, 0)
        self.feeds = {name: {"status": "loading", "updated": None} for name in PERIODS}
        self.bazaar, self.npc, self.bins, self.sales = {}, {}, {}, {}
        self.pets = []
        self.history_path = None

    def get(self):
        with self.lock:
            now = self.clock()
            self.active_until = now + 900
            feeds = self.feed_snapshot(now)

            def available(name):
                return feeds[name]["status"] != "unavailable"

            quotes = {}
            for name in TARGETS:
                recent = (
                    [p for _, p, when in self.sales.get(name, []) if now - 86400 <= when <= now]
                    if available("sales")
                    else []
                )
                quote = choose_quote(
                    self.bins.get(name, []) if available("auctions") else [], recent
                )
                if quote:
                    quotes[name] = quote
            return {
                "version": 1,
                "bazaar": self.bazaar if available("bazaar") else {},
                "npc": self.npc if available("npc") else {},
                "auctions": quotes,
                "pets": self.pets if available("auctions") else [],
                "feeds": feeds,
            }

    def feed_snapshot(self, now):
        feeds = {name: dict(feed) for name, feed in self.feeds.items()}
        for name, feed in feeds.items():
            if feed["updated"] is not None and now - feed["updated"] > PERIODS[name]:
                feed["status"] = "stale"
            if feed["updated"] is not None and now - feed["updated"] > 86400:
                feed["status"] = "unavailable"
        return feeds

    async def run(self):
        try:
            while True:
                if self.clock() < self.active_until or self.history_path is not None:
                    await asyncio.to_thread(
                        self.refresh, background=self.clock() >= self.active_until
                    )
                await asyncio.sleep(1)
        finally:
            self.stopped.set()

    def refresh(self, *, background=False):
        for name in PERIODS:
            if background and name in ("npc", "sales"):
                continue
            if self.stopped.is_set() or self.clock() < self.next[name]:
                continue
            try:
                value = getattr(self, "load_" + name)()
                with self.lock:
                    if name == "auctions":
                        self.bins, self.pets = value
                    else:
                        setattr(self, name, value)
                    self.feeds[name] = {"status": "ready", "updated": self.clock()}
                self.next[name] = self.clock() + PERIODS[name]
            except (
                OSError,
                sqlite3.Error,
                zlib.error,
                ValueError,
                http.client.HTTPException,
                KeyError,
                TypeError,
                IndexError,
                AttributeError,
            ):
                with self.lock:
                    self.feeds[name] = {
                        **self.feeds[name],
                        "status": "stale"
                        if self.feeds[name]["updated"] is not None
                        else "unavailable",
                    }
                self.next[name] = self.clock() + 60

    def load_bazaar(self):
        products = self.loader("skyblock/bazaar")["products"]
        result = {}
        for name in BAZAAR_IDS:
            status = products.get(name, {}).get("quick_status", {})
            instant, offer = status.get("sellPrice", 0), status.get("buyPrice", 0)
            result[name] = {
                "instant": instant if positive(instant) else 0,
                "offer": offer if positive(offer) else 0,
            }
        if not any(v["instant"] or v["offer"] for v in result.values()):
            raise ValueError("No Bazaar prices")
        return result

    def load_npc(self):
        result = {}
        for item in self.loader("resources/skyblock/items")["items"]:
            price = item.get("npc_sell_price")
            if positive(price):
                for key in (item.get("id"), item.get("name")):
                    if key in NPC_KEYS:
                        result[key] = max(result.get(key, 0), price)
        return result

    def load_auctions(self):
        first = self.loader("skyblock/auctions?page=0")
        pages = first["totalPages"]
        if not isinstance(pages, int) or not 1 <= pages <= 200:
            raise ValueError("Invalid auction page count")
        bins, pets = {}, []
        started = time.monotonic()

        collect_auction_page(first, 0, first, bins, pets)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for batch in range(1, pages, 4):
                if self.stopped.is_set() or time.monotonic() - started > 90:
                    raise ValueError("Auction scan interrupted")
                numbers = list(range(batch, min(batch + 4, pages)))
                futures = [pool.submit(self.loader, f"skyblock/auctions?page={n}") for n in numbers]
                for n, future in zip(numbers, futures, strict=True):
                    collect_auction_page(future.result(), n, first, bins, pets)
        updated = self.feeds["bazaar"]["updated"]
        bazaar = self.bazaar if updated is not None and self.clock() - updated <= 86400 else {}
        flower = bazaar.get("KAT_FLOWER", {}).get("offer", 0)
        if not flower and bins.get(KAT_FLOWER):
            flower = sum(bins[KAT_FLOWER]) / len(bins[KAT_FLOWER])
        return bins, pet_quotes(
            pets,
            bazaar=bazaar,
            flower_price=flower,
            history_path=self.history_path,
            now=self.clock(),
        )

    def load_sales(self):
        now = self.clock()
        recent = {
            name: [r for r in rows if now - 86400 <= r[2] <= now]
            for name, rows in self.sales.items()
        }
        auctions = self.loader("skyblock/auctions_ended")["auctions"]
        if not isinstance(auctions, list) or len(auctions) > 5000:
            raise ValueError("Invalid ended auctions")
        for auction in auctions:
            if auction.get("bin") is not True or not positive(auction.get("price")):
                continue
            try:
                name = target_name(decode_item(auction.get("item_bytes"))["display"]["Name"])
                when = auction["timestamp"] / 1000
                sale_id = auction["auction_id"]
                if (
                    name
                    and isinstance(sale_id, str)
                    and len(sale_id) <= 64
                    and now - 86400 <= when <= now
                ):
                    rows = recent.setdefault(name, [])
                    if all(row[0] != sale_id for row in rows):
                        rows.append((sale_id, auction["price"], when))
                    recent[name] = sorted(rows, key=lambda row: row[2], reverse=True)[:20]
            except (
                ValueError,
                OSError,
                EOFError,
                zlib.error,
                KeyError,
                IndexError,
                TypeError,
                AttributeError,
            ):
                continue
        return recent
