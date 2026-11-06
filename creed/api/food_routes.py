"""The food logger's routes. Any signed-in person can use them, and each sees and changes only their own food.

Writes all go through one route, /api/food/changes, as a list of changes. The app sends a tap straight away when
it has a signal and queues it when it doesn't; either way the same list arrives, possibly more than once. Each
change is applied on its own and reports its own outcome, so one bad change can't hold up the rest.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request

from creed import config
from creed import settings as app_settings
from creed.api.deps import Conn, Session
from creed.db import food, reads
from creed.food import day as food_day
from creed.food import targets
from creed.food.nutrition import InvalidFood

router = APIRouter(prefix="/api/food")

MAX_CHANGES = 200


def _today(conn: psycopg.Connection) -> date:
    """The day in the deployment's time zone. The app sends its own date when it knows better."""
    return config.local_today(app_settings.load(conn).timezone)


def _day(value: str | None, conn: psycopg.Connection) -> date:
    if value is None:
        return _today(conn)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must look like 2026-11-06.") from None


@router.get("/library")
def library(session: Session, conn: Conn) -> dict[str, Any]:
    """Everything the app keeps on the phone to log without waiting: nutrients, foods, presets, recents and
    targets."""
    user = session["user_id"]
    with food.as_user(conn, user):
        return {
            "nutrients": food.list_nutrients(conn, user),
            "foods": food.list_foods(conn, user, limit=5000),
            "presets": food.list_presets(conn, user),
            "recent_food_ids": food.recent_food_ids(conn, user),
            # Every target set, so the app can show the ones in force and edit them.
            "targets": [
                {"day_type": t.day_type, "effective_from": t.effective_from.isoformat(), "targets": t.targets}
                for t in sorted(food.target_sets(conn, user), key=lambda t: (t.day_type, t.effective_from))
            ],
        }


@router.get("/day")
def day_screen(session: Session, conn: Conn, date_: Annotated[str | None, Query(alias="date")] = None) -> dict[str, Any]:
    """One day's meals, totals and rings, with Garmin's burn for the owner."""
    user = session["user_id"]
    today = _today(conn)
    day = _day(date_, conn)
    threshold = targets.DEFAULT_TRAINING_MINUTES
    # Garmin data first: it can't be read while acting for a user.
    kind = food.day_types(conn, user, day, day, threshold)[day]
    burned = None
    if session["is_owner"]:
        burned = reads.metric_series(conn, ["calories_total"], day, day)["calories_total"].get(day)
    with food.as_user(conn, user):
        sets = food.target_sets(conn, user)
        return food_day.day_view(
            day=day, today=today, entries=food.entries_between(conn, user, day, day),
            nutrients=food.list_nutrients(conn, user), day_type=kind, threshold_minutes=threshold,
            target_set=targets.targets_for(day, kind.day_type, sets), burned_kcal=burned,
        )


def _when(change: dict[str, Any]) -> Any:
    if "changed_at" not in change:
        raise InvalidFood("Every change needs the time it was made.")
    return change["changed_at"]


def _date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise InvalidFood("A date must look like 2026-11-06.") from None


# Each kind of change, and how it's applied. Every one takes (conn, user, change).
APPLY: dict[str, Callable[[psycopg.Connection, str, dict[str, Any]], Any]] = {
    "food.save": lambda c, u, ch: food.save_food(c, u, ch.get("record") or {}, _when(ch)),
    "food.delete": lambda c, u, ch: food.delete_food(c, u, ch.get("id"), _when(ch)),
    "preset.save": lambda c, u, ch: food.save_preset(c, u, ch.get("record") or {}, _when(ch)),
    "preset.delete": lambda c, u, ch: food.delete_preset(c, u, ch.get("id"), _when(ch)),
    "presets.order": lambda c, u, ch: food.reorder_presets(c, u, ch.get("ids") or [], _when(ch)),
    "entries.save": lambda c, u, ch: food.save_entries(c, u, ch.get("records") or [], _when(ch)),
    "entries.delete": lambda c, u, ch: food.delete_entries(c, u, ch.get("ids") or [], _when(ch)),
    "group.delete": lambda c, u, ch: food.delete_group(c, u, ch.get("group_id"), _when(ch)),
    "nutrient.save": lambda c, u, ch: food.save_nutrient(c, u, ch.get("record") or {}, _when(ch)),
    "nutrient.delete": lambda c, u, ch: food.delete_nutrient(c, u, ch.get("id"), _when(ch)),
    "targets.save": lambda c, u, ch: food.save_targets(c, u, ch.get("day_type"), _date(ch.get("effective_from")),
                                                      ch.get("targets") or {}, _when(ch)),
    "day_type.set": lambda c, u, ch: food.set_day_type(c, u, _date(ch.get("date")), ch.get("day_type"), _when(ch)),
}


@router.post("/changes")
async def changes(request: Request, session: Session, conn: Conn) -> dict[str, Any]:
    """Apply changes in order. Each result is {"result": ...} or {"error": message}, matching the change's place."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Send a JSON object.") from None
    batch = body.get("changes") if isinstance(body, dict) else None
    if not isinstance(batch, list) or not 1 <= len(batch) <= MAX_CHANGES:
        raise HTTPException(status_code=422, detail=f"Send 1 to {MAX_CHANGES} changes.")
    user = session["user_id"]
    results: list[dict[str, Any]] = []
    with food.as_user(conn, user):
        for change in batch:
            kind = change.get("type") if isinstance(change, dict) else None
            apply = APPLY.get(kind) if isinstance(kind, str) else None
            if apply is None:
                results.append({"error": "Unknown kind of change."})
                continue
            conn.execute("savepoint food_change")
            try:
                results.append({"result": apply(conn, user, change)})
            except InvalidFood as exc:
                conn.execute("rollback to savepoint food_change")
                results.append({"error": str(exc)})
            else:
                conn.execute("release savepoint food_change")
    conn.commit()
    return {"results": results}
