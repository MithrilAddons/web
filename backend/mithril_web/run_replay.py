"""Bounded position/facing observations; not a world recording or anti-cheat proof."""

import base64
import struct
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SAMPLE = struct.Struct("<IhhBBH")
MAX_SAMPLES = 36002


class RunReplay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    samples: str = Field(min_length=32, max_length=MAX_SAMPLES * 16)

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
                or flags > 3
                or not previous_secrets <= secrets <= 3600
            ):
                raise ValueError("Invalid replay timeline")
            validate_position(x, z, flags)
            previous_time, previous_secrets = elapsed, secrets


def validate_position(x, z, flags):
    if flags & 2:
        if x or z or not flags & 1:
            raise ValueError("Unmapped replay point must break the path")
    elif not (-3200 <= x <= -145 and -3200 <= z <= -145):
        raise ValueError("Replay position outside dungeon")
