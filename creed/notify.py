"""Sending notifications from the scheduled job: food reminders, and the training notifications decided in
creed/alerts.py. Each one is claimed in the database before anything is sent, so two runs at once can't both send
it, and none goes out twice."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from creed import alerts, auth, config, push
from creed import settings as app_settings
from creed.db import food, reads
from creed.db import push as db_push
from creed.food import reminders
from creed.food import trends as food_trends
from creed.metrics import fitness, hr_params, recovery, strain, weekly
from creed.metrics.base import OK, MetricContext

Sender = Callable[[dict[str, Any], dict[str, Any], push.VapidKeys], str]


def deliver(conn: psycopg.Connection, user_id: str, message: dict[str, Any], keys: push.VapidKeys,
            sender: Sender = push.send) -> int:
    """Send to every phone this person turned notifications on for. Returns how many took it."""
    delivered = 0
    for subscription in db_push.subscriptions(conn, user_id):
        outcome = sender(subscription, message, keys)
        if outcome == push.SENT:
            delivered += 1
            db_push.mark_ok(conn, subscription["endpoint"])
        elif outcome == push.GONE:
            db_push.forget(conn, subscription["endpoint"])
    return delivered


def send_food_reminders(conn: psycopg.Connection, now: datetime | None = None, keys: push.VapidKeys | None = None,
                        sender: Sender = push.send) -> dict[str, Any]:
    """Every reminder due now. Returns counts only, since the scheduled job's log is public."""
    keys = keys or push.load_vapid_keys()
    if keys is None:
        return {"status": "not_configured"}
    now = now or datetime.now(timezone.utc)
    counts = {"status": "ok", "sent": 0, "skipped": 0, "failed": 0}
    for person in db_push.reminder_people(conn):
        user_id = str(person["user_id"])
        try:
            reminders.zone(person["timezone"])
        except ValueError:
            continue
        since = now.date() - timedelta(days=2)
        due = reminders.decide(now, times=person["reminder_times"], timezone=person["timezone"],
                               gap_minutes=person["reminder_gap_minutes"], last_logged=person["last_logged"],
                               already=db_push.decided(conn, user_id, since))
        for decision in due:
            outcome = "skipped" if decision.outcome == "skip" else "sent"
            if not db_push.record(conn, user_id, decision.local_date, decision.slot, outcome):
                continue
            if outcome == "skipped":
                counts["skipped"] += 1
                continue
            message = reminders.message(person["last_logged"], person["timezone"], now)
            if deliver(conn, user_id, message, keys, sender):
                counts["sent"] += 1
            else:
                db_push.set_outcome(conn, user_id, decision.local_date, decision.slot, "failed")
                counts["failed"] += 1
        conn.commit()
    return counts


# ---------------------------------------------------------------- training notifications

# A Sync now in the app shows these on screen, so they're marked seen rather than sent a few minutes later.
SEEN_IN_APP = ("recovery", "workout")
COUNTED = ("recovery", "workout", "load_spike", "weekly", "key_expiring", "sync_failed")


def _new_workouts(conn: psycopg.Connection, owner: str, ctx: MetricContext, now: datetime) -> list[dict[str, Any]]:
    """Activities that started recently and haven't had a recap, with their load where it can be worked out."""
    rows = reads.activities_started_since(conn, now - alerts.WORKOUT_RECENT)
    done = db_push.claimed(conn, owner, "workout", [str(r["activity_id"]) for r in rows])
    params = hr_params.estimate(ctx)
    threshold = strain.swim_threshold_speed(ctx.activities)
    records = {a.activity_id: a for a in ctx.activities}
    items = []
    for r in rows:
        if str(r["activity_id"]) in done:
            continue
        record = records.get(r["activity_id"])
        load = None
        if record is not None and not record.flagged:
            load, _ = strain.activity_load(record, params, threshold, ctx.settings.trimp_curve)
        items.append({"activity_id": r["activity_id"], "discipline": r["discipline"],
                      "duration_seconds": r["duration_seconds"], "distance_m": r["distance_m"], "load": load})
    return items


def _food_week(conn: psycopg.Connection, owner: str, start: date, end: date) -> dict[str, Any]:
    """Average calories and protein over the days with anything logged."""
    threshold = food.get_settings(conn, owner)["training_minutes"]
    kinds = food.day_types(conn, owner, start, end, threshold)
    with food.as_user(conn, owner):
        result = food_trends.trends(
            start=start, end=end, entries=food.entries_between(conn, owner, start, end),
            nutrients=food.list_nutrients(conn, owner), day_types=kinds, target_sets=food.target_sets(conn, owner),
            burned={})
    averages = result["averages"]
    return {"logged_days": result["logged_days"], "kcal": averages.get("kcal", {}).get("eaten"),
            "protein": averages.get("protein", {}).get("eaten")}


def _weekly_note(conn: psycopg.Connection, owner: str, ctx: MetricContext, saved: app_settings.AppSettings,
                 start: date) -> alerts.Note:
    weeks = weekly.compute(ctx).details.get("weeks", [])
    by_start = {w["week_start"]: w for w in weeks}
    this_week = by_start.get(start.isoformat())
    last_week = by_start.get((start - timedelta(days=7)).isoformat())
    summary: dict[str, Any] = {"seconds": {}, "total_load": 0.0}
    if this_week:
        summary = {"seconds": {d: t["seconds"] for d, t in this_week["disciplines"].items()},
                   "total_load": this_week["total_load"]}
    days_to_race = (date.fromisoformat(saved.race_date) - ctx.today).days
    return alerts.weekly(start, summary, last_week["total_load"] if last_week else None, days_to_race,
                         _food_week(conn, owner, start, ctx.today))


def due_training_notes(conn: psycopg.Connection, owner: str, now: datetime,
                       kinds: tuple[str, ...] = COUNTED) -> tuple[list[alerts.Note], list[dict[str, Any]]]:
    """What's due now, as notes, plus new workouts (handled apart, since one recap covers several)."""
    saved = app_settings.load(conn)
    tz = ZoneInfo(saved.timezone)
    local = now.astimezone(tz)
    ctx = reads.load_context(conn, local.date(), saved.for_metrics(), now)
    daytime = alerts.daytime(local)
    seen_only = kinds == SEEN_IN_APP
    notes: list[alerts.Note | None] = []
    workouts: list[dict[str, Any]] = []

    if "recovery" in kinds and saved.notify_recovery:
        result = recovery.compute(ctx)
        notes.append(alerts.recovery(local, saved.recovery_notify_time,
                                     result.value if result.state == OK else None, result.confidence))
    if "workout" in kinds and saved.notify_workout and (daytime or seen_only):
        workouts = _new_workouts(conn, owner, ctx, now)
    if "load_spike" in kinds and saved.notify_load_spike and daytime:
        totals = {day: sum(d.values()) for day, d in strain.daily_loads(ctx).items()}
        rows = fitness.series(totals, ctx.today)
        if rows:
            notes.append(alerts.load_spike(ctx.today, rows[-1].fitness, rows[-1].fatigue, len(rows),
                                           db_push.last_notification(conn, owner, "load_spike"), now))
    if "weekly" in kinds and saved.notify_weekly:
        start = alerts.weekly_due(local, saved.weekly_notify_time)
        if start is not None and not db_push.claimed(conn, owner, "weekly", [start.isoformat()]):
            notes.append(_weekly_note(conn, owner, ctx, saved, start))
    # intervals.icu keys never run out, so only a Garmin key is watched.
    if "key_expiring" in kinds and saved.notify_key_expiring and daytime and config.data_source() == config.GARMIN:
        expires = date.fromisoformat(saved.garmin_key_expires) if saved.garmin_key_expires else None
        notes.append(alerts.key_expiring(expires, ctx.today))
    if "sync_failed" in kinds and saved.notify_sync_failed and daytime:
        notes.append(alerts.sync_failed(reads.finished_runs(conn), reads.last_good_run(conn), tz,
                                        config.source_label()))
    return [n for n in notes if n is not None], workouts


def send_training_notifications(conn: psycopg.Connection, now: datetime | None = None,
                                keys: push.VapidKeys | None = None, sender: Sender = push.send,
                                trigger: str = "cron") -> dict[str, Any]:
    """Send whatever is due to the owner's phones. After a Sync now (trigger "manual") nothing is sent: what the
    app just showed is marked seen instead. Returns counts only, since the scheduled job's log is public."""
    manual = trigger == "manual"
    if not manual:
        keys = keys or push.load_vapid_keys()
        if keys is None:
            return {"status": "not_configured"}
    owner = auth.owner_id(conn)
    if owner is None or not db_push.has_phone(conn, owner):
        return {"status": "no_phone"}
    now = now or datetime.now(timezone.utc)
    notes, workouts = due_training_notes(conn, owner, now, SEEN_IN_APP if manual else COUNTED)
    counts = {"status": "ok", "sent": 0, "seen": 0, "failed": 0}

    if manual:
        for note in notes:
            counts["seen"] += db_push.claim(conn, owner, note.kind, note.ref, "seen")
        for item in workouts:
            counts["seen"] += db_push.claim(conn, owner, "workout", str(item["activity_id"]), "seen")
        conn.commit()
        return counts

    batches: list[tuple[str, list[str], dict[str, str]]] = []
    for note in notes:
        if db_push.claim(conn, owner, note.kind, note.ref, "sent"):
            batches.append((note.kind, [note.ref], note.message))
    mine = [w for w in workouts if db_push.claim(conn, owner, "workout", str(w["activity_id"]), "sent")]
    if mine:
        batches.append(("workout", [str(w["activity_id"]) for w in mine], alerts.workout(mine)))
    conn.commit()

    for kind, refs, message in batches:
        if deliver(conn, owner, message, keys, sender):
            counts["sent"] += 1
        else:
            for ref in refs:
                db_push.set_notification_outcome(conn, owner, kind, ref, "failed")
            counts["failed"] += 1
        conn.commit()
    return counts
