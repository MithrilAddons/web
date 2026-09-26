"""Account-wide mod bests, separate from selected-profile Hypixel records."""

import sqlite3
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Timing(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    floor: Literal["F7", "M7"]
    kind: Literal["solo_clear", "terminals"]
    real_ms: int = Field(gt=0, le=7_200_000)
    ticks: int = Field(gt=0, le=144_000)


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    records: list[Timing] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_records(self):
        if len({(r.floor, r.kind) for r in self.records}) != len(self.records):
            raise ValueError("Duplicate record")
        return self


class RecordStore:
    """One lock owns this connection. Writes merge minimums in one transaction."""

    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS mod_bests (
            uuid TEXT NOT NULL, floor TEXT NOT NULL, kind TEXT NOT NULL,
            real_ms INTEGER NOT NULL, ticks INTEGER NOT NULL,
            PRIMARY KEY(uuid, floor, kind))""")
        self.db.commit()

    def merge(self, uuid, records):
        with self.lock, self.db:
            self.db.executemany(
                "INSERT INTO mod_bests VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(uuid, floor, kind) DO UPDATE SET "
                "real_ms=MIN(real_ms, excluded.real_ms), ticks=MIN(ticks, excluded.ticks)",
                [(uuid, r.floor, r.kind, r.real_ms, r.ticks) for r in records],
            )

    def read(self, uuid):
        with self.lock:
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT floor, kind, real_ms, ticks FROM mod_bests WHERE uuid=?", (uuid,)
                )
            ]

    def close(self):
        self.db.close()


def with_mod_records(summary, records):
    # Do not mutate the cached Hypixel summary shared with concurrent readers.
    floors = [dict(row) for row in summary["floors"]]
    for record in records:
        for row in floors:
            if row["floor"] == record["floor"]:
                row[f"{record['kind']}_ms"] = record["real_ms"]
    return {**summary, "floors": floors, "mod_records_available": bool(records)}
