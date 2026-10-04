"""Bounded map observations attached to the current solo PB; never stored images."""

import json
import zlib
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .run_replay import RunReplay

Tile = Annotated[int, Field(ge=0, le=35)]
MAP_LIMIT = 600 * 1024


class StrictMap(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MapRoom(StrictMap):
    tiles: list[Tile] = Field(min_length=1, max_length=4)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    type: Literal[
        "UNKNOWN", "NORMAL", "RARE", "ENTRANCE", "BLOOD", "FAIRY", "CHAMPION", "PUZZLE", "TRAP"
    ]
    state: Literal["UNKNOWN", "UNOPENED", "DISCOVERED", "CLEARED", "COMPLETE", "FAILED"]
    secrets_found: int | None = Field(default=None, ge=0, le=100)
    secrets_total: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def consistent(self):
        if len(set(self.tiles)) != len(self.tiles):
            raise ValueError("Duplicate room tile")
        connected = {self.tiles[0]}
        for _ in self.tiles:
            connected.update(t for t in self.tiles if any(adjacent(t, c) for c in connected.copy()))
        if len(connected) != len(self.tiles):
            raise ValueError("Disconnected room")
        if (
            self.secrets_found is not None
            and self.secrets_total is not None
            and self.secrets_found > self.secrets_total
        ):
            raise ValueError("Found secrets exceed room total")
        return self


def adjacent(a, b):
    return abs(a - b) == 6 or (a // 6 == b // 6 and abs(a - b) == 1)


class MapDoor(StrictMap):
    a: Tile
    b: Tile
    type: Literal["UNKNOWN", "NORMAL", "WITHER", "BLOOD", "ENTRANCE"]


class TimedMapRoom(MapRoom):
    elapsed_ms: int = Field(ge=0, le=7_200_000)
    ticks: int = Field(ge=0, le=144_000)


class RunStats(StrictMap):
    elapsed_ms: int = Field(ge=0, le=7_200_000)
    ticks: int = Field(ge=0, le=144_000)
    transit_ms: int = Field(ge=0, le=7_200_000)
    transit_ticks: int = Field(ge=0, le=144_000)
    secrets_found: int | None = Field(ge=0, le=3600)
    secrets_total: int | None = Field(ge=0, le=3600)
    crypts: int | None = Field(ge=0, le=100)


class RunMap(StrictMap):
    version: Literal[1, 2]
    rooms: list[MapRoom | TimedMapRoom] = Field(min_length=1, max_length=36)
    doors: list[MapDoor] = Field(max_length=60)
    stats: RunStats | None = None
    replay: RunReplay | None = None

    def public_data(self):
        exclude = (
            {"stats", "replay"}
            if self.version == 1
            else ({"replay"} if self.replay is None else set())
        )
        return self.model_dump(exclude=exclude)

    @model_validator(mode="after")
    def timing(self):
        timed = [room for room in self.rooms if isinstance(room, TimedMapRoom)]
        if self.version == 1:
            if timed or self.stats is not None or self.replay is not None:
                raise ValueError("Timing requires map version 2")
            return self
        if self.stats is None or len(timed) != len(self.rooms):
            raise ValueError("Version 2 requires complete room timing and run stats")
        if self.replay is not None:
            self.replay.validate_timeline(self.stats.elapsed_ms)
        for field, transit in (("elapsed_ms", "transit_ms"), ("ticks", "transit_ticks")):
            if sum(getattr(room, field) for room in timed) + getattr(
                self.stats, transit
            ) != getattr(self.stats, field):
                raise ValueError("Room and transit times must equal run time")
        if (
            self.stats.secrets_found is not None
            and self.stats.secrets_total is not None
            and self.stats.secrets_found > self.stats.secrets_total
        ):
            raise ValueError("Found secrets exceed dungeon total")
        return self

    @model_validator(mode="after")
    def consistent(self):
        owners = {}
        for index, room in enumerate(self.rooms):
            for tile in room.tiles:
                if tile in owners:
                    raise ValueError("Overlapping rooms")
                owners[tile] = index
        pairs = set()
        for door in self.doors:
            pair = (door.a, door.b)
            if door.a >= door.b or not adjacent(*pair) or pair in pairs:
                raise ValueError("Invalid door connection")
            if door.a not in owners or door.b not in owners or owners[door.a] == owners[door.b]:
                raise ValueError("Door must join distinct rooms")
            pairs.add(pair)
        if len(self.model_dump_json(exclude={"replay"}).encode()) > 16384:
            raise ValueError("Map too large")
        return self


def retain_current(db, uuid, floor, record_id=None, snapshot=None):
    """Called inside the existing record transaction, including moderator corrections."""
    best = db.execute(
        "SELECT id FROM pb_records WHERE uuid=? AND floor=? AND kind='solo_clear' "
        "AND status='eligible' ORDER BY ticks,created,id LIMIT 1",
        (uuid, floor),
    ).fetchone()
    best_id = best[0] if best else None
    db.execute(
        "DELETE FROM pb_maps WHERE uuid=? AND floor=? AND record_id IS NOT ?",
        (uuid, floor, best_id),
    )
    if snapshot is not None and record_id == best_id:
        packed = zlib.compress(json.dumps(snapshot.public_data(), separators=(",", ":")).encode())
        db.execute(
            "INSERT OR REPLACE INTO pb_maps VALUES (?,?,?,?)", (uuid, floor, record_id, packed)
        )


def public_record(records, record_id):
    with records.lock:
        row = records.db.execute(
            "SELECT p.id,p.uuid,p.floor,p.real_ms,p.ticks,p.created,n.name,m.data "
            "FROM pb_records p LEFT JOIN record_names n USING(uuid) "
            "LEFT JOIN pb_maps m ON m.record_id=p.id WHERE p.id=? AND p.kind='solo_clear' "
            "AND p.status='eligible' AND NOT EXISTS (SELECT 1 FROM sanctions s WHERE s.uuid=p.uuid "
            "AND s.kind IN ('ban','network_ban') AND s.revoked IS NULL "
            "AND (s.expires IS NULL OR s.expires>?))",
            (record_id, records.clock()),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Record unavailable")
        result = dict(row)
        packed = result.pop("data")
        snapshot = None
        if packed is not None:
            decoder = zlib.decompressobj()
            raw = decoder.decompress(packed, MAP_LIMIT + 1)
            if len(raw) > MAP_LIMIT or not decoder.eof or decoder.unused_data:
                raise HTTPException(503, "Map unavailable")
            snapshot = RunMap.model_validate(json.loads(raw)).public_data()
        return {"version": 1, "record": result, "map": snapshot}
