"""Fitness, fatigue and form: the Banister impulse-response model.

    Fitness (CTL) today = CTL yesterday + (load today - CTL yesterday) / 42
    Fatigue (ATL) today = ATL yesterday + (load today - ATL yesterday) / 7
    Form (TSB) today = CTL yesterday - ATL yesterday, meaning how you arrive at today

Banister EW, Calvert TW, Savage MV, Bach T (1975), "A systems model of training for athletic
performance". Aust J Sports Med 7:57-61. This running-average form, with 42- and 7-day constants,
is the one popularised by Coggan and TrainingPeaks.

To personalize later: fit both time constants to your own performance tests, which needs repeated
race or test results. Until then these are population defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from creed.metrics import strain
from creed.metrics.base import COMPUTED, INSUFFICIENT, OK, MetricContext, MetricResult, Why

FITNESS_DAYS = 42
FATIGUE_DAYS = 7
MIN_HISTORY_DAYS = 42

WHY = Why(
    formula="Fitness and fatigue are running averages of daily load, over 42 and 7 days. Form is yesterday's fitness "
            "minus yesterday's fatigue.",
    inputs="Daily load from the Strain metric. A day with no activity counts as zero load.",
    window="All your history, weighted towards recent days.",
    citation="Banister et al. 1975.",
    note="The 42- and 7-day constants are population defaults, and could be personalized with repeated test results.",
)


@dataclass(frozen=True)
class FitnessDay:
    day: date
    load: float
    fitness: float
    fatigue: float
    form: float


def series(daily_load: dict[date, float], end: date, start: date | None = None) -> list[FitnessDay]:
    """One row per day from the first day with load to `end`. Both averages start at zero."""
    if not daily_load:
        return []
    day = start or min(daily_load)
    fitness = fatigue = 0.0
    rows = []
    while day <= end:
        load = daily_load.get(day, 0.0)
        form = fitness - fatigue
        fitness += (load - fitness) / FITNESS_DAYS
        fatigue += (load - fatigue) / FATIGUE_DAYS
        rows.append(FitnessDay(day, load, fitness, fatigue, form))
        day += timedelta(days=1)
    return rows


def compute(ctx: MetricContext) -> MetricResult:
    totals = {day: sum(d.values()) for day, d in strain.daily_loads(ctx).items()}
    rows = series(totals, ctx.today)
    base = {"key": "fitness", "title": "Fitness, fatigue, form", "tag": COMPUTED, "unit": "load", "why": WHY}
    if not rows:
        return MetricResult(**base, state=INSUFFICIENT, value=None, confidence="none",
                            reason="No activities with a load yet.")
    latest = rows[-1]
    return MetricResult(
        **base, state=OK, value=latest.fitness,
        confidence="medium" if len(rows) >= MIN_HISTORY_DAYS else "low",
        details={"fitness": latest.fitness, "fatigue": latest.fatigue, "form": latest.form, "days": len(rows),
                 "series": [{"day": r.day.isoformat(), "load": r.load, "fitness": r.fitness,
                             "fatigue": r.fatigue, "form": r.form} for r in rows[-180:]]},
    )
