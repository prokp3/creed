"""One day's food, shaped for the screen: meals in time order, totals, rings against that day's targets, and the
balance against Garmin's burn. Pure data in and out, so it can be checked by hand."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from creed.food import nutrition
from creed.food.targets import DayType, TargetSet


def _entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """An entry with its own values worked out. Its snapshot stays in, so the phone can edit it offline."""
    return {**entry, "nutrients": nutrition.entry_nutrients(entry)}


def meals(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Entries logged together (one preset tap, or one quick add) form a meal, ordered by its first entry's time."""
    groups: dict[str, dict[str, Any]] = {}
    for entry in sorted(entries, key=lambda e: (e["logged_at"], e["id"])):
        meal = groups.get(entry["group_id"])
        if meal is None:
            meal = groups[entry["group_id"]] = {
                "group_id": entry["group_id"], "label": entry["meal_label"], "kind": entry["kind"],
                "preset_id": entry["preset_id"], "logged_at": entry["logged_at"], "entries": [], "totals": {},
            }
        shaped = _entry(entry)
        meal["entries"].append(shaped)
        for key, value in shaped["nutrients"].items():
            meal["totals"][key] = meal["totals"].get(key, 0.0) + value
    return sorted(groups.values(), key=lambda m: m["logged_at"])


def rings(nutrients: Sequence[Mapping[str, Any]], totals: nutrition.Totals,
          target_set: TargetSet | None) -> list[dict[str, Any]]:
    """One ring per nutrient that has a target that day, in the nutrients' own order."""
    if target_set is None:
        return []
    shown = []
    for n in nutrients:
        target = target_set.targets.get(n["id"])
        if target is None:
            continue
        eaten = totals.values.get(n["id"], 0.0)
        shown.append({
            "id": n["id"], "name": n["name"], "unit": n["unit"], "eaten": eaten, "target": target,
            "remaining": target - eaten, "fraction": eaten / target, "incomplete": n["id"] in totals.incomplete,
        })
    return shown


def day_view(*, day: date, today: date, entries: Sequence[Mapping[str, Any]], nutrients: Sequence[Mapping[str, Any]],
             day_type: DayType, threshold_minutes: float, target_set: TargetSet | None,
             burned_kcal: float | None, source_tag: str = "Garmin") -> dict[str, Any]:
    ids = [n["id"] for n in nutrients]
    totals = nutrition.totals(entries, ids)
    eaten = totals.values.get("kcal", 0.0)
    return {
        "date": day.isoformat(),
        "is_today": day == today,
        "day_type": {"type": day_type.day_type, "how": day_type.how, "threshold_minutes": threshold_minutes},
        "targets_from": target_set.effective_from.isoformat() if target_set else None,
        "nutrients": [dict(n) for n in nutrients],
        "totals": totals.values,
        "incomplete": sorted(totals.incomplete),
        "rings": rings(nutrients, totals, target_set),
        "meals": meals(entries),
        "balance": {
            "tag": source_tag,
            "estimate": True,
            # Today isn't over, so its burn is only what Garmin has counted so far.
            "so_far": day == today,
            "eaten_kcal": eaten,
            "burned_kcal": burned_kcal,
            "net_kcal": nutrition.net_calories(eaten, burned_kcal),
        },
    }
