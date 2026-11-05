"""Daily strain per discipline.

Run, bike and other HR-tracked activities use Banister's TRIMP, from heart-rate reserve:
    TRIMP = minutes x x * k * e^(b * x), where x = (HR - resting) / (max - resting)
    Men: k = 0.64, b = 1.92. Women: k = 0.86, b = 1.67.
    Banister EW (1991), "Modeling elite athletic performance", in Physiological Testing of the
    High-Performance Athlete.

Swims don't use wrist HR, which is unreliable in water. They use duration and pace:
    load = (speed / threshold speed)^3 x hours x 100
    This is the swim TSS formula published by TrainingPeaks. Threshold speed is estimated from
    your own best sustained swim. It isn't peer reviewed, and its units only roughly line up
    with TRIMP, which the UI says.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from creed.metrics import hr_params
from creed.metrics.base import COMPUTED, INSUFFICIENT, OK, ActivityRecord, MetricContext, MetricResult, Why
from creed.metrics.hr_params import HrParams

CURVES = {"male": (0.64, 1.92), "female": (0.86, 1.67)}
MIN_SWIM_FOR_THRESHOLD_M = 400
FEW_SWIMS = 5
HOME_RING_REFERENCE_DAYS = 90

WHY = Why(
    formula="Run and bike: Banister TRIMP from heart-rate reserve. Swim: (speed / threshold speed)^3 x hours x 100, "
            "with no wrist HR.",
    inputs="Seconds at each heart rate from the FIT file, or average HR if that's missing. Swim duration and distance.",
    window="One day, split by discipline.",
    citation="Banister 1991 (TRIMP). TrainingPeaks swim TSS formula, which isn't peer reviewed.",
    note="Swim units only roughly line up with TRIMP. Whoop's strain algorithm is proprietary and isn't replicated.",
)


def trimp_weight(x: float, curve: str = "male") -> float:
    k, b = CURVES[curve]
    return k * math.exp(b * x)


def reserve_fraction(hr: float, resting: float, maximum: float) -> float:
    return max(0.0, min(1.0, (hr - resting) / (maximum - resting)))


def trimp_from_average(minutes: float, hr: float, resting: float, maximum: float, curve: str = "male") -> float:
    x = reserve_fraction(hr, resting, maximum)
    return minutes * x * trimp_weight(x, curve)


def trimp_from_histogram(seconds_at: dict[int, float], resting: float, maximum: float, curve: str = "male") -> float:
    return sum(trimp_from_average(seconds / 60, hr, resting, maximum, curve) for hr, seconds in seconds_at.items())


def swim_load(duration_seconds: float, distance_m: float, threshold_speed: float) -> float:
    speed = distance_m / duration_seconds
    return (speed / threshold_speed) ** 3 * (duration_seconds / 3600) * 100


def swim_threshold_speed(activities: list[ActivityRecord]) -> float | None:
    """The fastest average speed on a swim long enough to be sustained."""
    speeds = [
        a.distance_m / a.duration_seconds
        for a in activities
        if a.discipline == "swim" and not a.flagged and a.duration_seconds and a.distance_m
        and a.distance_m >= MIN_SWIM_FOR_THRESHOLD_M
    ]
    return max(speeds) if speeds else None


def activity_load(a: ActivityRecord, params: HrParams, threshold: float | None, curve: str) -> tuple[float | None, str]:
    """An activity's load and the method used. None means it can't be worked out, and it stays out."""
    if a.discipline == "swim":
        if threshold and a.duration_seconds and a.distance_m:
            return swim_load(a.duration_seconds, a.distance_m, threshold), "swim"
        return None, "none"
    if params.max_hr is None or params.resting_hr is None or params.max_hr <= params.resting_hr:
        return None, "none"
    if a.hr_seconds:
        return trimp_from_histogram(a.hr_seconds, params.resting_hr, params.max_hr, curve), "samples"
    if a.avg_hr and a.duration_seconds:
        return trimp_from_average(a.duration_seconds / 60, a.avg_hr, params.resting_hr, params.max_hr, curve), "average"
    return None, "none"


def counted(activities: list[ActivityRecord]) -> list[ActivityRecord]:
    """A multisport parent's legs are counted on their own, so the parent isn't counted as well."""
    return [a for a in activities if not a.is_parent and not a.flagged]


def daily_loads(ctx: MetricContext) -> dict[date, dict[str, float]]:
    """Load per day per discipline. A day with no activities is absent, and callers treat it as zero load."""
    params = hr_params.estimate(ctx)
    threshold = swim_threshold_speed(ctx.activities)
    days: dict[date, dict[str, float]] = defaultdict(dict)
    for a in counted(ctx.activities):
        load, _ = activity_load(a, params, threshold, ctx.settings.trimp_curve)
        if load is not None:
            days[a.day][a.discipline] = days[a.day].get(a.discipline, 0.0) + load
    return dict(days)


def compute(ctx: MetricContext) -> MetricResult:
    params = hr_params.estimate(ctx)
    base = {"key": "strain", "title": "Strain", "tag": COMPUTED, "unit": "load", "why": WHY}
    details = {"max_hr": params.max_hr, "max_hr_source": params.max_source,
               "resting_hr": params.resting_hr, "resting_hr_source": params.resting_source}
    if params.max_hr is None or params.resting_hr is None:
        reason = params.max_source if params.max_hr is None else params.resting_source
        return MetricResult(**base, state=INSUFFICIENT, value=None, confidence="none", reason=reason, details=details)

    threshold = swim_threshold_speed(ctx.activities)
    today = [a for a in counted(ctx.activities) if a.day == ctx.today]
    by_discipline: dict[str, float] = {}
    methods = set()
    skipped = 0
    for a in today:
        load, method = activity_load(a, params, threshold, ctx.settings.trimp_curve)
        if load is None:
            skipped += 1
            continue
        by_discipline[a.discipline] = by_discipline.get(a.discipline, 0.0) + load
        methods.add(method)

    swims = sum(1 for a in ctx.activities if a.discipline == "swim" and not a.flagged)
    if skipped or "swim" in methods and swims < FEW_SWIMS:
        confidence = "low"
    elif "average" in methods or "swim" in methods:
        confidence = "medium"
    else:
        confidence = "high"

    loads = daily_loads(ctx)
    recent = sorted(sum(d.values()) for day, d in loads.items()
                    if 0 < (ctx.today - day).days <= HOME_RING_REFERENCE_DAYS)
    return MetricResult(
        **base, state=OK, value=sum(by_discipline.values()), confidence=confidence,
        details={**details, "by_discipline": by_discipline, "activities": len(today), "skipped": skipped,
                 "swim_threshold_speed_mps": threshold,
                 # The home ring is relative to your own hardest recent day, not a fixed scale.
                 "ring_reference": recent[-1] if recent else None},
    )
