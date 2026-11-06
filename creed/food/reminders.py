"""When a food reminder is due. Pure, so the rules can be checked by hand.

A reminder is a local clock time. The schedule that checks runs about every 30 minutes and can run late, so a
reminder counts as due for an hour after its time, and is decided once: sent, or skipped because something was
logged recently. It never goes out twice for the same time on the same day.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from creed.food.nutrition import InvalidFood

WINDOW = timedelta(minutes=60)
MAX_TIMES = 8
CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def clean_times(values: object) -> list[str]:
    """Up to eight distinct HH:MM times, in order."""
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise InvalidFood("Reminder times must be a list like 13:30.")
    times = sorted({v.strip() for v in values})
    if len(times) > MAX_TIMES:
        raise InvalidFood(f"Up to {MAX_TIMES} reminder times.")
    for value in times:
        if not CLOCK.match(value):
            raise InvalidFood(f"{value} isn't a time like 13:30.")
    return times


def zone(name: object) -> ZoneInfo:
    if not isinstance(name, str):
        raise InvalidFood("Unknown time zone.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidFood("Unknown time zone.") from None


@dataclass(frozen=True)
class Decision:
    slot: str
    local_date: date
    outcome: str  # "send" or "skip"


def decide(now: datetime, *, times: Sequence[str], timezone: str, gap_minutes: int,
           last_logged: datetime | None, already: Iterable[tuple[date, str]]) -> list[Decision]:
    """The reminders to act on now. `already` holds (local date, slot) pairs decided before."""
    local_now = now.astimezone(zone(timezone))
    done = set(already)
    decisions = []
    for slot in times:
        hours, minutes = map(int, slot.split(":"))
        # Today's slot, or yesterday's if it was late last night and its hour hasn't passed.
        for day in (local_now.date(), local_now.date() - timedelta(days=1)):
            at = datetime(day.year, day.month, day.day, hours, minutes, tzinfo=local_now.tzinfo)
            if at <= local_now < at + WINDOW and (day, slot) not in done:
                recent = last_logged is not None and now - last_logged < timedelta(minutes=gap_minutes)
                decisions.append(Decision(slot, day, "skip" if recent else "send"))
                break
    return decisions


def message(last_logged: datetime | None, timezone: str, now: datetime) -> dict[str, str]:
    """What the notification says. It names no food or amount: lock screens are seen by others."""
    if last_logged is None or last_logged.astimezone(zone(timezone)).date() != now.astimezone(zone(timezone)).date():
        body = "Nothing logged yet today. Tap to log what you've eaten."
    else:
        hours = int((now - last_logged).total_seconds() // 3600)
        body = f"Nothing logged for {hours} hours. Tap to log what you've eaten."
    return {"title": "Food", "body": body, "url": "/#/food", "tag": "food-reminder"}
