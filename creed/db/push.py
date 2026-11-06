"""Phones that receive notifications, and the food reminders sent to them.

These run as the server's own role, not as a person: the scheduled job has to look across everyone with
reminders on. Every function that touches one person's rows still names that person.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import psycopg

from creed.db.food import _id, _not_acting

MAX_PER_PERSON = 10
ENDPOINT_LONGEST = 1000


def save_subscription(conn: psycopg.Connection, user_id: str, endpoint: Any, p256dh: Any, auth: Any) -> None:
    """Remember a phone. The same phone signing in as someone else moves to them."""
    _not_acting(conn)
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > ENDPOINT_LONGEST:
        raise ValueError("That isn't a push address.")
    if not all(isinstance(v, str) and 10 <= len(v) <= 200 for v in (p256dh, auth)):
        raise ValueError("The phone's notification keys are missing.")
    uid = _id(user_id, "User")
    conn.execute(
        "insert into push_subscription (endpoint, user_id, p256dh, auth) values (%s, %s, %s, %s) "
        "on conflict (endpoint) do update set user_id = excluded.user_id, p256dh = excluded.p256dh, "
        "auth = excluded.auth, created_at = now()",
        (endpoint, uid, p256dh, auth),
    )
    # Old phones that never said goodbye: keep the newest few.
    conn.execute(
        "delete from push_subscription where user_id = %s and endpoint not in (select endpoint from push_subscription "
        "where user_id = %s order by created_at desc limit %s)",
        (uid, uid, MAX_PER_PERSON),
    )


def delete_subscription(conn: psycopg.Connection, user_id: str, endpoint: str) -> None:
    _not_acting(conn)
    conn.execute("delete from push_subscription where user_id = %s and endpoint = %s", (_id(user_id, "User"), endpoint))


def subscriptions(conn: psycopg.Connection, user_id: str) -> list[dict[str, Any]]:
    _not_acting(conn)
    return conn.execute("select endpoint, p256dh, auth from push_subscription where user_id = %s",
                        (_id(user_id, "User"),)).fetchall()


def forget(conn: psycopg.Connection, endpoint: str) -> None:
    """The push service said this phone is gone."""
    conn.execute("delete from push_subscription where endpoint = %s", (endpoint,))


def mark_ok(conn: psycopg.Connection, endpoint: str) -> None:
    conn.execute("update push_subscription set last_ok_at = now() where endpoint = %s", (endpoint,))


def reminder_people(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Everyone with reminders on and a phone to send to, with when they last logged anything."""
    _not_acting(conn)
    return conn.execute(
        "select s.user_id, s.reminder_times, s.reminder_gap_minutes, s.timezone, "
        "(select max(e.logged_at) from food_log_entry e where e.user_id = s.user_id and e.deleted_at is null) "
        "as last_logged from food_setting s where s.reminders_on and cardinality(s.reminder_times) > 0 "
        "and exists (select 1 from push_subscription p where p.user_id = s.user_id)"
    ).fetchall()


def decided(conn: psycopg.Connection, user_id: str, since: date) -> set[tuple[date, str]]:
    rows = conn.execute("select local_date, slot from food_reminder_sent where user_id = %s and local_date >= %s",
                        (user_id, since)).fetchall()
    return {(r["local_date"], r["slot"]) for r in rows}


def record(conn: psycopg.Connection, user_id: str, local_date: date, slot: str, outcome: str) -> bool:
    """Claim a reminder slot. False if another run got there first, so it's never sent twice."""
    row = conn.execute(
        "insert into food_reminder_sent (user_id, local_date, slot, outcome) values (%s, %s, %s, %s) "
        "on conflict do nothing returning slot",
        (user_id, local_date, slot, outcome),
    ).fetchone()
    return row is not None


def set_outcome(conn: psycopg.Connection, user_id: str, local_date: date, slot: str, outcome: str) -> None:
    conn.execute("update food_reminder_sent set outcome = %s, sent_at = %s where user_id = %s and local_date = %s "
                 "and slot = %s", (outcome, datetime.now().astimezone(), user_id, local_date, slot))
