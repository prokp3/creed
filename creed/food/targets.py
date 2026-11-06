"""Which targets apply to a day: training or rest, and the target set in force on that date."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

TRAINING = "training"
REST = "rest"
DAY_TYPES = (TRAINING, REST)
DEFAULT_TRAINING_MINUTES = 20

# How a day's type was decided, so the app can say so.
SET_BY_HAND = "override"
FROM_GARMIN = "garmin"
NO_WORKOUT_YET = "default"


@dataclass(frozen=True)
class DayType:
    day_type: str
    how: str


@dataclass(frozen=True)
class TargetSet:
    day_type: str
    effective_from: date
    targets: dict[str, float]


def detect(durations_seconds: Iterable[float | None], threshold_minutes: float) -> bool:
    """A training day has at least one recorded activity lasting the threshold or longer."""
    return any(seconds is not None and seconds >= threshold_minutes * 60 for seconds in durations_seconds)


def day_type(override: str | None, durations_seconds: Iterable[float | None], threshold_minutes: float) -> DayType:
    """Your choice wins. Otherwise Garmin decides, and a day with no long enough workout synced yet is a rest day."""
    if override in DAY_TYPES:
        return DayType(override, SET_BY_HAND)
    if detect(durations_seconds, threshold_minutes):
        return DayType(TRAINING, FROM_GARMIN)
    return DayType(REST, NO_WORKOUT_YET)


def targets_for(day: date, kind: str, sets: Iterable[TargetSet]) -> TargetSet | None:
    """The newest set of that type starting on or before the day. None before any were set."""
    candidates = [s for s in sets if s.day_type == kind and s.effective_from <= day]
    return max(candidates, key=lambda s: s.effective_from, default=None)


def remaining(targets: Mapping[str, float], totals: Mapping[str, float]) -> dict[str, float]:
    """Target minus eaten, per nutrient with a target. Negative means over."""
    return {key: target - totals.get(key, 0.0) for key, target in targets.items()}
