"""Sending food reminders, called from the scheduled job. Each reminder slot is claimed in the database before
anything is sent, so two runs at once can't both send it."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from creed import push
from creed.db import push as db_push
from creed.food import reminders

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
