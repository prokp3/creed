"""Weekly swim, bike and run volume and load, with each discipline's share. Weeks start on Monday."""
from __future__ import annotations

from datetime import date, timedelta

from creed.metrics import hr_params, strain
from creed.metrics.base import COMPUTED, INSUFFICIENT, OK, MetricContext, MetricResult, Why

DISCIPLINES = ("swim", "bike", "run")
WEEKS_SHOWN = 8

WHY = Why(
    formula="Adds up distance, time and load for each discipline, Monday to Sunday. Share is each discipline's "
            "part of the week's swim, bike and run load.",
    inputs="Activities from Garmin, and load from the Strain metric.",
    window="This week and the previous 7.",
    citation="A plain sum, so no published method is needed. Load uses Banister 1991 and the TrainingPeaks swim formula.",
    note="A week with no activity shows zero, because no activity was recorded.",
)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _empty() -> dict:
    return {"distance_m": 0.0, "seconds": 0.0, "load": 0.0, "activities": 0}


def compute(ctx: MetricContext) -> MetricResult:
    base = {"key": "weekly", "title": "Weekly load", "tag": COMPUTED, "unit": "load", "why": WHY}
    this_week = week_start(ctx.today)
    first_week = this_week - timedelta(weeks=WEEKS_SHOWN - 1)
    weeks = {first_week + timedelta(weeks=i): {d: _empty() for d in DISCIPLINES} for i in range(WEEKS_SHOWN)}

    params = hr_params.estimate(ctx)
    threshold = strain.swim_threshold_speed(ctx.activities)
    missing_load = 0
    for a in strain.counted(ctx.activities):
        week = weeks.get(week_start(a.day))
        if week is None or a.discipline not in week or a.day > ctx.today:
            continue
        totals = week[a.discipline]
        totals["activities"] += 1
        totals["distance_m"] += a.distance_m or 0.0
        totals["seconds"] += a.duration_seconds or 0.0
        load, _ = strain.activity_load(a, params, threshold, ctx.settings.trimp_curve)
        if load is None:
            missing_load += 1
        else:
            totals["load"] += load

    if not any(t["activities"] for week in weeks.values() for t in week.values()):
        return MetricResult(**base, state=INSUFFICIENT, value=None, confidence="none",
                            reason=f"No swim, bike or run in the last {WEEKS_SHOWN} weeks.",
                            details={"weeks": []})
    rows = []
    for start, week in sorted(weeks.items()):
        total = sum(t["load"] for t in week.values())
        rows.append({
            "week_start": start.isoformat(),
            "total_load": total,
            "disciplines": {d: {**t, "share": t["load"] / total if total else 0.0} for d, t in week.items()},
        })
    return MetricResult(**base, state=OK, value=rows[-1]["total_load"],
                        confidence="low" if missing_load else "medium",
                        details={"weeks": rows, "activities_without_load": missing_load})
