"""Food over 7 or 30 days: each day's totals against that day's targets and Garmin's burn, and averages.

A day with nothing logged is unknown, not a day of eating nothing, so it's left out of every average and shown as
a gap. Averages say how many days they cover.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from creed.food import nutrition
from creed.food.targets import DayType, TargetSet, targets_for


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def trends(*, start: date, end: date, entries: Sequence[Mapping[str, Any]], nutrients: Sequence[Mapping[str, Any]],
           day_types: Mapping[date, DayType], target_sets: Sequence[TargetSet],
           burned: Mapping[date, float | None]) -> dict[str, Any]:
    ids = [n["id"] for n in nutrients]
    by_day: dict[date, list[Mapping[str, Any]]] = {}
    for entry in entries:
        by_day.setdefault(entry["local_date"], []).append(entry)

    days = []
    day = start
    while day <= end:
        logged = by_day.get(day, [])
        kind = day_types[day]
        target_set = targets_for(day, kind.day_type, target_sets)
        sums = nutrition.totals(logged, ids) if logged else None
        days.append({
            "date": day.isoformat(),
            "day_type": kind.day_type,
            "entries": len(logged),
            "totals": sums.values if sums else None,
            "incomplete": sorted(sums.incomplete) if sums else [],
            "targets": dict(target_set.targets) if target_set else None,
            "burned_kcal": burned.get(day),
        })
        day += timedelta(days=1)

    logged_days = [d for d in days if d["entries"]]
    averages = {}
    for n in ids:
        eaten = [d["totals"][n] for d in logged_days]
        targets = [d["targets"][n] for d in logged_days if d["targets"] and n in d["targets"]]
        averages[n] = {"eaten": _mean(eaten), "target": _mean(targets) if len(targets) == len(eaten) else None}
    # Net only over days with both a log and a burn figure.
    balanced = [d for d in logged_days if d["burned_kcal"] is not None]
    protein_days = [d for d in logged_days if d["targets"] and "protein" in d["targets"]]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "nutrients": [dict(n) for n in nutrients],
        "days": days,
        "logged_days": len(logged_days),
        "averages": averages,
        "net": {
            "days": len(balanced),
            "average_kcal": _mean([d["totals"]["kcal"] - d["burned_kcal"] for d in balanced]) if "kcal" in ids else None,
            "estimate": True,
        },
        "protein_target_met": {
            "days": sum(1 for d in protein_days if d["totals"]["protein"] >= d["targets"]["protein"]),
            "of": len(protein_days),
        },
    }
