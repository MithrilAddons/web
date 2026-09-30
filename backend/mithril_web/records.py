"""Account-wide mod bests, separate from selected-profile Hypixel records."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .record_store import RecordStore as RecordStore


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


def with_mod_records(summary, records):
    # Do not mutate the cached Hypixel summary shared with concurrent readers.
    floors = [dict(row) for row in summary["floors"]]
    for record in records:
        for row in floors:
            if row["floor"] == record["floor"]:
                row[f"{record['kind']}_ms"] = record["real_ms"]
    return {**summary, "floors": floors, "mod_records_available": bool(records)}
