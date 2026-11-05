"""What every metric takes in and gives back. Pure data: no database or web code in this package.

Adding a metric means one module with a compute(ctx) function, one line in ALL in
__init__.py, and one UI card.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

OK = "ok"
INSUFFICIENT = "insufficient"

COMPUTED = "Computed"
GARMIN = "Garmin"


@dataclass(frozen=True)
class Why:
    """The contents of the "Why this number" panel."""

    formula: str
    inputs: str
    window: str
    citation: str
    note: str = ""


@dataclass
class MetricResult:
    key: str
    title: str
    tag: str
    state: str  # OK or INSUFFICIENT. An insufficient metric has no value, and never a guess.
    value: float | str | None
    unit: str
    confidence: str  # high, medium, low or none
    why: Why
    reason: str = ""  # Why there isn't enough data, in plain words.
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SleepRecord:
    day: date
    seconds: int
    start_local_minutes: int | None = None  # Minutes after local midnight.
    end_local_minutes: int | None = None
    deep_seconds: int | None = None
    light_seconds: int | None = None
    rem_seconds: int | None = None
    respiration: float | None = None
    score: int | None = None
    flagged: bool = False


@dataclass(frozen=True)
class ActivityRecord:
    activity_id: int
    day: date
    discipline: str
    type_key: str | None = None
    duration_seconds: float | None = None
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    is_parent: bool = False
    flagged: bool = False
    hr_seconds: dict[int, float] | None = None  # Seconds spent at each heart rate, from the FIT file.
    steady: bool = False
    efficiency: float | None = None  # Metres per minute per heartbeat.
    decoupling_pct: float | None = None
    steady_speed_mps: float | None = None
    steady_hr: float | None = None


@dataclass(frozen=True)
class Settings:
    race_date: date = date(2027, 11, 1)
    timezone: str = "Asia/Kolkata"
    max_hr: float | None = None  # Overrides the estimate when set.
    resting_hr: float | None = None  # Overrides the estimate when set.
    trimp_curve: str = "male"  # Banister's weighting differs by sex: "male" or "female".


@dataclass
class MetricContext:
    today: date
    now: datetime  # Timezone-aware.
    settings: Settings = field(default_factory=Settings)
    hrv: dict[date, float] = field(default_factory=dict)
    resting_hr: dict[date, float] = field(default_factory=dict)
    sleep: list[SleepRecord] = field(default_factory=list)
    activities: list[ActivityRecord] = field(default_factory=list)
