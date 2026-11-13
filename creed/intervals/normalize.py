"""Turn intervals.icu responses into the same normalized rows Garmin's become. No database or network here.

The same rules as for Garmin: nothing is imputed, a value that wasn't sent stays absent, and an impossible value is
kept but flagged. intervals.icu passes on what your watch measured, so its values are tagged with intervals.icu as
their source, never with Garmin's name.

Field names come from intervals.icu's OpenAPI document (https://intervals.icu/api/v1/docs).
"""
from __future__ import annotations

import re
from typing import Any

from creed.garmin.types import discipline_of
from creed.sync.normalize import (
    IMPOSSIBLE_SLEEP_SECONDS,
    SHORT_SLEEP_SECONDS,
    BadRecord,
    DayRecord,
    Flag,
    _checked_metric,
    _integer,
    _number,
    activity_checks,
    offset_minutes,
    parse_date,
    parse_utc,
)

# intervals.icu IDs are small numbers after an "i". Offsetting them keeps them clear of Garmin's activity IDs, which
# share the same column, while staying below 2^53 so a browser reads them exactly.
ID_OFFSET = 10**15
_ID = re.compile(r"^i(\d{1,14})$")

# metric: (wellness field, lowest possible, highest possible). The names match Garmin's, so the metrics read either.
WELLNESS_FIELDS: dict[str, tuple[str, float, float]] = {
    "resting_hr": ("restingHR", 25, 120),
    "hrv_last_night_avg": ("hrv", 5, 300),
    "steps": ("steps", 0, 150000),
    "spo2_avg": ("spO2", 50, 100),
}
WELLNESS_METRICS = tuple(WELLNESS_FIELDS)

# intervals.icu's activity types, as Garmin-style type keys, so maps, titles and indoor rules work the same way.
TYPE_KEYS = {
    "Run": "running",
    "TrailRun": "trail_running",
    "VirtualRun": "virtual_run",
    "Ride": "cycling",
    "VirtualRide": "virtual_ride",
    "GravelRide": "gravel_cycling",
    "MountainBikeRide": "mountain_biking",
    "EBikeRide": "e_bike_fitness",
    "EMountainBikeRide": "e_bike_mountain",
    "TrackRide": "track_cycling",
    "Swim": "lap_swimming",
    "OpenWaterSwim": "open_water_swimming",
    "Walk": "walking",
    "Hike": "hiking",
    "WeightTraining": "strength_training",
    "Workout": "fitness_equipment",
    "Rowing": "rowing",
    "VirtualRow": "indoor_rowing",
    "Yoga": "yoga",
}
INDOOR = {"running": "treadmill_running", "cycling": "indoor_cycling"}


class Unavailable(BadRecord):
    """intervals.icu listed the activity but won't pass its details on, as for activities that came from Strava."""


def activity_id(value: Any) -> int:
    match = _ID.match(value) if isinstance(value, str) else None
    if match is None:
        raise Unavailable(f"activity id {value!r} isn't one intervals.icu shares")
    return ID_OFFSET + int(match.group(1))


def intervals_id(stored: int) -> str:
    """The ID intervals.icu knows an activity by, from the one stored here."""
    return f"i{stored - ID_OFFSET}"


def type_key(kind: Any, trainer: bool) -> str | None:
    if not isinstance(kind, str) or not kind:
        return None
    key = TYPE_KEYS.get(kind) or re.sub(r"(?<!^)(?=[A-Z])", "_", kind).lower()
    return INDOOR.get(key, key) if trainer else key


def wellness(row: dict) -> tuple[DayRecord, dict[str, Any] | None, list[Flag]]:
    """One wellness record: the day's metrics, and the night's sleep or None. The record's id is its local date."""
    day = parse_date(row.get("id"))
    if day is None:
        raise BadRecord("wellness record without a date")
    record = DayRecord(day)
    for metric, (name, low, high) in WELLNESS_FIELDS.items():
        value = _checked_metric(metric, row.get(name), low, high, record.flags)
        if value:
            record.metrics.append(value)
    values = {m.metric: m.value_num for m in record.metrics}
    record.has_data = (values.get("resting_hr") is not None or values.get("hrv_last_night_avg") is not None
                       or values.get("spo2_avg") is not None or (values.get("steps") or 0) > 0)
    if not record.has_data:
        # A zero step count on a day nothing else was measured describes nothing. Keep the day empty.
        record.metrics, record.flags = [], []

    sleep, sleep_flags = _sleep(row, day)
    return record, sleep, sleep_flags


def _sleep(row: dict, day) -> tuple[dict[str, Any] | None, list[Flag]]:
    """intervals.icu has the night's length and score, but no stages or times, so those stay empty."""
    seconds = _integer(row.get("sleepSecs"))
    if not seconds or seconds <= 0:
        return None, []
    flags: list[Flag] = []
    quality = "ok"
    if seconds < SHORT_SLEEP_SECONDS:
        flags.append(Flag("short_record", "warning", f"Only {seconds / 3600:.1f} h recorded, likely a partial night."))
        quality = "flagged"
    if seconds > IMPOSSIBLE_SLEEP_SECONDS:
        flags.append(Flag("impossible_duration", "problem", f"{seconds / 3600:.1f} h recorded in one night."))
        quality = "flagged"
    score = _integer(row.get("sleepScore"))
    if score is not None and not 0 <= score <= 100:
        flags.append(Flag("impossible_sleep_score", "problem", f"Sleep score was {score}."))
        score = None
    respiration = _number(row.get("respiration"))
    if respiration is not None and not 4 <= respiration <= 60:
        respiration = None
    return {
        "calendar_date": day,
        "sleep_start": None,
        "sleep_end": None,
        "utc_offset_minutes": None,
        "sleep_seconds": seconds,
        "deep_seconds": None,
        "light_seconds": None,
        "rem_seconds": None,
        "awake_seconds": None,
        "unmeasurable_seconds": None,
        "nap_seconds": None,
        "score_overall": score,
        "score_qualifier": None,
        "respiration_avg": respiration,
        "respiration_low": None,
        "respiration_high": None,
        "avg_sleep_stress": None,
        "awake_count": None,
        "confirmation": None,
        "from_device": None,
        "rem_capable": None,
        "quality": quality,
    }, flags


def activity(row: dict) -> tuple[dict[str, Any], list[Flag]]:
    """One entry of the activity list. Names, notes and GPS stay in the raw record only."""
    stored_id = activity_id(row.get("id"))
    if row.get("source") == "STRAVA" or not row.get("start_date_local"):
        raise Unavailable("intervals.icu doesn't share this activity's details")
    trainer = bool(row.get("trainer"))
    key = type_key(row.get("type"), trainer)
    if key == "lap_swimming" and not row.get("pool_length"):
        key = "swimming"
    discipline = discipline_of(key)
    moving = _number(row.get("moving_time"))
    elapsed = _number(row.get("elapsed_time"))
    # Moving time is closest to a watch's timer time, which is what Garmin's duration is.
    duration = moving if moving else elapsed
    distance = _number(row.get("distance"))
    speed = _number(row.get("average_speed"))
    avg_hr = _number(row.get("average_heartrate"))
    max_hr = _number(row.get("max_heartrate"))
    flags, quality = activity_checks(discipline, duration, distance, speed, avg_hr, max_hr)

    start_utc = row.get("start_date")
    start_local = row.get("start_date_local")
    manual = row.get("source") == "MANUAL"
    return {
        "activity_id": stored_id,
        "parent_id": None,
        "is_parent": False,
        "type_key": key,
        "discipline": discipline,
        "start_time": parse_utc(start_utc),
        "local_date": parse_date(start_local),
        "utc_offset_minutes": offset_minutes(start_local, start_utc),
        "duration_seconds": duration,
        "moving_seconds": moving,
        "elapsed_seconds": elapsed,
        "distance_m": distance,
        "avg_speed_mps": speed,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        # Garmin's own training load and training effects. intervals.icu doesn't pass these on.
        "garmin_load": None,
        "aerobic_effect": None,
        "anaerobic_effect": None,
        "moderate_minutes": None,
        "vigorous_minutes": None,
        "avg_power": _number(row.get("icu_average_watts")),
        "max_power": _number(row.get("max_watts")),
        "norm_power": _number(row.get("icu_weighted_avg_watts")),
        "pool_length_m": _number(row.get("pool_length")),
        "active_lengths": _integer(row.get("lengths")),
        "strokes": None,
        "avg_swolf": None,
        "is_manual": manual,
        "quality": quality,
    }, flags
