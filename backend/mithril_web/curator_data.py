"""Curator's item catalog and auction sales counts, collected from Hypixel's keyless API.

Only item IDs and daily sale counts are kept; no player or auction details are stored
beyond the auction IDs needed to avoid counting a sale twice.
"""

import asyncio
import http.client
import json
import sqlite3
import threading
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path

from . import slayer_market
from .curator import catalog

PERIODS = {"sales": 60, "catalog": 6 * 3600}
SALES_DAYS = 60
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
        updated, items = response["lastUpdated"], response["items"]
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
                """INSERT INTO curator_items VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, clues=excluded.clues,
                family=excluded.family, guessable=1, candidate=excluded.candidate""",
                [
                    (
                        identifier,
                        entry["name"],
                        json.dumps(entry["clues"], sort_keys=True),
                        entry["family"],
                        int(entry["candidate"]),
                        now,
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
