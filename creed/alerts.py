"""When a training notification is due, and what it says. Pure, so the rules can be checked by hand.

Six kinds, all for the person whose Garmin data this is:
  recovery      Recovery score, once a day at the time chosen in Settings, once last night's HRV has synced.
  workout       A recap when a new activity syncs.
  load_spike    This week's load jumped well above the last six weeks' (acute:chronic ratio of 1.5 or more).
  weekly        A summary of the week, on Sundays at the time chosen in Settings.
  key_expiring  The Garmin key runs out in 14, 7, 3 or 1 days, today, or has run out.
  sync_failed   Syncing keeps failing (two failures in a row, or Garmin refusing the key once).

Each one has a `ref` that makes it one notification (a date, an activity id, a week), and the database keeps which
refs went out, so nothing is sent twice. The schedule runs about every 30 minutes and can run late, so timed ones
are due for a few hours after their time rather than at one exact minute.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

TIMED_WINDOW = timedelta(hours=3)
# Only Recovery and the weekly summary, which have a time you chose, go out outside these hours.
DAY_STARTS = time(7, 0)
DAY_ENDS = time(22, 0)
# A workout that started longer ago than this is too old for a recap (also keeps the first run from sending
# a recap for every old activity).
WORKOUT_RECENT = timedelta(hours=18)
# A long workout gets a reminder about the meal after it.
MEAL_NUDGE_SECONDS = 45 * 60
KEY_STEPS = (14, 7, 3, 1, 0)

# Acute:chronic workload ratio. Here acute is the 7-day fatigue average and chronic the 42-day fitness average,
# both exponentially weighted (Williams et al. 2017, BJSM 51:209). Above about 1.5 has been linked with more
# injuries (Gabbett 2016, BJSM 50:273), though the ratio is debated (Impellizzeri et al. 2020, IJSPP 15:907),
# so the notification says "linked with", never "will".
SPIKE_RATIO = 1.5
SPIKE_MIN_HISTORY_DAYS = 42
# Below this average daily load the ratio swings wildly on a single session, so it isn't used.
SPIKE_MIN_FITNESS = 10.0
SPIKE_COOLDOWN = timedelta(days=7)

# Recovery is 50 + 25 x a z-score composite, so 50 is your own normal.
RECOVERY_ABOVE = 60
RECOVERY_BELOW = 40
RECOVERY_LOW = 34  # The same line the Today ring turns red at.

LABELS = {"run": "Run", "bike": "Bike", "swim": "Swim"}


@dataclass(frozen=True)
class Note:
    kind: str
    ref: str
    message: dict[str, str]


def _message(title: str, body: str, url: str, tag: str) -> dict[str, str]:
    return {"title": title, "body": body, "url": url, "tag": tag}


def daytime(local_now: datetime) -> bool:
    """Outside these hours only the notifications with a time you picked go out."""
    return DAY_STARTS <= local_now.time() < DAY_ENDS


def _due_at(local_now: datetime, clock: str) -> bool:
    hours, minutes = map(int, clock.split(":"))
    at = local_now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    return at <= local_now < at + TIMED_WINDOW


# ------------------------------------------------------------------ formatting

def duration(seconds: float | None) -> str:
    if not seconds:
        return "0 min"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h" if rest == 0 else f"{hours} h {rest} min"


def distance(metres: float | None, discipline: str) -> str | None:
    if not metres:
        return None
    if discipline == "swim":
        return f"{round(metres):,} m"
    return f"{metres / 1000:.1f} km"


def short_date(day: date) -> str:
    return f"{day.day} {day.strftime('%b')}"


# ------------------------------------------------------------------ recovery

def recovery(local_now: datetime, clock: str, score: float | None, confidence: str) -> Note | None:
    """Due for three hours from the chosen time, once the score exists. No score means nothing is sent:
    a guess is never shown, and Today says why it's missing."""
    if score is None or not _due_at(local_now, clock):
        return None
    value = round(score)
    if value < RECOVERY_LOW:
        body = "Well below your normal. An easier day may suit you."
    elif value < RECOVERY_BELOW:
        body = "Below your normal."
    elif value < RECOVERY_ABOVE:
        body = "Around your normal."
    else:
        body = "Above your normal."
    if confidence == "low":
        body += " Low confidence: some inputs are missing."
    return Note("recovery", local_now.date().isoformat(),
                _message(f"Recovery {value} of 100", body, "/#/in-depth", "recovery"))


# ------------------------------------------------------------------ workouts

def workout(items: Sequence[Mapping[str, Any]]) -> dict[str, str] | None:
    """One notification for every new activity in this sync. Each item has activity_id, discipline,
    duration_seconds, distance_m and load (None when it can't be worked out)."""
    if not items:
        return None
    if len(items) == 1:
        a = items[0]
        label = LABELS.get(a["discipline"], "Workout")
        parts = [duration(a["duration_seconds"])]
        if (km := distance(a["distance_m"], a["discipline"])) is not None:
            parts.append(km)
        if a.get("load") is not None:
            parts.append(f"load {round(a['load'])}")
        body = " · ".join(parts) + "."
        if (a["duration_seconds"] or 0) >= MEAL_NUDGE_SECONDS:
            body += " Remember your recovery meal."
        return _message(f"{label} synced", body, f"/#/activities/{a['activity_id']}", "workout")
    parts = [f"{LABELS.get(a['discipline'], 'Workout')} {duration(a['duration_seconds'])}" for a in items]
    loads = [a["load"] for a in items if a.get("load") is not None]
    body = " · ".join(parts) + "."
    if loads:
        body += f" Load {round(sum(loads))}."
    if sum(a["duration_seconds"] or 0 for a in items) >= MEAL_NUDGE_SECONDS:
        body += " Remember your recovery meal."
    return _message(f"{len(items)} workouts synced", body, "/#/activities", "workout")


# ------------------------------------------------------------------ load spike

def load_spike(today: date, fitness: float | None, fatigue: float | None, history_days: int,
               last_sent: datetime | None, now: datetime) -> Note | None:
    if fitness is None or fatigue is None or history_days < SPIKE_MIN_HISTORY_DAYS or fitness < SPIKE_MIN_FITNESS:
        return None
    ratio = fatigue / fitness
    if ratio < SPIKE_RATIO or (last_sent is not None and now - last_sent < SPIKE_COOLDOWN):
        return None
    body = (f"Your load over the last week is {ratio:.1f}× your six-week average. Jumps this big are linked with more "
            "injuries, so an easier day or two may help.")
    return Note("load_spike", today.isoformat(), _message("Load spike", body, "/#/in-depth", "load-spike"))


# ------------------------------------------------------------------ weekly summary

def weekly_due(local_now: datetime, clock: str) -> date | None:
    """The Monday that starts the week being summed up, on Sundays from the chosen time for three hours."""
    if local_now.weekday() != 6 or not _due_at(local_now, clock):
        return None
    return local_now.date() - timedelta(days=6)


def weekly(week_start: date, this_week: Mapping[str, Any], last_week_load: float | None,
           days_to_race: int | None, food: Mapping[str, Any] | None) -> Note:
    """this_week has seconds per discipline and total_load. food has logged_days, kcal and protein (averages
    over logged days only, since a day with nothing logged is unknown, not a day of eating nothing)."""
    seconds = this_week.get("seconds", {})
    done = [f"{LABELS[d]} {duration(seconds[d])}" for d in ("run", "bike", "swim") if seconds.get(d)]
    sentences = [" · ".join(done) + "." if done else "No run, bike or swim this week."]
    total = this_week.get("total_load") or 0
    if total:
        load = f"Load {round(total)}"
        if last_week_load:
            change = round((total - last_week_load) / last_week_load * 100)
            load += (f", up {change}% on last week" if change > 0 else
                     f", down {-change}% on last week" if change < 0 else ", the same as last week")
        sentences.append(load + ".")
    if food and food.get("logged_days"):
        days = food["logged_days"]
        bits = []
        if food.get("kcal") is not None:
            bits.append(f"{round(food['kcal']):,} kcal")
        if food.get("protein") is not None:
            bits.append(f"{round(food['protein'])} g protein")
        if bits:
            sentences.append(f"Food: {' and '.join(bits)} a day over {days} logged day{'s' if days != 1 else ''}.")
    if days_to_race is not None and days_to_race >= 0:
        sentences.append(f"{days_to_race} day{'s' if days_to_race != 1 else ''} to race day.")
    return Note("weekly", week_start.isoformat(),
                _message("Your week", " ".join(sentences), "/#/in-depth", "weekly"))


# ------------------------------------------------------------------ Garmin key

def key_expiring(expires: date | None, today: date) -> Note | None:
    """Once at each step as the date gets close. Setting the date late sends the step you're in, once."""
    if expires is None:
        return None
    left = (expires - today).days
    if left > KEY_STEPS[0]:
        return None
    if left < 0:
        ref, body = f"{expires.isoformat()}:expired", (
            f"Your Garmin key expired on {short_date(expires)}, so syncing has stopped. Make a new key and "
            "replace GARMIN_PERSONAL_API_KEY in Vercel.")
    else:
        step = min(s for s in KEY_STEPS if s >= left)
        when = "today" if left == 0 else "tomorrow" if left == 1 else f"in {left} days ({short_date(expires)})"
        ref, body = f"{expires.isoformat()}:{step}", (
            f"Your Garmin key expires {when}. Make a new one and replace GARMIN_PERSONAL_API_KEY in Vercel, "
            "then update the date in Settings.")
    return Note("key_expiring", ref, _message("Garmin key", body, "/#/settings", "garmin-key"))


# ------------------------------------------------------------------ sync failed

FAILED = ("failed", "auth_failed")


def sync_failed(runs: Sequence[Mapping[str, Any]], last_good: datetime | None, timezone: Any) -> Note | None:
    """runs are finished syncs, newest first. One notification per run of failures, named by its first run.
    The error text isn't included: it stays in the app."""
    streak = []
    for run in runs:
        if run["status"] not in FAILED:
            break
        streak.append(run)
    if not streak or (streak[0]["status"] != "auth_failed" and len(streak) < 2):
        return None
    if streak[0]["status"] == "auth_failed":
        body = "Garmin refused the key, so syncing has stopped until it's fixed."
    else:
        body = f"The last {len(streak)} syncs failed."
    if last_good is not None:
        local = last_good.astimezone(timezone)
        hour = local.strftime("%I:%M %p").lstrip("0")
        body += f" Last good sync: {short_date(local.date())}, {hour}."
    return Note("sync_failed", str(streak[-1]["id"]), _message("Sync failed", body, "/#/today", "sync-failed"))
