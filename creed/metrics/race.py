"""Race countdown and fitness trend. There's no plan in v1, so this makes no readiness prediction."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from creed.metrics import fitness, strain
from creed.metrics.base import COMPUTED, MetricContext, MetricResult, OK, Why

TREND_DAYS = 42

WHY = Why(
    formula="Time from now until the start of race day in the race's time zone, plus the change in fitness over 42 days.",
    inputs="The race date in Settings, and fitness from the Banister model.",
    window="Fitness change over the last 42 days.",
    citation="Banister et al. 1975 for fitness. The countdown is plain arithmetic.",
    note="There's no training plan in v1, so this doesn't predict race readiness.",
)


def countdown(now: datetime, race_day, tz_name: str) -> dict[str, int]:
    start = datetime.combine(race_day, time.min, tzinfo=ZoneInfo(tz_name))
    left = max(0, int((start - now).total_seconds()))
    return {"days": left // 86400, "hours": left % 86400 // 3600, "minutes": left % 3600 // 60,
            "seconds": left % 60, "total_seconds": left}


def compute(ctx: MetricContext) -> MetricResult:
    left = countdown(ctx.now, ctx.settings.race_date, ctx.settings.timezone)
    totals = {day: sum(d.values()) for day, d in strain.daily_loads(ctx).items()}
    rows = fitness.series(totals, ctx.today)
    now_fitness = rows[-1].fitness if rows else None
    then = rows[-1 - TREND_DAYS].fitness if len(rows) > TREND_DAYS else None
    return MetricResult(
        key="race", title="Race countdown", tag=COMPUTED, state=OK, value=left["days"], unit="days",
        confidence="high", why=WHY,
        details={"countdown": left, "race_date": ctx.settings.race_date.isoformat(),
                 "timezone": ctx.settings.timezone, "fitness": now_fitness,
                 "fitness_change_42_days": None if then is None else now_fitness - then},
    )
