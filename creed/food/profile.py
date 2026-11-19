"""The body details auto food targets are worked out from. Every field is optional, so a half-filled form can be
saved, but any value given has to be believable. The maths itself runs on the phone (web/src/lib/autotargets.js),
where the workings are shown."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from creed.food.nutrition import InvalidFood

SEXES = ("male", "female")
ACTIVITY = ("sitting", "some", "feet")
INTENSITY = ("easy", "moderate", "hard")
GOALS = ("lose", "lose_slowly", "maintain", "gain_slowly")


def _number(value: Any, label: str, low: float, high: float, whole: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise InvalidFood(f"{label} must be between {low:g} and {high:g}.")
    if whole and not float(value).is_integer():
        raise InvalidFood(f"{label} must be a whole number.")
    return int(value) if whole else float(value)


def clean_profile(value: Any, today: date | None = None) -> dict[str, Any]:
    """Only known fields, each checked. A missing or null field is left out."""
    if not isinstance(value, Mapping):
        raise InvalidFood("Body details must be a list of values.")
    year = (today or date.today()).year
    checks = {
        "sex": lambda v: v if v in SEXES else _bad("Sex must be male or female."),
        "birth_year": lambda v: _number(v, "Year born", year - 100, year - 10, whole=True),
        "height_cm": lambda v: _number(v, "Height", 100, 250),
        "weight_kg": lambda v: _number(v, "Weight", 30, 300),
        "activity": lambda v: v if v in ACTIVITY else _bad("Unknown activity level."),
        "workout_minutes": lambda v: _number(v, "Typical workout", 0, 600, whole=True),
        "intensity": lambda v: v if v in INTENSITY else _bad("Unknown workout intensity."),
        "goal": lambda v: v if v in GOALS else _bad("Unknown goal."),
        "protein_per_kg": lambda v: _number(v, "Protein per kg", 0.8, 3.0),
    }
    unknown = set(value) - set(checks)
    if unknown:
        raise InvalidFood(f"Unknown body detail: {min(unknown)}.")
    return {key: checks[key](v) for key, v in value.items() if v is not None}


def _bad(message: str) -> Any:
    raise InvalidFood(message)
