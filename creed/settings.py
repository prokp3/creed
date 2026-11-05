"""Settings a person can change in the app, saved in the database and validated on the way in."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from psycopg.types.json import Jsonb

from creed.metrics.base import Settings as MetricSettings

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
CURVES = ("male", "female")


class InvalidSetting(ValueError):
    """A value that can't be saved. The message is written for the person using the app."""


@dataclass(frozen=True)
class AppSettings:
    race_date: str = "2027-11-01"
    timezone: str = "Asia/Kolkata"
    max_hr: float | None = None  # None uses the estimate from your data.
    resting_hr: float | None = None  # None uses the estimate from your data.
    trimp_curve: str = "male"
    garmin_key_expires: str | None = None  # Garmin doesn't expose this, so you enter it.
    recovery_notify_time: str = "07:30"  # 24-hour here. The app shows it in 12-hour form.
    notify_recovery: bool = True
    notify_key_expiring: bool = True
    notify_sync_failed: bool = True

    def for_metrics(self) -> MetricSettings:
        return MetricSettings(
            race_date=date.fromisoformat(self.race_date),
            timezone=self.timezone,
            max_hr=self.max_hr,
            resting_hr=self.resting_hr,
            trimp_curve=self.trimp_curve,
        )


def _date(label: str, value: Any, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise InvalidSetting(f"{label} must be a date like 2027-11-01.") from None


def _heart_rate(label: str, value: Any, low: int, high: int) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise InvalidSetting(f"{label} must be between {low} and {high} bpm.")
    return float(value)


def _timezone(value: Any) -> str:
    try:
        ZoneInfo(str(value))
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidSetting("That time zone isn't recognised.") from None
    return str(value)


def _curve(value: Any) -> str:
    if value not in CURVES:
        raise InvalidSetting("Load curve must be men's or women's.")
    return value


def _clock(value: Any) -> str:
    if not isinstance(value, str) or not TIME_PATTERN.match(value):
        raise InvalidSetting("Time must look like 07:30.")
    return value


def _flag(label: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise InvalidSetting(f"{label} must be on or off.")
    return value


VALIDATORS = {
    "race_date": lambda v: _date("Race date", v),
    "timezone": _timezone,
    "max_hr": lambda v: _heart_rate("Max HR", v, 100, 240),
    "resting_hr": lambda v: _heart_rate("Resting HR", v, 25, 120),
    "trimp_curve": _curve,
    "garmin_key_expires": lambda v: _date("Key expiry", v, optional=True),
    "recovery_notify_time": _clock,
    "notify_recovery": lambda v: _flag("This notification", v),
    "notify_key_expiring": lambda v: _flag("This notification", v),
    "notify_sync_failed": lambda v: _flag("This notification", v),
}


def load(conn: psycopg.Connection) -> AppSettings:
    """Saved values over the defaults. A value saved by an older version that no longer exists is ignored."""
    rows = conn.execute("select key, value from app_setting").fetchall()
    return AppSettings(**{r["key"]: r["value"] for r in rows if r["key"] in VALIDATORS})


def save(conn: psycopg.Connection, changes: dict[str, Any]) -> AppSettings:
    """Validate first, then write, so one bad value means nothing changes."""
    unknown = sorted(set(changes) - set(VALIDATORS))
    if unknown:
        raise InvalidSetting(f"Unknown setting: {', '.join(unknown)}.")
    cleaned = {key: VALIDATORS[key](value) for key, value in changes.items()}
    merged = AppSettings(**{**asdict(load(conn)), **cleaned})
    if merged.max_hr is not None and merged.resting_hr is not None and merged.resting_hr >= merged.max_hr:
        raise InvalidSetting("Resting HR must be below max HR.")
    for key, value in cleaned.items():
        conn.execute(
            "insert into app_setting (key, value) values (%s, %s) "
            "on conflict (key) do update set value = excluded.value, updated_at = now()",
            (key, Jsonb(value)),
        )
    return merged
