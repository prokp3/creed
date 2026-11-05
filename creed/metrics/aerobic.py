"""Aerobic efficiency on steady runs: speed for each heartbeat, and heart-rate drift within a run.

Efficiency Factor is speed in metres per minute divided by heart rate. Decoupling (Pa:HR) compares the
first and second halves of a run. Both come from Joe Friel, "The Triathlete's Training Bible", as also
described by TrainingPeaks. The steadiness rules that pick which runs count are this project's choices.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from creed.metrics.base import COMPUTED, INSUFFICIENT, OK, ActivityRecord, MetricContext, MetricResult, Why

WINDOW_DAYS = 42
MIN_STEADY_RUNS = 6
HIGH_CONFIDENCE_RUNS = 10

WHY = Why(
    formula="Efficiency is metres per minute divided by heart rate. Drift compares the first and second halves of a "
            "run. HR at a given pace comes from a straight line fitted through your steady runs.",
    inputs="Heart rate and speed samples from FIT files. The first 10 minutes are skipped. Only outdoor runs with at "
           "least 20 more minutes at an even pace count, judged mainly on 5-minute averages because wrist GPS is noisy.",
    window="The last 42 days, compared with the 42 before.",
    citation="Friel, The Triathlete's Training Bible (Efficiency Factor and Pa:HR decoupling).",
    note="Wrist HR lags and can drift. Heat changes this too, and Goa is hot, so read the trend rather than one run.",
)


def fit_line(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least-squares slope and intercept, or None if the x values don't vary."""
    if len(points) < 2:
        return None
    mean_x = statistics.fmean(x for x, _ in points)
    mean_y = statistics.fmean(y for _, y in points)
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    if spread == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread
    return slope, mean_y - slope * mean_x


def _steady_runs(activities: list[ActivityRecord], newest, oldest) -> list[ActivityRecord]:
    return [a for a in activities
            if a.steady and not a.flagged and a.efficiency is not None and oldest <= a.day <= newest]


def compute(ctx: MetricContext) -> MetricResult:
    base = {"key": "aerobic", "title": "Aerobic efficiency", "tag": COMPUTED, "unit": "m/min per bpm", "why": WHY}
    window_start = ctx.today - timedelta(days=WINDOW_DAYS - 1)
    runs = _steady_runs(ctx.activities, ctx.today, window_start)
    if len(runs) < MIN_STEADY_RUNS:
        return MetricResult(**base, state=INSUFFICIENT, value=None, confidence="none",
                            reason=f"Needs {MIN_STEADY_RUNS} steady runs in {WINDOW_DAYS} days. You have {len(runs)}.",
                            details={"steady_runs": len(runs), "runs_needed": MIN_STEADY_RUNS})

    efficiency = statistics.median(a.efficiency for a in runs)
    previous = _steady_runs(ctx.activities, window_start - timedelta(days=1), window_start - timedelta(days=WINDOW_DAYS))
    drifts = [a.decoupling_pct for a in runs if a.decoupling_pct is not None]
    points = [(a.steady_speed_mps, a.steady_hr) for a in runs if a.steady_speed_mps and a.steady_hr]
    reference_speed = statistics.median(p[0] for p in points) if points else None
    line = fit_line(points)
    hr_at_reference = line[0] * reference_speed + line[1] if line and reference_speed else None
    return MetricResult(
        **base, state=OK, value=efficiency,
        confidence="high" if len(runs) >= HIGH_CONFIDENCE_RUNS else "medium",
        details={
            "steady_runs": len(runs),
            "previous_efficiency": statistics.median(a.efficiency for a in previous) if len(previous) >= MIN_STEADY_RUNS else None,
            "previous_steady_runs": len(previous),
            "median_drift_pct": statistics.median(drifts) if drifts else None,
            "reference_speed_mps": reference_speed,
            "hr_at_reference_speed": hr_at_reference,
        },
    )
