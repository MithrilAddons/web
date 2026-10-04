"""Bounded client observations; the server recomputes the existing projected score."""

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .run_maps import RunMap

Account = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Nonce = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ScoreEvidence(Strict):
    completed: int | None = Field(default=None, ge=0, le=100)
    cleared: int | None = Field(default=None, ge=0, le=100)
    secrets: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    crypts: int | None = Field(default=None, ge=0, le=100)
    puzzles: int | None = Field(default=None, ge=0, le=10)
    solved: int = Field(ge=0, le=10)
    deaths: int | None = Field(default=None, ge=0, le=100)
    blood_included: bool
    in_boss: bool
    mimic: bool
    prince: bool
    bat: bool

    def score(self, elapsed_ms: int, paul: bool) -> int | None:
        if (
            any(
                value is None
                for value in (
                    self.completed,
                    self.cleared,
                    self.secrets,
                    self.crypts,
                    self.puzzles,
                    self.deaths,
                )
            )
            or not self.cleared
        ):
            return None
        total = math.floor(self.completed / (self.cleared / 100.0) + 0.4)
        if total <= 0 or total < self.completed or self.solved > self.puzzles:
            return None
        effective = min(
            total, self.completed + int(not self.blood_included) + int(not self.in_boss)
        )
        ratio = effective / total
        skill = max(
            20,
            min(
                100,
                20
                + math.floor(ratio * 80)
                - (self.puzzles - self.solved) * 10
                - max(0, self.deaths * 2 - 1),
            ),
        )
        bonus = min(5, self.crypts) + 2 * self.mimic + self.prince + self.bat + 10 * paul
        over = max(0, elapsed_ms // 1000 - 840) * 100.0 / 840
        deduction = 0.0
        for cap, divisor in ((20, 2), (20, 3.5), (10, 4), (10, 5)):
            used = min(over, cap)
            deduction += used / divisor
            over -= used
        speed = max(0, int(100 - deduction - over / 6))
        return (
            int(ratio * 60)
            + skill
            + max(0, min(40, math.floor(self.secrets * 0.4)))
            + bonus
            + speed
        )


class SoloStart(Strict):
    version: Literal[2]
    floor: Literal["F7", "M7"]
    elapsed_ms: int = Field(ge=0, le=10_000)
    ticks: int = Field(ge=0, le=240)
    paul: bool


class SoloProgress(Strict):
    version: Literal[2]
    attempt_id: Nonce
    nonce: Nonce
    sequence: int = Field(ge=1, le=1500)
    elapsed_ms: int = Field(ge=0, le=7_200_000)
    ticks: int = Field(ge=0, le=144_000)
    roster: list[Account] = Field(min_length=1, max_length=5)
    dead: bool
    valid: bool
    evidence: ScoreEvidence
    complete: bool
    map: RunMap | None = None

    @model_validator(mode="after")
    def completion_map(self):
        if self.map is not None and not self.complete:
            raise ValueError("Map requires a completion report")
        if self.map is not None and self.map.stats is not None:
            stats = self.map.stats
            if (
                stats.elapsed_ms != self.elapsed_ms
                or stats.ticks != self.ticks
                or stats.crypts != self.evidence.crypts
            ):
                raise ValueError("Map stats must match the completion observation")
        return self


class TerminalReport(Strict):
    version: Literal[2]
    report_id: Account
    floor: Literal["F7", "M7"]
    run_started_ms: int = Field(ge=0)
    roster: list[Account] = Field(min_length=1, max_length=5)
    real_ms: int = Field(ge=1, le=7_200_000)
    ticks: int = Field(ge=1, le=144_000)
