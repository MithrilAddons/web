"""Curator's item catalog and auction sales counts, collected from Hypixel's keyless API.

Only item IDs and daily sale counts are kept; no player or auction details are stored
beyond the auction IDs needed to avoid counting a sale twice.
"""

import asyncio
import http.client
import json
import random
import sqlite3
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from . import slayer_market
from .curator import catalog

PERIODS = {"sales": 60, "catalog": 6 * 3600, "lock": 60}
SALES_DAYS = 60
QUEUE_DAYS = 30
DEFAULT_CUTOFF = 100
# Bumped when stored catalog columns change, so the next refresh rewrites every item.
CATALOG_VERSION = 3
POOL = ("eligible", "allowed")
FAILURES = (
    OSError,
    sqlite3.Error,
    zlib.error,
    ValueError,
    http.client.HTTPException,
    KeyError,
    TypeError,
    AttributeError,
)


def day(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).date().isoformat()


def sold_item(auction):
    """The SkyBlock item ID of one ended auction, or None when it can't be read."""
    try:
        identifier = slayer_market.decode_item(auction.get("item_bytes"))["ExtraAttributes"]["id"]
    except (ValueError, OSError, EOFError, zlib.error, KeyError, IndexError, TypeError):
        return None
    return identifier if isinstance(identifier, str) and 0 < len(identifier) <= 128 else None


class CuratorData:
    """One lock owns SQLite; network calls never hold it."""

    def __init__(self, path: Path, loader=None, clock=time.time):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.loader = loader or (lambda request: slayer_market.fetch_json(request))
        self.clock = clock
        self.lock = threading.Lock()
        self.next = dict.fromkeys(PERIODS, 0)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS curator_items (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, clues TEXT NOT NULL, family TEXT,
            guessable INTEGER NOT NULL, candidate INTEGER NOT NULL, first_seen REAL NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS curator_sales (
            item TEXT NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL,
            PRIMARY KEY (item, day))""")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS curator_seen (auction TEXT PRIMARY KEY, at REAL NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS curator_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(curator_items)")}
        for column in ("cosmetic", "unique_clues", "admin"):
            if column not in columns:
                self.db.execute(
                    f"ALTER TABLE curator_items ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                )
        if "icon" not in columns:
            self.db.execute("ALTER TABLE curator_items ADD COLUMN icon TEXT NOT NULL DEFAULT '{}'")
        self.db.execute("""CREATE TABLE IF NOT EXISTS curator_prices (
            day TEXT NOT NULL, item TEXT NOT NULL, price REAL NOT NULL,
            PRIMARY KEY (day, item))""")
        # The answer and its clues are frozen when the day starts.
        self.db.execute("""CREATE TABLE IF NOT EXISTS curator_locks (
            day TEXT PRIMARY KEY, item TEXT NOT NULL, values_json TEXT NOT NULL,
            at REAL NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS curator_lists (
            item TEXT PRIMARY KEY, list TEXT NOT NULL, actor TEXT NOT NULL, at REAL NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS curator_days (
            day TEXT PRIMARY KEY, item TEXT NOT NULL, actor TEXT, at REAL NOT NULL)""")
        self.db.commit()

    def close(self):
        # A refresh thread may still be running; it must never use a closing connection.
        with self.lock:
            self.db.close()

    async def run(self):
        while True:
            await asyncio.to_thread(self.refresh)
            await asyncio.sleep(1)

    def refresh(self):
        for name in PERIODS:
            if self.clock() < self.next[name]:
                continue
            try:
                getattr(self, "load_" + name)()
                self.next[name] = self.clock() + PERIODS[name]
            except FAILURES:
                self.next[name] = self.clock() + 60

    def load_catalog(self):
        response = self.loader("resources/skyblock/items")
        updated = f"{CATALOG_VERSION}:{response['lastUpdated']}"
        items = response["items"]
        if not isinstance(items, list) or not 1000 <= len(items) <= 50000:
            raise ValueError("Invalid items list")
        with self.lock:
            row = self.db.execute(
                "SELECT value FROM curator_meta WHERE key='catalog_updated'"
            ).fetchone()
        if row and row["value"] == str(updated):
            return
        entries = catalog(items)
        now = self.clock()
        with self.lock, self.db:
            # Items Hypixel removes stay known, but can no longer be guessed or picked.
            self.db.execute("UPDATE curator_items SET guessable=0, candidate=0")
            self.db.executemany(
                """INSERT INTO curator_items
                (id, name, clues, family, guessable, candidate, first_seen, cosmetic,
                unique_clues, admin, icon) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, clues=excluded.clues,
                family=excluded.family, guessable=1, candidate=excluded.candidate,
                cosmetic=excluded.cosmetic, unique_clues=excluded.unique_clues,
                admin=excluded.admin, icon=excluded.icon""",
                [
                    (
                        identifier,
                        entry["name"],
                        json.dumps(entry["clues"], sort_keys=True),
                        entry["family"],
                        int(entry["candidate"]),
                        now,
                        int(entry["cosmetic"]),
                        int(entry["unique"]),
                        int(entry["admin"]),
                        json.dumps(entry["icon"], sort_keys=True),
                    )
                    for identifier, entry in entries.items()
                ],
            )
            self.db.execute(
                "INSERT OR REPLACE INTO curator_meta VALUES ('catalog_updated', ?)", (str(updated),)
            )

    def load_sales(self):
        auctions = self.loader("skyblock/auctions_ended")["auctions"]
        if not isinstance(auctions, list) or len(auctions) > 5000:
            raise ValueError("Invalid ended auctions")
        now = self.clock()
        sales = []
        for auction in auctions:
            sale, ended = auction.get("auction_id"), auction.get("timestamp")
            if not isinstance(sale, str) or not 0 < len(sale) <= 64:
                continue
            if not isinstance(ended, int) or not now - 86400 <= ended / 1000 <= now + 300:
                continue
            item = sold_item(auction)
            if item:
                sales.append((sale, item, day(ended / 1000)))
        with self.lock, self.db:
            for sale, item, sold in sales:
                if self.db.execute(
                    "INSERT OR IGNORE INTO curator_seen VALUES (?, ?)", (sale, now)
                ).rowcount:
                    self.db.execute(
                        """INSERT INTO curator_sales VALUES (?, ?, 1)
                        ON CONFLICT(item, day) DO UPDATE SET count=count+1""",
                        (item, sold),
                    )
            self.db.execute("DELETE FROM curator_seen WHERE at<?", (now - 2 * 86400,))
            self.db.execute(
                "DELETE FROM curator_sales WHERE day<?", (day(now - SALES_DAYS * 86400),)
            )

    def sales(self, days=30):
        """Auction sales per item over the last `days` UTC days, today included."""
        with self.lock:
            rows = self.db.execute(
                "SELECT item, SUM(count) AS total FROM curator_sales WHERE day>? GROUP BY item",
                (day(self.clock() - days * 86400),),
            ).fetchall()
        return {row["item"]: row["total"] for row in rows}

    def items(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM curator_items WHERE guessable=1").fetchall()
        return {
            row["id"]: {
                "name": row["name"],
                "clues": json.loads(row["clues"]),
                "family": row["family"],
                "candidate": bool(row["candidate"]),
            }
            for row in rows
        }

    def _meta(self, key, default):
        row = self.db.execute("SELECT value FROM curator_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def _rows(self):
        """Every guessable item with its curation status; the caller holds the lock."""
        sales = {
            row["item"]: row["total"]
            for row in self.db.execute(
                "SELECT item, SUM(count) AS total FROM curator_sales WHERE day>? GROUP BY item",
                (day(self.clock() - 30 * 86400),),
            )
        }
        lists = dict(self.db.execute("SELECT item, list FROM curator_lists").fetchall())
        cutoff = int(self._meta("sales_cutoff", DEFAULT_CUTOFF))
        reviewed = float(self._meta("reviewed_at", 0))
        rows = []
        for row in self.db.execute("SELECT * FROM curator_items WHERE guessable=1 ORDER BY name"):
            listed, count = lists.get(row["id"]), sales.get(row["id"], 0)
            if listed == "block":
                status = "blocked"
            elif not row["unique_clues"]:
                # Not even the allowlist helps: players couldn't tell it apart.
                status = "not_unique"
            elif listed == "allow":
                status = "allowed"
            elif row["cosmetic"]:
                status = "cosmetic"
            else:
                status = "popular" if count > cutoff else "eligible"
            clues = json.loads(row["clues"])
            rows.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "rarity": clues["rarity"],
                    "museum": clues["museum"],
                    "sales": count,
                    "list": listed,
                    "status": status,
                    "admin": bool(row["admin"]),
                    "family": row["family"],
                    "new": row["first_seen"] > reviewed,
                }
            )
        return rows

    def _pick(self, rows, avoid, rng):
        pool = [row for row in rows if row["status"] in POOL and row["id"] not in avoid]
        if not pool:
            return None
        # Rarely traded items are the point; heavily traded ones are still possible.
        return rng.choices(pool, [1 / (1 + row["sales"]) for row in pool])[0]["id"]

    def queue(self, rng=None):
        """Answers for today and the next 29 days; missing days are picked now."""
        rng = rng or random.SystemRandom()
        now = self.clock()
        days = [day(now + n * 86400) for n in range(QUEUE_DAYS)]
        with self.lock, self.db:
            planned = dict(
                self.db.execute(
                    "SELECT day, item FROM curator_days WHERE day>=?", (days[0],)
                ).fetchall()
            )
            used = {row[0] for row in self.db.execute("SELECT item FROM curator_days")}
            rows = self._rows()
            for date in days:
                if date not in planned:
                    # Once every item has had its day, repeats start, but never within the queue.
                    item = self._pick(rows, used, rng) or self._pick(
                        rows, set(planned.values()), rng
                    )
                    if item:
                        self.db.execute(
                            "INSERT INTO curator_days VALUES (?, ?, NULL, ?)", (date, item, now)
                        )
                        planned[date] = item
                        used.add(item)
            known = {row["id"]: row for row in rows}
            return [
                {
                    "day": date,
                    "item": planned.get(date),
                    "name": known.get(planned.get(date), {}).get("name"),
                    "sales": known.get(planned.get(date), {}).get("sales"),
                    "locked": date == days[0],
                }
                for date in days
            ]

    def _changeable(self, date):
        now = self.clock()
        if not day(now) < date <= day(now + (QUEUE_DAYS - 1) * 86400):
            raise ValueError("Only the coming days in the queue can change")

    def reroll(self, date, actor, rng=None):
        rng = rng or random.SystemRandom()
        self._changeable(date)
        with self.lock, self.db:
            used = {row[0] for row in self.db.execute("SELECT item FROM curator_days")}
            item = self._pick(self._rows(), used, rng)
            if not item:
                raise LookupError("No other item is available")
            self.db.execute(
                "INSERT OR REPLACE INTO curator_days VALUES (?, ?, ?, ?)",
                (date, item, actor, self.clock()),
            )

    def schedule(self, date, item, actor):
        self._changeable(date)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT unique_clues FROM curator_items WHERE id=? AND guessable=1", (item,)
            ).fetchone()
            if not row:
                raise LookupError("Unknown item")
            if not row["unique_clues"]:
                raise ValueError("Players couldn't tell this item apart from another")
            self.db.execute(
                "INSERT OR REPLACE INTO curator_days VALUES (?, ?, ?, ?)",
                (date, item, actor, self.clock()),
            )

    def set_list(self, item, listed, actor):
        with self.lock, self.db:
            if not self.db.execute("SELECT 1 FROM curator_items WHERE id=?", (item,)).fetchone():
                raise LookupError("Unknown item")
            if listed is None:
                self.db.execute("DELETE FROM curator_lists WHERE item=?", (item,))
            else:
                self.db.execute(
                    "INSERT OR REPLACE INTO curator_lists VALUES (?, ?, ?, ?)",
                    (item, listed, actor, self.clock()),
                )

    def set_cutoff(self, cutoff):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO curator_meta VALUES ('sales_cutoff', ?)", (cutoff,)
            )

    def mark_reviewed(self):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO curator_meta VALUES ('reviewed_at', ?)", (self.clock(),)
            )

    def overview(self):
        queue = self.queue()
        with self.lock:
            rows = self._rows()
            since = self.db.execute("SELECT MIN(day) FROM curator_sales").fetchone()[0]
            cutoff = int(self._meta("sales_cutoff", DEFAULT_CUTOFF))
        counts = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "version": 1,
            "sales_cutoff": cutoff,
            "sales_since": since,
            "counts": counts,
            "new": sum(row["new"] for row in rows),
            "queue": queue,
        }

    def review(self, group, query="", offset=0, limit=50):
        with self.lock:
            rows = self._rows()
        groups = {
            "pool": lambda row: row["status"] in POOL,
            "admin": lambda row: row["admin"],
            "new": lambda row: row["new"],
            "allowed": lambda row: row["list"] == "allow",
            "blocked": lambda row: row["list"] == "block",
            "all": lambda row: True,
        }
        needle = query.strip().casefold()
        rows = [
            row
            for row in rows
            if groups[group](row)
            and (needle in row["name"].casefold() or needle in row["id"].casefold())
        ]
        return {"version": 1, "total": len(rows), "items": rows[offset : offset + limit]}

    def load_lock(self):
        """At the start of each UTC day: take the market snapshot and freeze the answer."""
        today = day(self.clock())
        with self.lock:
            if self.db.execute("SELECT 1 FROM curator_locks WHERE day=?", (today,)).fetchone():
                return
        answer = self.queue()[0]["item"]
        if not answer:
            raise ValueError("No item is available for today")
        prices = market_prices(self.loader)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT clues FROM curator_items WHERE id=?", (answer,)
            ).fetchone()
            values = {**json.loads(row["clues"]), "market": prices.get(answer)}
            self.db.execute("DELETE FROM curator_prices WHERE day<?", (today,))
            self.db.executemany(
                "INSERT OR REPLACE INTO curator_prices VALUES (?, ?, ?)",
                [(today, item, price) for item, price in prices.items()],
            )
            self.db.execute(
                "INSERT INTO curator_locks VALUES (?, ?, ?, ?)",
                (today, answer, json.dumps(values, sort_keys=True), self.clock()),
            )

    def locked(self, date):
        """The frozen answer of one day, or None while it is still being prepared."""
        with self.lock:
            row = self.db.execute(
                "SELECT l.item, l.values_json, i.name, i.family, i.icon FROM curator_locks l "
                "JOIN curator_items i ON i.id=l.item WHERE l.day=?",
                (date,),
            ).fetchone()
            first = self.db.execute("SELECT MIN(day) FROM curator_locks").fetchone()[0]
        if not row:
            return None
        return {
            "item": row["item"],
            "name": row["name"],
            "family": row["family"],
            "values": json.loads(row["values_json"]),
            "icon": json.loads(row["icon"]),
            "number": (date_of(date) - date_of(first)).days + 1,
        }

    def guessable(self, item, date):
        """One guessable item with its clues and that day's market value."""
        with self.lock:
            row = self.db.execute(
                "SELECT name, clues, family FROM curator_items WHERE id=? AND guessable=1",
                (item,),
            ).fetchone()
            if not row:
                return None
            price = self.db.execute(
                "SELECT price FROM curator_prices WHERE day=? AND item=?", (date, item)
            ).fetchone()
        return {
            "item": item,
            "name": row["name"],
            "family": row["family"],
            "values": {**json.loads(row["clues"]), "market": price[0] if price else None},
        }

    def guess_list(self):
        """Every guessable name once, for autocomplete, with the catalog version."""
        with self.lock:
            version = self._meta("catalog_updated", "")
            rows = self.db.execute(
                "SELECT id, name FROM curator_items WHERE guessable=1 ORDER BY id"
            ).fetchall()
        names = {}
        for row in rows:
            names.setdefault(row["name"], row["id"])
        return version, sorted(([item, name] for name, item in names.items()), key=lambda r: r[1])


def date_of(text):
    return datetime.fromisoformat(text).date()


def market_prices(loader):
    """Lowest BIN per item ID across the Auction House, overridden by Bazaar buy prices."""
    first = loader("skyblock/auctions?page=0")
    pages = first["totalPages"]
    if not isinstance(pages, int) or not 1 <= pages <= 200:
        raise ValueError("Invalid auction page count")
    prices = {}

    def collect(page, number):
        if page["page"] != number or page["lastUpdated"] != first["lastUpdated"]:
            raise ValueError("Auction snapshot changed; retry later")
        auctions = page["auctions"]
        if not isinstance(auctions, list) or len(auctions) > 1000:
            raise ValueError("Invalid auction page")
        for auction in auctions:
            price = auction.get("starting_bid")
            if auction.get("bin") is not True or not slayer_market.positive(price):
                continue
            try:
                tag, count = slayer_market.decode_item(auction.get("item_bytes"), with_count=True)
                item = tag["ExtraAttributes"]["id"]
            except (ValueError, OSError, EOFError, zlib.error, KeyError, IndexError, TypeError):
                continue
            if isinstance(item, str) and isinstance(count, int) and 1 <= count <= 64:
                prices[item] = min(prices.get(item, price / count), price / count)

    collect(first, 0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        numbers = range(1, pages)
        for number, page in zip(
            numbers,
            pool.map(lambda n: loader(f"skyblock/auctions?page={n}"), numbers),
            strict=True,
        ):
            collect(page, number)
    for item, product in loader("skyblock/bazaar")["products"].items():
        price = (product.get("quick_status") or {}).get("buyPrice")
        if isinstance(item, str) and slayer_market.positive(price):
            prices[item] = price
    return prices
