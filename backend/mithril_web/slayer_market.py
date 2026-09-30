"""Shared, keyless Hypixel prices for the Slayer calculator; no player lookups.

Pricing rules adapted from the owner's MithrilAddons at 403f0dd. Only aggregate
quotes leave this service. Recent sale samples live in bounded process memory.
"""

import asyncio
import base64
import gzip
import http.client
import io
import json
import math
import re
import struct
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CATALOGUE = json.loads(Path(__file__).with_name("slayer_data.json").read_text())
DROPS = [d for s in CATALOGUE for t in s["tiers"] for d in t["drops"]]
TARGETS = sorted({d["auctionName"] for d in DROPS if not d["bazaarId"]}, key=len, reverse=True)
BAZAAR_IDS = {d["bazaarId"] for d in DROPS if d["bazaarId"]}
NPC_KEYS = BAZAAR_IDS | {d[k] for d in DROPS for k in ("name", "auctionName")}
FORMATTING = re.compile(r"§[0-9A-FK-OR]", re.I)
PET_NAME = re.compile(r"^\[Lvl (\d+)] (.+)$")
XP_100 = dict(
    zip(
        ("COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC"),
        (5624785, 8644220, 12626665, 18608500, 25353230, 25353230),
        strict=True,
    )
)
PERIODS = {"bazaar": 300, "npc": 3600, "auctions": 900, "sales": 60}
MAX_BODY = 16 * 1024 * 1024


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


def decode_item(encoded):
    """Read bounded standard NBT from the official API's gzipped item payload."""
    if not isinstance(encoded, str) or len(encoded) > 3_000_000:
        raise ValueError("Invalid item")
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(encoded, validate=True))) as zipped:
        data = zipped.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Item too large")
    stream = io.BytesIO(data)
    budget = 50000

    def read(size):
        if size < 0 or size > len(data):
            raise ValueError("Invalid NBT length")
        value = stream.read(size)
        if len(value) != size:
            raise ValueError("Truncated NBT")
        return value

    def number(fmt):
        return struct.unpack(fmt, read(struct.calcsize(fmt)))[0]

    def string():
        return read(number(">H")).decode("utf-8", errors="replace")

    def tag(kind, depth=0):
        nonlocal budget
        budget -= 1
        if depth > 32 or budget < 0:
            raise ValueError("NBT too complex")
        if kind in (1, 2, 3, 4, 5, 6):
            return number({1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}[kind])
        if kind == 8:
            return string()
        if kind in (7, 11, 12):
            read(number(">i") * {7: 1, 11: 4, 12: 8}[kind])
            return None
        if kind == 9:
            child, count = number(">B"), number(">i")
            if not 0 <= count <= budget:
                raise ValueError("NBT list too large")
            return [tag(child, depth + 1) for _ in range(count)]
        if kind == 10:
            result = {}
            while (child := number(">B")) != 0:
                name = string()
                result[name] = tag(child, depth + 1)
            return result
        raise ValueError("Invalid NBT tag")

    if number(">B") != 10:
        raise ValueError("Expected NBT compound")
    string()
    root = tag(10)
    return root["i"][0]["tag"]


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
        rarity = info.get("tier") or auction.get("tier", "")
        xp = info.get("exp")
        if rarity not in XP_100 or (xp is not None and (not positive(xp) and xp != 0)):
            return None
        return {
            "name": match[2].strip(),
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


def pet_quotes(listings):
    groups = {}
    for item in listings:
        groups.setdefault((item["name"], item["rarity"]), []).append(item)
    result = []
    for (name, rarity), group in groups.items():
        golden = name.lower() == "golden dragon"
        end_level = 200 if golden else 100
        start_level = (
            min((p["level"] for p in group if 100 <= p["level"] < 200), default=None)
            if golden
            else 1
        )
        start = sorted((p for p in group if p["level"] == start_level), key=lambda p: p["price"])[
            :3
        ]
        end = sorted((p for p in group if p["level"] == end_level), key=lambda p: p["price"])[:3]
        if not start or not end:
            continue
        xp = XP_100[rarity]
        if golden:
            experiences = [p["xp"] for p in start if p["xp"] is not None]
            if not experiences and start_level != 100:
                continue
            xp = 214023230 - (sum(experiences) / len(experiences) if experiences else 25353230)
        start_price = sum(p["price"] for p in start) / len(start)
        end_price = sum(p["price"] for p in end) / len(end)
        if xp > 0 and end_price > start_price:
            result.append(
                {
                    "name": name,
                    "rarity": rarity,
                    "startLevel": start_level,
                    "endLevel": end_level,
                    "startPrice": start_price,
                    "endPrice": end_price,
                    "requiredXp": xp,
                    "samples": len(start) + len(end),
                }
            )
    return sorted(
        result, key=lambda p: (p["endPrice"] - p["startPrice"]) / p["requiredXp"], reverse=True
    )[:100]


class SlayerMarket:
    def __init__(self, loader=fetch_json, clock=time.time):
        self.loader, self.clock = loader, clock
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.active_until = 0
        self.next = dict.fromkeys(PERIODS, 0)
        self.feeds = {name: {"status": "loading", "updated": None} for name in PERIODS}
        self.bazaar, self.npc, self.bins, self.sales = {}, {}, {}, {}
        self.pets = []

    def get(self):
        with self.lock:
            now = self.clock()
            self.active_until = now + 900
            feeds = {name: dict(feed) for name, feed in self.feeds.items()}
            for name, feed in feeds.items():
                if feed["updated"] is not None and now - feed["updated"] > PERIODS[name]:
                    feed["status"] = "stale"
                if feed["updated"] is not None and now - feed["updated"] > 86400:
                    feed["status"] = "unavailable"

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

    async def run(self):
        try:
            while True:
                if self.clock() < self.active_until:
                    await asyncio.to_thread(self.refresh)
                await asyncio.sleep(1)
        finally:
            self.stopped.set()

    def refresh(self):
        for name in PERIODS:
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
        pages, generation = first["totalPages"], first["lastUpdated"]
        if not isinstance(pages, int) or not 1 <= pages <= 200:
            raise ValueError("Invalid auction page count")
        bins, pets = {}, []
        started = time.monotonic()

        def consume(page, expected):
            if (
                page["page"] != expected
                or page["totalPages"] != pages
                or page["lastUpdated"] != generation
            ):
                raise ValueError("Auction snapshot changed; retry later")
            auctions = page["auctions"]
            if not isinstance(auctions, list) or len(auctions) > 1000:
                raise ValueError("Invalid auction page")
            for auction in auctions:
                price = auction.get("starting_bid")
                if auction.get("bin") is not True or not positive(price):
                    continue
                name = target_name(auction.get("item_name"))
                if name:
                    bins[name] = sorted([*bins.get(name, []), price])[:3]
                pet = pet_listing(auction)
                if pet:
                    pets.append(pet)

        consume(first, 0)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for batch in range(1, pages, 4):
                if self.stopped.is_set() or time.monotonic() - started > 90:
                    raise ValueError("Auction scan interrupted")
                numbers = list(range(batch, min(batch + 4, pages)))
                futures = [pool.submit(self.loader, f"skyblock/auctions?page={n}") for n in numbers]
                for n, future in zip(numbers, futures, strict=True):
                    consume(future.result(), n)
        return bins, pet_quotes(pets)

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
