"""The food logger's routes. Any signed-in person can use them, and each sees and changes only their own food.

Writes all go through one route, /api/food/changes, as a list of changes. The app sends a tap straight away when
it has a signal and queues it when it doesn't; either way the same list arrives, possibly more than once. Each
change is applied on its own and reports its own outcome, so one bad change can't hold up the rest.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from creed import config, notify, push
from creed import settings as app_settings
from creed.api.deps import Conn, Session
from creed.db import food, reads
from creed.db import push as db_push
from creed.food import barcode, csvio, reminders, targets
from creed.food import day as food_day
from creed.food import trends as food_trends
from creed.food.nutrition import InvalidFood

router = APIRouter(prefix="/api/food")
push_router = APIRouter(prefix="/api/push")

MAX_CHANGES = 200
MAX_CSV_CHARACTERS = 3_000_000
TREND_DAYS = (7, 30)


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
            "settings": _settings_out(food.get_settings(conn, user)),
            # Every target set, so the app can show the ones in force and edit them.
            "targets": [
                {"day_type": t.day_type, "effective_from": t.effective_from.isoformat(), "targets": t.targets}
                for t in sorted(food.target_sets(conn, user), key=lambda t: (t.day_type, t.effective_from))
            ],
            "account": user,
            "push": push_info(),
        }


def _settings_out(saved: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in saved.items() if k != "changed_at"}


def push_info() -> dict[str, Any]:
    """The public half of the notification key, which the phone needs to subscribe. None when not set up."""
    try:
        keys = push.load_vapid_keys()
    except push.PushNotConfigured:
        keys = None
    return {"public_key": keys.public_b64 if keys else None}


@router.get("/day")
def day_screen(session: Session, conn: Conn, date_: Annotated[str | None, Query(alias="date")] = None) -> dict[str, Any]:
    """One day's meals, totals and rings, with Garmin's burn for the owner."""
    user = session["user_id"]
    today = _today(conn)
    day = _day(date_, conn)
    threshold = food.get_settings(conn, user)["training_minutes"]
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
    "settings.save": lambda c, u, ch: food.save_settings(c, u, ch.get("record") or {}, _when(ch)),
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


# ---------------------------------------------------------------- trends

@router.get("/trends")
def trends_screen(session: Session, conn: Conn, days: int = 7,
                  end: Annotated[str | None, Query()] = None) -> dict[str, Any]:
    """The last 7 or 30 days: each day's food against its targets and Garmin's burn, plus averages."""
    if days not in TREND_DAYS:
        raise HTTPException(status_code=422, detail="days must be 7 or 30.")
    user = session["user_id"]
    last = _day(end, conn)
    first = last - timedelta(days=days - 1)
    threshold = food.get_settings(conn, user)["training_minutes"]
    kinds = food.day_types(conn, user, first, last, threshold)
    burned: dict[date, float | None] = {}
    if session["is_owner"]:
        burned = reads.metric_series(conn, ["calories_total"], first, last)["calories_total"]
    with food.as_user(conn, user):
        return food_trends.trends(
            start=first, end=last, entries=food.entries_between(conn, user, first, last),
            nutrients=food.list_nutrients(conn, user), day_types=kinds, target_sets=food.target_sets(conn, user),
            burned=burned,
        )


# ---------------------------------------------------------------- CSV

@router.get("/export.csv")
def export_csv(session: Session, conn: Conn) -> Response:
    """Every entry ever logged, as a spreadsheet."""
    user = session["user_id"]
    with food.as_user(conn, user):
        text = csvio.export(food.entries_between(conn, user, date(1970, 1, 1), date(2999, 12, 31)),
                            food.list_nutrients(conn, user))
    name = f"creed-food-{config.local_today(app_settings.load(conn).timezone).isoformat()}.csv"
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def _csv_body(request: Request) -> tuple[str, str, dict[str, Any]]:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Send a JSON object.") from None
    text = body.get("csv") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="Choose a CSV file.")
    if len(text) > MAX_CSV_CHARACTERS:
        raise HTTPException(status_code=422, detail="That file is too big. Import up to about 3 MB at a time.")
    zone_name = body.get("timezone") or "Asia/Kolkata"
    try:
        reminders.zone(zone_name)
    except InvalidFood:
        zone_name = "Asia/Kolkata"
    return text, zone_name, body


def _parse_csv(conn: psycopg.Connection, user: str, text: str, zone_name: str) -> dict[str, Any]:
    with food.as_user(conn, user):
        nutrients = food.list_nutrients(conn, user)
    try:
        return csvio.parse(text, nutrients, zone_name)
    except InvalidFood as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _check_rows(parsed: dict[str, Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    """Rows the database would refuse join the file's own errors, so one bad row can't stop the rest."""
    good, errors = [], list(parsed["errors"])
    for number, record in parsed["records"]:
        try:
            food.clean_entry(record)
        except InvalidFood as exc:
            errors.append({"row": number, "error": str(exc)})
        else:
            good.append((number, record))
    return good, sorted(errors, key=lambda e: e["row"])


@router.post("/import/preview")
async def import_preview(request: Request, session: Session, conn: Conn) -> dict[str, Any]:
    """What importing this file would do, without saving anything."""
    text, zone_name, _ = await _csv_body(request)
    user = session["user_id"]
    parsed = _parse_csv(conn, user, text, zone_name)
    good, errors = _check_rows(parsed)
    classified = food.classify_import(conn, user, [r for _, r in good]) if good else []
    counts = {food.NEW: 0, food.DUPLICATE: 0, food.CONFLICT: 0, food.DELETED_HERE: 0}
    samples: dict[str, list[dict[str, Any]]] = {k: [] for k in counts}
    for (number, _), (status, record) in zip(good, classified, strict=True):
        counts[status] += 1
        if len(samples[status]) < 5:
            samples[status].append({"row": number, "date": record["local_date"].isoformat(),
                                    "food": record["food_name"], "meal": record["meal_label"]})
    return {"counts": counts, "samples": samples, "errors": errors[:50], "error_count": len(errors),
            "ignored_columns": parsed["ignored"]}


@router.post("/import")
async def import_csv(request: Request, session: Session, conn: Conn) -> dict[str, Any]:
    """Save the file's new entries. Entries that differ from what's saved are replaced only if asked."""
    text, zone_name, body = await _csv_body(request)
    replace = body.get("replace_conflicts") is True
    user = session["user_id"]
    good, errors = _check_rows(_parse_csv(conn, user, text, zone_name))
    counts = food.apply_import(conn, user, [r for _, r in good], replace, datetime.now(timezone.utc)) if good else {}
    conn.commit()
    return {"counts": counts, "error_count": len(errors)}


# ---------------------------------------------------------------- barcodes

@router.get("/barcode/{code}")
def barcode_lookup(code: str, session: Session, conn: Conn) -> dict[str, Any]:
    """Your own food with this barcode, else a draft from Open Food Facts, else nothing found."""
    if not barcode.valid(code):
        raise HTTPException(status_code=422, detail="A barcode is 6 to 14 digits.")
    user = session["user_id"]
    with food.as_user(conn, user):
        mine = food.find_by_barcode(conn, user, code)
    if mine:
        return {"source": "library", "food": mine}
    try:
        product = barcode.fetch(code)
    except barcode.LookupFailed as exc:
        raise HTTPException(status_code=502, detail=f"{exc} Enter the food by hand; the barcode is kept.") from None
    if product is None:
        return {"source": "none", "barcode": code}
    return {"source": "openfoodfacts", "draft": barcode.draft(code, product)}


# ---------------------------------------------------------------- notifications

async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Send a JSON object.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Send a JSON object.")
    return body


@push_router.post("/subscribe")
async def subscribe(request: Request, session: Session, conn: Conn) -> dict[str, Any]:
    """This phone agreed to notifications. The address and keys are the browser's own subscription."""
    body = await _json(request)
    keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    try:
        db_push.save_subscription(conn, session["user_id"], body.get("endpoint"), keys.get("p256dh"), keys.get("auth"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    conn.commit()
    return {"subscribed": True}


@push_router.post("/unsubscribe")
async def unsubscribe(request: Request, session: Session, conn: Conn) -> dict[str, Any]:
    body = await _json(request)
    if isinstance(body.get("endpoint"), str):
        db_push.delete_subscription(conn, session["user_id"], body["endpoint"])
        conn.commit()
    return {"subscribed": False}


TEST_SCREENS = {"food": "/#/food", "settings": "/#/settings"}


@push_router.post("/test")
def test_notification(session: Session, conn: Conn, screen: str = "food") -> dict[str, Any]:
    """Send a notification to your own phones now, to check they arrive. Tapping it opens the screen it came from."""
    try:
        keys = push.load_vapid_keys()
    except push.PushNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    if keys is None:
        raise HTTPException(status_code=503, detail="Notifications aren't set up on the server yet.")
    delivered = notify.deliver(conn, session["user_id"], {
        "title": "Creed", "body": "Notifications work.", "url": TEST_SCREENS.get(screen, "/#/food"), "tag": "test"},
        keys)
    conn.commit()
    if not delivered:
        raise HTTPException(status_code=409, detail="No phone took the notification. Turn notifications on again.")
    return {"delivered": delivered}
