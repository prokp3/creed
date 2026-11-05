"""Max and resting heart rate: estimated from your own data unless you override them in Settings."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import timedelta

from creed.metrics.base import MetricContext

MIN_ACTIVITIES_FOR_MAX = 5
TOP_VALUES_FOR_MAX = 3
RESTING_WINDOW_DAYS = 60
MIN_DAYS_FOR_RESTING = 7


@dataclass(frozen=True)
class HrParams:
    max_hr: float | None
    max_source: str
    resting_hr: float | None
    resting_source: str


def estimate(ctx: MetricContext) -> HrParams:
    return HrParams(*_max_hr(ctx), *_resting_hr(ctx))


def _max_hr(ctx: MetricContext) -> tuple[float | None, str]:
    if ctx.settings.max_hr:
        return ctx.settings.max_hr, "Set by you in Settings."
    # Swims are left out because wrist HR is unreliable in water.
    values = sorted(
        (a.max_hr for a in ctx.activities
         if a.max_hr and not a.flagged and a.discipline != "swim"),
        reverse=True,
    )
    if len(values) < MIN_ACTIVITIES_FOR_MAX:
        return None, f"Needs {MIN_ACTIVITIES_FOR_MAX} activities with heart rate. You have {len(values)}."
    # The median of the top few, because the single highest reading on a wrist sensor can be a spike.
    top = values[:TOP_VALUES_FOR_MAX]
    return statistics.median(top), (
        f"Median of your {TOP_VALUES_FOR_MAX} highest activity max HR readings ({', '.join(f'{v:g}' for v in top)})."
    )


def _resting_hr(ctx: MetricContext) -> tuple[float | None, str]:
    if ctx.settings.resting_hr:
        return ctx.settings.resting_hr, "Set by you in Settings."
    cutoff = ctx.today - timedelta(days=RESTING_WINDOW_DAYS)
    values = [v for day, v in ctx.resting_hr.items() if cutoff <= day <= ctx.today]
    if len(values) < MIN_DAYS_FOR_RESTING:
        return None, f"Needs {MIN_DAYS_FOR_RESTING} days of resting HR in the last {RESTING_WINDOW_DAYS}. You have {len(values)}."
    return statistics.median(values), f"Median of Garmin's resting HR over {len(values)} days in the last {RESTING_WINDOW_DAYS}."
