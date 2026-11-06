"""Units, scaling, totals and net calories.

Every food's values are per 100 of its base (g, or ml for a liquid). A quantity in any unit is turned into
an amount of the base first, then values scale from there. Nothing here guesses: a nutrient a food doesn't
list is unknown, not zero, and totals say which nutrients had gaps.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

BASES = ("g", "ml")
BUILT_IN = ("kcal", "protein", "carbs", "fat", "sodium", "potassium", "magnesium")
QUICK_ADD = "Quick add"

# The most of a nutrient 100 g of anything can hold, by unit. Pure fat is 900 kcal and 100 g of fat; table salt
# is about 39,000 mg of sodium. Liquids denser than water (honey, syrups) can go a little over 100 g per 100 ml.
LIMIT_PER_100 = {"kcal": 1000.0, "g": 150.0, "mg": 100_000.0}
LIMIT_OTHER_UNIT = 100_000.0
MAX_QUANTITY = 100_000.0


class InvalidFood(ValueError):
    """A value that can't be saved or used. The message is written for the person using the app."""


def _number(label: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InvalidFood(f"{label} must be a number.")
    return float(value)


def check_quantity(value: Any) -> float:
    quantity = _number("Quantity", value)
    if not 0 < quantity <= MAX_QUANTITY:
        raise InvalidFood("Quantity must be more than 0.")
    return quantity


def unit_amount(unit: str, base: str, units: Mapping[str, float]) -> float:
    """How much of the base one of `unit` is. The base itself is always 1."""
    if unit == base:
        return 1.0
    if unit in units:
        return float(units[unit])
    raise InvalidFood(f"This food can't be measured in {unit}. Use {base} or one of its units.")


def base_amount(quantity: Any, unit: str, base: str, units: Mapping[str, float]) -> float:
    """6 pieces of a 50 g egg is 300 g."""
    return check_quantity(quantity) * unit_amount(unit, base, units)


def scale(per_100: Mapping[str, float], amount: float) -> dict[str, float]:
    """Values for `amount` of the base, from values per 100 of it."""
    return {key: value * amount / 100.0 for key, value in per_100.items()}


def per_100_from_unit(values: Mapping[str, float], amount: float) -> dict[str, float]:
    """Values typed in for one unit (one 30 g scoop) turned into values per 100 of the base."""
    if amount <= 0:
        raise InvalidFood("A unit must weigh more than 0.")
    return {key: value * 100.0 / amount for key, value in values.items()}


def clean_nutrients(values: Any, known: Mapping[str, str]) -> dict[str, float]:
    """Check values per 100 of the base. `known` maps nutrient id to its unit. A missing nutrient stays missing."""
    if not isinstance(values, Mapping):
        raise InvalidFood("Nutrients must be a list of values.")
    cleaned: dict[str, float] = {}
    for key, value in values.items():
        if key not in known:
            raise InvalidFood(f"Unknown nutrient: {key}.")
        if value is None:
            continue
        number = _number(f"{key.capitalize()}", value)
        limit = LIMIT_PER_100.get(known[key], LIMIT_OTHER_UNIT)
        if not 0 <= number <= limit:
            raise InvalidFood(f"{key.capitalize()} per 100 must be between 0 and {limit:g} {known[key]}.")
        cleaned[key] = number
    return cleaned


def clean_units(units: Any, base: str) -> dict[str, float]:
    if not isinstance(units, Mapping):
        raise InvalidFood("Units must be a list of names and amounts.")
    cleaned: dict[str, float] = {}
    for name, amount in units.items():
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 20:
            raise InvalidFood("A unit needs a name of up to 20 characters.")
        name = name.strip()
        if name in BASES:
            raise InvalidFood(f"{name} is built in, so it doesn't need adding.")
        number = _number(f"One {name}", amount)
        if not 0 < number <= MAX_QUANTITY:
            raise InvalidFood(f"One {name} must be more than 0 {base}.")
        cleaned[name] = number
    return cleaned


@dataclass(frozen=True)
class Snapshot:
    """A food as it was when logged. Entries keep this, so editing the food later changes no past day."""

    food_name: str
    food_brand: str | None
    base: str
    nutrients_per_100: dict[str, float]
    unit_amounts: dict[str, float]


def snapshot(food: Mapping[str, Any]) -> Snapshot:
    return Snapshot(
        food_name=food["name"],
        food_brand=food.get("brand"),
        base=food["base"],
        nutrients_per_100=dict(food["nutrients"]),
        unit_amounts=dict(food.get("units") or {}),
    )


def entry_nutrients(entry: Mapping[str, Any]) -> dict[str, float]:
    """An entry's values, from its own snapshot and amount."""
    return scale(entry["nutrients_per_100"], entry["base_amount"])


@dataclass
class Totals:
    values: dict[str, float] = field(default_factory=dict)
    # Nutrients that at least one counted entry didn't list, so their total may be low.
    incomplete: set[str] = field(default_factory=set)
    entries: int = 0


def totals(entries: Iterable[Mapping[str, Any]], nutrient_ids: Iterable[str]) -> Totals:
    """Sums for the given nutrients. A nutrient an entry doesn't list adds nothing and marks the total incomplete."""
    ids = list(nutrient_ids)
    result = Totals(values={key: 0.0 for key in ids})
    for entry in entries:
        result.entries += 1
        values = entry_nutrients(entry)
        for key in ids:
            if key in values:
                result.values[key] += values[key]
            else:
                result.incomplete.add(key)
    return result


def net_calories(eaten_kcal: float, burned_kcal: float | None) -> float | None:
    """Eaten minus burned. Positive means a surplus. No burn figure means no balance, never a guess."""
    if burned_kcal is None:
        return None
    return eaten_kcal - burned_kcal
