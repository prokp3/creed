"""The intervals.icu endpoints the sync uses, with their responses checked for shape.

As with Garmin, a response that no longer looks as expected raises SchemaChanged rather than being read as "no data".
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from creed.garmin.api import ApiError, SchemaChanged
from creed.garmin.client import AuthFailed
from creed.intervals.client import Client, Resp

KEY_ENV_VAR = "INTERVALS_API_KEY"
ATHLETE_ENV_VAR = "INTERVALS_ATHLETE_ID"
# "0" means the athlete the key belongs to, so most people never need to set an ID.
DEFAULT_ATHLETE = "0"

__all__ = ["ApiError", "SchemaChanged", "activities", "activity_fit", "athlete_id", "resolve_api_key", "wellness"]


def resolve_api_key() -> str:
    key = os.environ.get(KEY_ENV_VAR, "").strip()
    if not key:
        raise AuthFailed(f"{KEY_ENV_VAR} isn't set. Copy your key from intervals.icu, under Settings, Developer Settings.")
    return key


def athlete_id() -> str:
    value = os.environ.get(ATHLETE_ENV_VAR, "").strip() or DEFAULT_ATHLETE
    # Their IDs look like i12345 or 12345. Anything else would end up in a URL path, so it's refused.
    if not value.removeprefix("i").isdigit():
        raise AuthFailed(f"{ATHLETE_ENV_VAR} should look like i12345, not {value!r}.")
    return value


def _json(client: Client, path: str, params: dict[str, Any]) -> Any:
    r = client.get(path, params)
    if r.status == 403:
        # A good key asking for someone else's athlete ID. Nothing will work until it's fixed, so the sync stops.
        raise AuthFailed(f"intervals.icu answered HTTP 403 for {path}. Check {ATHLETE_ENV_VAR}, or leave it unset.")
    if not r.ok:
        raise ApiError(f"{path} answered HTTP {r.status or r.error}", r.status)
    try:
        return r.json()
    except ValueError as exc:
        raise SchemaChanged(f"{path} did not answer with JSON") from exc


def _rows(body: Any, path: str, expected: tuple[str, ...]) -> list[dict]:
    if body is None:
        return []
    if not isinstance(body, list) or not all(isinstance(row, dict) for row in body):
        raise SchemaChanged(f"{path} did not answer with a list of records")
    if body and not any(key in row for row in body for key in expected):
        raise SchemaChanged(f"{path} records no longer contain any of: {', '.join(expected)}")
    return body


def wellness(client: Client, athlete: str, start: date, end: date) -> list[dict]:
    """One record per day, keyed by its local date in "id". Both ends are included."""
    path = f"/api/v1/athlete/{athlete}/wellness"
    body = _json(client, path, {"oldest": start.isoformat(), "newest": end.isoformat()})
    return _rows(body, path, ("id",))


def activities(client: Client, athlete: str, start: date, end: date) -> list[dict]:
    """Activities that started on these local days, newest first."""
    path = f"/api/v1/athlete/{athlete}/activities"
    # newest takes a date and time, so the whole of the last day is included.
    body = _json(client, path, {"oldest": start.isoformat(), "newest": f"{end.isoformat()}T23:59:59"})
    return _rows(body, path, ("id",))


def activity_fit(client: Client, activity_id: str) -> Resp:
    """intervals.icu's FIT file for an activity, whatever format the watch uploaded. Usually gzipped."""
    return client.get(f"/api/v1/activity/{activity_id}/fit-file", accept="application/octet-stream, */*")
