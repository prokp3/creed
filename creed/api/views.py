"""Shape metric results into what each screen shows. No web framework or database here.

The home screen rule: a ring shows only when it has enough data. Recovery and Sleep otherwise collapse
into a "hidden" list with the reason, and resting HR takes a ring so the screen stays useful.

Red means attention, so `attention` is true only for a real problem.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from creed import config
from creed.metrics import hr_params, strain
from creed.metrics.base import OK, MetricContext, MetricResult

LOW_RECOVERY = 34
SHORT_SLEEP_PERFORMANCE = 0.85
RESTING_LOOKBACK_DAYS = 3
RESTING_BASELINE_DAYS = 28
DISCIPLINES = ("run", "bike", "swim")


def metric_json(result: MetricResult) -> dict[str, Any]:
    data = asdict(result)
    data.pop("details", None)
    return data


def _recovery_ring(result: MetricResult) -> dict[str, Any]:
    return {"key": "recovery", "label": "Recovery", "tag": result.tag, "value": result.value, "unit": "of 100",
            "fraction": result.value / 100, "attention": result.value < LOW_RECOVERY,
            "confidence": result.confidence}


def _strain_ring(result: MetricResult) -> dict[str, Any]:
    reference = result.details.get("ring_reference")
    value = result.value if result.state == OK else None
    fraction = min(value / reference, 1.0) if value is not None and reference else 0.0
    return {"key": "strain", "label": "Strain", "tag": result.tag, "value": value, "unit": "load",
            "fraction": fraction, "attention": False, "confidence": result.confidence,
            "reason": result.reason or None}


def _sleep_ring(result: MetricResult) -> dict[str, Any]:
    performance = result.details["performance"]
    return {"key": "sleep", "label": "Sleep", "tag": result.tag, "value": result.value, "unit": "seconds",
            "need_seconds": result.details["need_seconds"], "fraction": min(performance, 1.0),
            "attention": performance < SHORT_SLEEP_PERFORMANCE, "confidence": result.confidence}


def resting_hr_view(ctx: MetricContext) -> dict[str, Any] | None:
    """The newest reading from the last few days, with the difference from your own baseline."""
    for back in range(RESTING_LOOKBACK_DAYS):
        day = ctx.today - timedelta(days=back)
        value = ctx.resting_hr.get(day)
        if value is None:
            continue
        baseline = [v for d, v in ctx.resting_hr.items()
                    if timedelta(0) < day - d <= timedelta(days=RESTING_BASELINE_DAYS)]
        return {"value": value, "day": day.isoformat(), "tag": config.source_label(),
                "difference": value - statistics.fmean(baseline) if baseline else None}
    return None


def _discipline_day(ctx: MetricContext, day: date) -> dict[str, dict[str, float]]:
    params = hr_params.estimate(ctx)
    threshold = strain.swim_threshold_speed(ctx.activities)
    totals = {d: {"distance_m": 0.0, "seconds": 0.0, "load": 0.0, "activities": 0} for d in DISCIPLINES}
    for a in strain.counted(ctx.activities):
        if a.day != day or a.discipline not in totals:
            continue
        row = totals[a.discipline]
        row["activities"] += 1
        row["distance_m"] += a.distance_m or 0.0
        row["seconds"] += a.duration_seconds or 0.0
        load, _ = strain.activity_load(a, params, threshold, ctx.settings.trimp_curve)
        row["load"] += load or 0.0
    return totals


NO_LOAD = {"load": None, "load_method": None}


def activity_loads(ctx: MetricContext) -> dict[int, dict[str, Any]]:
    """Each activity's computed load, using the current heart-rate settings and load curve."""
    params = hr_params.estimate(ctx)
    threshold = strain.swim_threshold_speed(ctx.activities)
    loads = {}
    for a in ctx.activities:
        load, method = strain.activity_load(a, params, threshold, ctx.settings.trimp_curve)
        loads[a.activity_id] = {"load": load, "load_method": method}
    return loads


def today_view(ctx: MetricContext, results: dict[str, MetricResult], garmin: dict[str, Any],
               issues: list[dict[str, Any]], sync: dict[str, Any]) -> dict[str, Any]:
    recovery, sleep = results["recovery"], results["sleep"]
    resting = resting_hr_view(ctx)
    rings = []
    hidden = []
    if recovery.state == OK:
        rings.append(_recovery_ring(recovery))
    else:
        hidden.append({"key": "recovery", "label": "Recovery", "reason": recovery.reason})
    rings.append(_strain_ring(results["strain"]))
    if sleep.state == OK:
        rings.append(_sleep_ring(sleep))
    else:
        hidden.append({"key": "sleep", "label": "Sleep", "reason": sleep.reason})
    if hidden and resting:
        rings.append({"key": "resting_hr", "label": "Resting HR", "tag": config.source_label(), "value": resting["value"],
                      "unit": "bpm", "fraction": 1.0, "attention": False, "day": resting["day"]})

    # These sit under the rings only when they aren't already a ring.
    tiles: dict[str, Any] = {}
    if not hidden and resting:
        tiles["resting_hr"] = resting
    if sleep.state == OK:
        tiles["sleep_vs_need"] = {"performance": sleep.details["performance"], "seconds": sleep.value,
                                  "need_seconds": sleep.details["need_seconds"],
                                  "attention": sleep.details["performance"] < SHORT_SLEEP_PERFORMANCE}

    weeks = results["weekly"].details.get("weeks") or []
    aerobic = results["aerobic"]
    return {
        "today": ctx.today.isoformat(),
        "race": results["race"].details,
        "rings": rings,
        "hidden": hidden,
        "tiles": tiles,
        "today_by_discipline": _discipline_day(ctx, ctx.today),
        "week_by_discipline": weeks[-1]["disciplines"] if weeks else None,
        "garmin": garmin,
        "fitness": {"value": results["fitness"].value, "state": results["fitness"].state,
                    "change_42_days": results["race"].details.get("fitness_change_42_days"),
                    "series_30_days": [{"day": r["day"], "fitness": r["fitness"]}
                                       for r in (results["fitness"].details.get("series") or [])[-30:]]},
        "aerobic": {"state": aerobic.state, "value": aerobic.value, "unit": aerobic.unit, "reason": aerobic.reason,
                    "confidence": aerobic.confidence},
        "issues": [{"code": i["code"], "severity": i["severity"], "detail": i["detail"], "day": i["day"]}
                   for i in issues],
        "sync": sync,
    }


def daily_series(values: dict[date, Any], days: int, today: date) -> list[dict[str, Any]]:
    """One entry per day, oldest first. A day with no record stays null, so the chart shows a gap."""
    return [{"day": (today - timedelta(days=back)).isoformat(), "value": values.get(today - timedelta(days=back))}
            for back in range(days - 1, -1, -1)]


def in_depth_view(ctx: MetricContext, results: dict[str, MetricResult], garmin_series: dict[str, dict[date, Any]],
                  garmin_latest: dict[str, Any], days: int, issues: list[dict[str, Any]]) -> dict[str, Any]:
    fitness = results["fitness"]
    sleep = results["sleep"]
    recovery = results["recovery"]
    loads = strain.daily_loads(ctx)
    respiration = {n.day: n.respiration for n in ctx.sleep if n.respiration is not None and not n.flagged}
    nights = {n.day: n for n in ctx.sleep}
    start = (ctx.today - timedelta(days=days - 1)).isoformat()
    return {
        "days": days,
        "form": {
            **metric_json(fitness),
            "fitness": fitness.details.get("fitness"),
            "fatigue": fitness.details.get("fatigue"),
            "form": fitness.details.get("form"),
            "series": [r for r in (fitness.details.get("series") or []) if r["day"] >= start],
        },
        "recovery": {
            **metric_json(recovery),
            "inputs": recovery.details.get("inputs"),
            "baseline_nights": recovery.details.get("baseline_nights"),
            "nights_needed": recovery.details.get("nights_needed"),
            "hrv": daily_series(ctx.hrv, days, ctx.today),
            "hrv_balanced_low": garmin_latest.get("hrv_balanced_low"),
            "hrv_balanced_high": garmin_latest.get("hrv_balanced_high"),
            "resting_hr": daily_series(ctx.resting_hr, days, ctx.today),
            "respiration": daily_series(respiration, days, ctx.today),
        },
        "sleep": {
            **metric_json(sleep),
            "details": {k: v for k, v in sleep.details.items()},
            "nights": [
                {"day": (ctx.today - timedelta(days=back)).isoformat(),
                 "seconds": nights[ctx.today - timedelta(days=back)].seconds if ctx.today - timedelta(days=back) in nights else None,
                 "flagged": nights[ctx.today - timedelta(days=back)].flagged if ctx.today - timedelta(days=back) in nights else False}
                for back in range(13, -1, -1)
            ],
        },
        "load": {
            **metric_json(results["strain"]),
            "strain_details": results["strain"].details,
            "daily": [{"day": (ctx.today - timedelta(days=back)).isoformat(),
                       **{d: loads.get(ctx.today - timedelta(days=back), {}).get(d, 0.0) for d in DISCIPLINES}}
                      for back in range(13, -1, -1)],
            "weekly": results["weekly"].details.get("weeks") or [],
            "weekly_why": metric_json(results["weekly"])["why"],
        },
        "garmin": {
            "tag": config.source_label(),
            "latest": garmin_latest,
            "body_battery_max": daily_series(garmin_series.get("body_battery_max", {}), days, ctx.today),
            "stress_avg": daily_series(garmin_series.get("stress_avg", {}), days, ctx.today),
        },
        "aerobic": {**metric_json(results["aerobic"]), "details": results["aerobic"].details},
        "data_quality": {"issues": [{"code": i["code"], "severity": i["severity"], "detail": i["detail"], "day": i["day"]}
                                    for i in issues]},
    }


def settings_view(settings: Any, ctx: MetricContext) -> dict[str, Any]:
    params = hr_params.estimate(ctx)
    return {
        **asdict(settings),
        "data_source": {"key": config.data_source(), "label": config.source_label()},
        "estimates": {"max_hr": params.max_hr, "max_hr_source": params.max_source,
                      "resting_hr": params.resting_hr, "resting_hr_source": params.resting_source},
    }
