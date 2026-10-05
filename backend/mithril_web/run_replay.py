"""Bounded position/facing observations; not a world recording or anti-cheat proof."""

import base64
import struct
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SAMPLE = struct.Struct("<IhhBBH")
MAX_SAMPLES = 36002
ROOM_SECRET = struct.Struct("<IBB")


class RunReplay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    samples: str = Field(min_length=32, max_length=MAX_SAMPLES * 16)
    room_secrets: str | None = Field(
        default=None, max_length=3600 * 8, exclude_if=lambda v: v is None
    )

    def validate_rooms(self, rooms, duration):
        if self.room_secrets is None:
            return
        raw = base64.b64decode(self.room_secrets, validate=True)
        if len(raw) % ROOM_SECRET.size:
            raise ValueError("Invalid room secret event size")
        owners = {room.tiles[0]: room for room in rooms}
        counts = {}
        previous_time = 0
        for elapsed, tile, found in ROOM_SECRET.iter_unpack(raw):
            room = owners.get(tile)
            if (
                room is None
                or not previous_time <= elapsed <= duration
                or not counts.get(tile, 0) < found <= 100
                or (room.secrets_total is not None and found > room.secrets_total)
                or (room.secrets_found is not None and found > room.secrets_found)
            ):
                raise ValueError("Invalid room secret timeline")
            previous_time = elapsed
            counts[tile] = found

    def validate_timeline(self, duration):
        raw = base64.b64decode(self.samples, validate=True)
        if len(raw) % SAMPLE.size or not 2 <= len(raw) // SAMPLE.size <= MAX_SAMPLES:
            raise ValueError("Invalid replay sample count")
        previous_time, previous_secrets = -1, 0
        count = len(raw) // SAMPLE.size
        for index, (elapsed, x, z, _, flags, secrets) in enumerate(SAMPLE.iter_unpack(raw)):
            if (
                elapsed > duration
                or elapsed <= previous_time
                or (index == 0 and (elapsed != 0 or not flags & 1))
                or (0 < index < count - 1 and elapsed - previous_time < 200)
                or (index == count - 1 and elapsed != duration)
                or not previous_secrets <= secrets <= 3600
            ):
                raise ValueError("Invalid replay timeline")
            validate_flags(flags, index)
            validate_position(x, z, flags)
            previous_time, previous_secrets = elapsed, secrets


def validate_flags(flags, index):
    kind = (flags >> 2) & 7
    if (
        (flags & 0x80 and index != 0)
        or kind > 4
        or (kind and (index == 0 or not flags & 1 or flags & 2))
        or (not kind and flags & 0x60)
    ):
        raise ValueError("Invalid replay teleport flags")


def validate_position(x, z, flags):
    if flags & 2:
        if x or z or not flags & 1:
            raise ValueError("Unmapped replay point must break the path")
    elif not (-3200 <= x <= -145 and -3200 <= z <= -145):
        raise ValueError("Replay position outside dungeon")
