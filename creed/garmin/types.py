"""Mapping Garmin activity type keys to the three triathlon disciplines."""
from __future__ import annotations


def discipline_of(type_key: str | None) -> str:
    key = (type_key or "").lower()
    if key in ("multi_sport", "transition", "transition_v2") or "transition" in key:
        return "multisport"
    if "swim" in key:
        return "swim"
    if "cycl" in key or "biking" in key or "bike" in key or "virtual_ride" in key:
        return "bike"
    if "run" in key:
        return "run"
    return "other"
