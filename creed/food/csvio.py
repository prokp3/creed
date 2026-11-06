"""The food log as CSV, and back.

Export writes one row per entry with its own values for each nutrient, so the file is useful in a spreadsheet.
Import reads that format back exactly (ids included, so importing the same file twice changes nothing), and also
reads simpler hand-made files: a date, a time, a food and some values are enough.

Nothing here touches the database. Import turns rows into entry records and says what's wrong with any it can't
use; the caller decides what to save.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from creed.food import nutrition
from creed.food.nutrition import InvalidFood

FIXED = ("entry_id", "group_id", "date", "time", "utc_offset", "meal", "kind", "food", "brand", "quantity", "unit",
         "amount", "base", "food_id", "preset_id")
MAX_ROWS = 20_000
IMPORTED = "Imported"
# A namespace for ids made from a row's content, so the same hand-made row always gets the same id.
ROW_NAMESPACE = uuid.UUID("5b6f1f2e-6d1c-4f4e-9a59-7c1e0f6a2b10")
ONE_OFF_UNIT = "serving"
ONE_OFF_AMOUNT = 1000.0


def nutrient_header(n: Mapping[str, Any]) -> str:
    return f"{n['name']} ({n['unit']})"


def _number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def export(entries: Sequence[Mapping[str, Any]], nutrients: Sequence[Mapping[str, Any]]) -> str:
    """Entries as CSV, oldest first, with each nutrient's amount for that entry. Unknown values are left blank."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([*FIXED, *(nutrient_header(n) for n in nutrients)])
    for e in sorted(entries, key=lambda e: (e["logged_at"], str(e["id"]))):
        local = e["logged_at"].astimezone(timezone(timedelta(minutes=e["utc_offset_minutes"])))
        values = nutrition.entry_nutrients(e)
        writer.writerow([
            e["id"], e["group_id"], local.date().isoformat(), local.time().isoformat(timespec="seconds"),
            _offset(e["utc_offset_minutes"]), e["meal_label"], e["kind"], e["food_name"], e["food_brand"] or "",
            _number(e["quantity"]), e["unit"], _number(e["base_amount"]), e["base"], e["food_id"] or "",
            e["preset_id"] or "",
            *(_number(values[n["id"]]) if n["id"] in values else "" for n in nutrients),
        ])
    return out.getvalue()


def _header_map(header: Sequence[str], nutrients: Sequence[Mapping[str, Any]]) -> tuple[dict[str, int],
                                                                                         dict[str, int], list[str]]:
    """Which column holds each fixed field and each nutrient. Nutrients match by "Name (unit)", name or id."""
    fixed: dict[str, int] = {}
    found: dict[str, int] = {}
    ignored: list[str] = []
    names = {}
    for n in nutrients:
        for key in (nutrient_header(n), n["name"], n["id"]):
            names[key.strip().lower()] = n["id"]
    for index, raw in enumerate(header):
        name = raw.strip().lstrip("﻿")
        key = name.lower()
        if key in FIXED:
            fixed[key] = index
        elif key in names:
            found[names[key]] = index
        elif name:
            ignored.append(name)
    return fixed, found, ignored


def _parse_number(text: str, label: str) -> float | None:
    text = text.strip().replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise InvalidFood(f"{label} must be a number.") from None
    if value < 0:
        raise InvalidFood(f"{label} can't be below 0.")
    return value


def _logged_at(day: str, clock: str, offset: str, zone_name: str) -> datetime:
    day, clock, offset = day.strip(), clock.strip(), offset.strip()
    if not day or not clock:
        raise InvalidFood("Each row needs a date and a time.")
    if re.fullmatch(r"\d{1,2}:\d{2}", clock):
        clock = f"{int(clock.split(':')[0]):02d}:{clock.split(':')[1]}:00"
    try:
        if offset:
            return datetime.fromisoformat(f"{day}T{clock}{offset}")
        return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ZoneInfo(zone_name))
    except ValueError:
        raise InvalidFood("Dates look like 2026-11-06 and times like 13:30.") from None


def parse(text: str, nutrients: Sequence[Mapping[str, Any]], zone_name: str) -> dict[str, Any]:
    """Rows to entry records. Returns {"records": [(row number, record)], "errors": [...], "ignored": [...]}."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise InvalidFood("The file is empty.") from None
    fixed, columns, ignored = _header_map(header, nutrients)
    missing = [c for c in ("date", "time", "food") if c not in fixed]
    if missing:
        raise InvalidFood(f"The file needs these columns: {', '.join(missing)}.")
    if not columns:
        raise InvalidFood("The file has no nutrient columns, such as Calories (kcal).")

    records: list[tuple[int, dict[str, Any]]] = []
    errors: list[dict[str, Any]] = []
    for number, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(records) + len(errors) >= MAX_ROWS:
            raise InvalidFood(f"Import up to {MAX_ROWS:,} rows at a time.")
        try:
            records.append((number, _record(_Row(row, fixed), row, columns, zone_name)))
        except InvalidFood as exc:
            errors.append({"row": number, "error": str(exc)})
    return {"records": records, "errors": errors, "ignored": ignored}


class _Row:
    """A row's fixed fields by name: an empty string for a column the file doesn't have."""

    def __init__(self, row: Sequence[str], fixed: Mapping[str, int]) -> None:
        self.row, self.fixed = row, fixed

    def __call__(self, name: str) -> str:
        index = self.fixed.get(name)
        return self.row[index] if index is not None and index < len(self.row) else ""


def _record(cell: Any, row: Sequence[str], columns: Mapping[str, int], zone_name: str) -> dict[str, Any]:
    logged_at = _logged_at(cell("date"), cell("time"), cell("utc_offset"), zone_name)
    food = cell("food").strip()
    if not food:
        raise InvalidFood("Each row needs a food name.")
    values: dict[str, float] = {}
    for nutrient_id, index in columns.items():
        value = _parse_number(row[index] if index < len(row) else "", nutrient_id)
        if value is not None:
            values[nutrient_id] = value
    if not values:
        raise InvalidFood("Each row needs at least one value, such as calories.")

    base = cell("base").strip() or "g"
    if base not in nutrition.BASES:
        raise InvalidFood("Base must be g or ml.")
    amount = _parse_number(cell("amount"), "Amount")
    quantity = _parse_number(cell("quantity"), "Quantity")
    unit = cell("unit").strip()
    if amount is None:
        # No weight: something eaten once, stored as servings the way the app stores a quick add.
        quantity = quantity or 1.0
        unit, base, amount = ONE_OFF_UNIT, "g", quantity * ONE_OFF_AMOUNT
        units = {ONE_OFF_UNIT: ONE_OFF_AMOUNT}
    else:
        if amount <= 0:
            raise InvalidFood("Amount must be more than 0.")
        unit = unit or base
        quantity = quantity if quantity is not None else (amount if unit == base else 1.0)
        if quantity <= 0:
            raise InvalidFood("Quantity must be more than 0.")
        units = {} if unit == base else {unit: amount / quantity}
    per_100 = {k: v * 100.0 / amount for k, v in values.items()}

    meal = cell("meal").strip() or IMPORTED
    kind = cell("kind").strip()
    if kind not in ("preset", "quick", "import"):
        kind = "import"
    if kind == "preset" and not cell("preset_id").strip():
        kind = "import"
    entry_id = cell("entry_id").strip() or str(uuid.uuid5(
        ROW_NAMESPACE, "|".join([logged_at.isoformat(), food, unit, repr(quantity), repr(sorted(values.items()))])))
    group_id = cell("group_id").strip() or str(uuid.uuid5(ROW_NAMESPACE, f"{logged_at.isoformat()}|{meal}"))
    return {
        "id": entry_id, "group_id": group_id, "kind": kind, "meal_label": meal[:40],
        "preset_id": cell("preset_id").strip() or None, "food_id": cell("food_id").strip() or None,
        "logged_at": logged_at, "quantity": quantity, "unit": unit, "food_name": food[:80],
        "food_brand": cell("brand").strip() or None, "base": base, "nutrients_per_100": per_100, "unit_amounts": units,
    }


def same_entry(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Whether a row in the file says the same as what's already saved, allowing for rounding in the file."""
    if a["food_name"] != b["food_name"] or a["unit"] != b["unit"] or a["logged_at"] != b["logged_at"]:
        return False
    if abs(a["quantity"] - b["quantity"]) > 1e-3 * max(1.0, abs(b["quantity"])):
        return False
    va, vb = nutrition.entry_nutrients(a), nutrition.entry_nutrients(b)
    if set(va) != set(vb):
        return False
    return all(abs(va[k] - vb[k]) <= 0.01 + 1e-4 * abs(vb[k]) for k in va)
