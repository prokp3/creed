"""The home screen widget's key. A widget can't sign in with a passkey, so it sends this key instead.

The key only reads today's food totals against targets: it can't change anything or see meals, Garmin data or
settings. Only its hash is stored, and turning the widget off in Settings deletes it.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

import psycopg

KEY_PREFIX = "creed_w_"


def _hash(key: str) -> bytes:
    return hashlib.sha256(key.encode()).digest()


def new_key(conn: psycopg.Connection, user_id: str) -> str:
    """Make a key for this person, replacing any they had. The key itself is shown once and never stored."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    conn.execute(
        "insert into widget_key (user_id, key_hash) values (%s, %s) "
        "on conflict (user_id) do update set key_hash = excluded.key_hash, created_at = now(), last_used_at = null",
        (user_id, _hash(key)),
    )
    conn.commit()
    return key


def remove_key(conn: psycopg.Connection, user_id: str) -> None:
    conn.execute("delete from widget_key where user_id = %s", (user_id,))
    conn.commit()


def status(conn: psycopg.Connection, user_id: str) -> dict[str, Any]:
    row = conn.execute(
        "select created_at, last_used_at from widget_key where user_id = %s", (user_id,)
    ).fetchone()
    if row is None:
        return {"on": False, "created_at": None, "last_used_at": None}
    return {"on": True, "created_at": row["created_at"].isoformat(),
            "last_used_at": row["last_used_at"].isoformat() if row["last_used_at"] else None}


def user_for_key(conn: psycopg.Connection, key: str | None) -> dict[str, Any] | None:
    """Whose key this is, or None. Notes when it was last used, so Settings can show the widget is working."""
    if not key or not key.startswith(KEY_PREFIX):
        return None
    row = conn.execute(
        "update widget_key k set last_used_at = now() from app_user u "
        "where k.key_hash = %s and u.id = k.user_id returning k.user_id::text as user_id, u.is_owner",
        (_hash(key),),
    ).fetchone()
    conn.commit()
    return row
