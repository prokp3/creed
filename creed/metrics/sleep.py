"""Sleep: last night against an individual need, sleep debt and bedtime consistency.

Need is the median of your longest third of nights over the last 90 days, a stand-in for how much
you sleep when nothing cuts it short. That's a heuristic rather than a published method, and the UI
says so. Debt and variability follow established research:
    Van Dongen HPA et al. (2003), "The cumulative cost of additional wakefulness". Sleep 26:117-126.
    Bei B et al. (2016), "Beyond the mean". Sleep Med Rev 28:108-124.

Only recorded nights count. A night with no record is unknown, not zero. Records flagged as partial
are left out of everything except the night they describe.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from creed.metrics.base import COMPUTED, INSUFFICIENT, OK, MetricContext, MetricResult, SleepRecord, Why

NEED_WINDOW_DAYS = 90
MIN_NIGHTS_FOR_NEED = 14
DEBT_WINDOW_DAYS = 7
SPREAD_NIGHTS = 14
MIN_NIGHTS_FOR_SPREAD = 5
MINUTES_PER_DAY = 1440

WHY = Why(
    formula="Last night's sleep divided by your need. Need is the median of your longest third of nights. Debt adds "
            "up the shortfall on recorded nights.",
    inputs="Garmin's sleep records. Wrist-based stages are approximate.",
    window="Need: 90 days. Debt: 7 days. Bedtime spread: your last 14 recorded nights.",
    citation="Van Dongen et al. 2003 (cumulative debt). Bei et al. 2016 (variability). The need estimate is a "
             "heuristic, not a published method.",
    note="Nights with no record are unknown, so they don't add to debt. Partial records are left out.",
)


def sleep_need_seconds(nights: list[SleepRecord]) -> float | None:
    durations = sorted(n.seconds for n in nights if not n.flagged)
    if len(durations) < MIN_NIGHTS_FOR_NEED:
        return None
    return statistics.median(durations[-max(1, len(durations) // 3):])


def sleep_debt_seconds(nights: list[SleepRecord], need: float) -> float:
    return sum(max(0.0, need - n.seconds) for n in nights if not n.flagged)


def clock_spread_minutes(minutes_after_midnight: list[int]) -> float | None:
    """Standard deviation of a clock time. Measured from noon, so 23:50 and 00:10 count as close."""
    if len(minutes_after_midnight) < MIN_NIGHTS_FOR_SPREAD:
        return None
    return statistics.stdev((m - 720) % MINUTES_PER_DAY for m in minutes_after_midnight)


def compute(ctx: MetricContext) -> MetricResult:
    base = {"key": "sleep", "title": "Sleep", "tag": COMPUTED, "unit": "seconds", "why": WHY}
    recorded = sorted((n for n in ctx.sleep if n.day <= ctx.today), key=lambda n: n.day)
    recent = [n for n in recorded if (ctx.today - n.day).days < NEED_WINDOW_DAYS]
    need = sleep_need_seconds(recent)
    last_night = next((n for n in recorded if n.day == ctx.today), None)

    usable = sum(1 for n in recent if not n.flagged)
    counts = {"nights_recorded": usable, "nights_needed": MIN_NIGHTS_FOR_NEED}
    if last_night is None:
        return MetricResult(**base, state=INSUFFICIENT, value=None, confidence="none",
                            reason="No record for last night.", details=counts)
    if need is None:
        return MetricResult(**base, state=INSUFFICIENT, value=None, confidence="none",
                            reason=f"Needs {MIN_NIGHTS_FOR_NEED} recorded nights in {NEED_WINDOW_DAYS} days to "
                                   f"estimate your need. You have {usable}.", details=counts)

    window = [n for n in recorded if (ctx.today - n.day).days < DEBT_WINDOW_DAYS]
    last_spread = [n for n in recorded[-SPREAD_NIGHTS:] if n.start_local_minutes is not None and not n.flagged]
    if last_night.flagged:
        confidence = "low"
    elif usable >= 28:
        confidence = "high"
    else:
        confidence = "medium"
    return MetricResult(
        **base, state=OK, value=last_night.seconds, confidence=confidence,
        details={
            **counts,
            "need_seconds": need,
            "performance": last_night.seconds / need,
            "debt_seconds": sleep_debt_seconds(window, need),
            "debt_nights_counted": sum(1 for n in window if not n.flagged),
            "bedtime_spread_minutes": clock_spread_minutes([n.start_local_minutes for n in last_spread]),
            "wake_spread_minutes": clock_spread_minutes(
                [n.end_local_minutes for n in last_spread if n.end_local_minutes is not None]),
            "stages_seconds": {"deep": last_night.deep_seconds, "light": last_night.light_seconds,
                               "rem": last_night.rem_seconds},
            "stages_note": "Wrist-based stages are approximate.",
            "last_night_flagged": last_night.flagged,
        },
    )


def performance_on(ctx: MetricContext, day) -> float | None:
    """Sleep divided by need for one night, using only nights before it. Used by Recovery."""
    night = next((n for n in ctx.sleep if n.day == day and not n.flagged), None)
    if night is None:
        return None
    earlier = [n for n in ctx.sleep
               if timedelta(0) < day - n.day <= timedelta(days=NEED_WINDOW_DAYS)]
    need = sleep_need_seconds(earlier)
    return night.seconds / need if need else None
