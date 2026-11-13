"""Turn Garmin responses into normalized rows, and validate them. No database or network here.

The rules:
  * Nothing is imputed. A value Garmin didn't send stays absent.
  * Garmin's "not measured" markers (negative numbers, status NONE) count as absent.
  * A value outside its possible range is kept but flagged, so metrics can leave it out
    and the Data Quality page can show why.

Field names come from the Swagger document and were confirmed against real responses.
The importer will produce these same rows from the account export.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from creed.garmin.types import discipline_of

SHORT_SLEEP_SECONDS = 3 * 3600
IMPOSSIBLE_SLEEP_SECONDS = 16 * 3600
STAGE_TOLERANCE_SECONDS = 300
LOW_WEAR_MILLIS = 6 * 3600 * 1000
VERY_SHORT_ACTIVITY_SECONDS = 60

# The longest believable speed for each discipline, in metres per second.
MAX_SPEED_MPS = {"swim": 3.0, "bike": 35.0, "run": 12.0}

# metric: (where it sits in the v2 daily summary, lowest possible, highest possible)
DAILY_FIELDS: dict[str, tuple[tuple[str, ...], float, float]] = {
    "resting_hr": (("heartRate", "restingValue"), 25, 120),
    "hr_min": (("heartRate", "minValue"), 20, 200),
    "hr_max": (("heartRate", "maxValue"), 30, 240),
    "steps": (("movement", "steps", "value"), 0, 150000),
    "step_distance_m": (("movement", "steps", "distanceInMeters"), 0, 200000),
    "floors_up": (("movement", "floorsAscended", "value"), 0, 1000),
    "intensity_moderate": (("intensityMinutes", "moderate"), 0, 1440),
    "intensity_vigorous": (("intensityMinutes", "vigorous"), 0, 1440),
    "stress_avg": (("stress", "avgLevel"), 0, 100),
    "stress_max": (("stress", "maxLevel"), 0, 100),
    "body_battery_min": (("bodyBattery", "minValue"), 0, 100),
    "body_battery_max": (("bodyBattery", "maxValue"), 0, 100),
    "body_battery_latest": (("bodyBattery", "latestValue"), 0, 100),
    "body_battery_charged": (("bodyBattery", "chargedValue"), 0, 300),
    "body_battery_drained": (("bodyBattery", "drainedValue"), 0, 300),
    "respiration_avg": (("respiration", "avgValue"), 4, 60),
    "respiration_min": (("respiration", "minValue"), 2, 60),
    "respiration_max": (("respiration", "maxValue"), 4, 80),
    "spo2_avg": (("pulseOx", "avgValue"), 50, 100),
    "spo2_min": (("pulseOx", "minValue"), 50, 100),
    "hydration_ml": (("hydration", "consumedInMl"), 0, 30000),
    "calories_total": (("calories", "burnedTotal"), 0, 30000),
    "calories_active": (("calories", "burnedActive"), 0, 30000),
}
DAILY_TEXT_FIELDS: dict[str, tuple[str, ...]] = {"stress_qualifier": ("stress", "qualifier")}

# metric: (field in an HRV summary, lowest possible, highest possible)
HRV_FIELDS: dict[str, tuple[tuple[str, ...], float, float]] = {
    "hrv_last_night_avg": (("lastNightAvg",), 5, 300),
    "hrv_5min_high": (("lastNight5MinHigh",), 5, 400),
    "hrv_weekly_avg": (("weeklyAvg",), 5, 300),
    "hrv_balanced_low": (("baseline", "balancedLow"), 5, 300),
    "hrv_balanced_high": (("baseline", "balancedUpper"), 5, 300),
    "hrv_low_upper": (("baseline", "lowUpper"), 5, 300),
}
HRV_STATUS_METRIC = "hrv_status"
NOT_MEASURED_TEXT = {"", "NONE", "INVALID", "UNDEFINED", "UNKNOWN"}

DAILY_METRICS = tuple(DAILY_FIELDS) + tuple(DAILY_TEXT_FIELDS)
HRV_METRICS = tuple(HRV_FIELDS) + (HRV_STATUS_METRIC,)


class BadRecord(ValueError):
    """A record can't be used at all, for example because it has no date."""


@dataclass(frozen=True)
class Flag:
    code: str
    severity: str  # info, warning or problem
    detail: str


@dataclass
class Metric:
    metric: str
    value_num: float | None = None
    value_text: str | None = None
    quality: str = "ok"


@dataclass
class DayRecord:
    calendar_date: date
    metrics: list[Metric] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    has_data: bool = False


def dig(row: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(row, dict):
            return None
        row = row.get(key)
    return row


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_utc(value: Any) -> datetime | None:
    """A UTC instant from epoch milliseconds, or from a string that carries no offset."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", ""))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def offset_minutes(local: Any, gmt: Any) -> int | None:
    """Local minus UTC. Both are read as if UTC, so the difference is the offset."""
    a, b = parse_utc(local), parse_utc(gmt)
    return None if a is None or b is None else round((a - b).total_seconds() / 60)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else round(number)


def _checked_metric(metric: str, value: Any, low: float, high: float, flags: list[Flag]) -> Metric | None:
    number = _number(value)
    if number is None or number < 0:  # Garmin uses negative numbers for "not measured".
        return None
    if number < low or number > high:
        flags.append(Flag(f"impossible_{metric}", "problem", f"{metric} was {number:g}, outside {low:g} to {high:g}."))
        return Metric(metric, value_num=number, quality="flagged")
    return Metric(metric, value_num=number)


def daily_summary(row: dict) -> DayRecord:
    """One row of /usersummary-service/v2/dailysummaries."""
    day = parse_date(row.get("calendarDate"))
    if day is None:
        raise BadRecord("daily summary without a calendarDate")
    record = DayRecord(day)
    for metric, (path, low, high) in DAILY_FIELDS.items():
        value = _checked_metric(metric, dig(row, *path), low, high, record.flags)
        if value:
            record.metrics.append(value)
    for metric, path in DAILY_TEXT_FIELDS.items():
        text = dig(row, *path)
        if isinstance(text, str) and text.upper() not in NOT_MEASURED_TEXT:
            record.metrics.append(Metric(metric, value_text=text))

    values = {m.metric: m.value_num for m in record.metrics}
    # Garmin can return a mostly empty row for an unworn day.
    record.has_data = values.get("resting_hr") is not None or (values.get("steps") or 0) > 0
    if not record.has_data:
        # Zeros on an unworn day, such as intensity minutes, describe nothing. Keep the day empty.
        record.metrics, record.flags = [], []
        return record
    worn = dig(row, "stress", "totalDurationInMillis")
    if isinstance(worn, (int, float)) and worn < LOW_WEAR_MILLIS:
        record.flags.append(Flag("low_wear", "info", f"Only {worn / 3600000:.1f} h of measurements that day."))
    return record


def hrv_summary(row: dict) -> DayRecord:
    """One entry of /hrv-service/hrv/daily. The date is the morning you woke up."""
    day = parse_date(row.get("calendarDate"))
    if day is None:
        raise BadRecord("HRV summary without a calendarDate")
    record = DayRecord(day)
    for metric, (path, low, high) in HRV_FIELDS.items():
        value = _checked_metric(metric, dig(row, *path), low, high, record.flags)
        if value:
            record.metrics.append(value)
    status = row.get("status")
    if isinstance(status, str) and status.upper() not in NOT_MEASURED_TEXT:
        record.metrics.append(Metric(HRV_STATUS_METRIC, value_text=status))
    record.has_data = any(m.metric == "hrv_last_night_avg" for m in record.metrics)
    return record


def sleep_night(row: dict) -> tuple[dict[str, Any], list[Flag]] | None:
    """One entry of /sleep-service/sleep/dailySleepSummariesByDate, or None if no sleep was recorded."""
    day = parse_date(row.get("calendarDate"))
    if day is None:
        raise BadRecord("sleep record without a calendarDate")
    seconds = _integer(row.get("sleepTimeSeconds"))
    if not seconds or seconds <= 0:
        return None

    start = parse_utc(row.get("sleepStartTimestampGMT"))
    end = parse_utc(row.get("sleepEndTimestampGMT"))
    offset = offset_minutes(row.get("sleepEndTimestampLocal"), row.get("sleepEndTimestampGMT"))
    deep = _integer(row.get("deepSleepSeconds"))
    light = _integer(row.get("lightSleepSeconds"))
    rem = _integer(row.get("remSleepSeconds"))
    unmeasurable = _integer(row.get("unmeasurableSleepSeconds"))

    flags: list[Flag] = []
    quality = "ok"
    if seconds < SHORT_SLEEP_SECONDS:
        flags.append(Flag("short_record", "warning", f"Only {seconds / 3600:.1f} h recorded, likely a partial night."))
        quality = "flagged"
    if seconds > IMPOSSIBLE_SLEEP_SECONDS:
        flags.append(Flag("impossible_duration", "problem", f"{seconds / 3600:.1f} h recorded in one night."))
        quality = "flagged"
    if None not in (deep, light, rem) and abs(deep + light + rem - seconds) > STAGE_TOLERANCE_SECONDS:
        flags.append(Flag("stage_mismatch", "warning", "Sleep stages don't add up to the total."))
    if unmeasurable:
        flags.append(Flag("unmeasurable_sleep", "info", f"{unmeasurable / 60:.0f} min couldn't be classified."))
    if end is not None and offset is not None:
        wake_date = parse_utc(row.get("sleepEndTimestampLocal")).date()
        if wake_date != day:
            flags.append(Flag("date_not_wake_date", "warning", f"Filed under {day}, but you woke on {wake_date}."))

    return {
        "calendar_date": day,
        "sleep_start": start,
        "sleep_end": end,
        "utc_offset_minutes": offset,
        "sleep_seconds": seconds,
        "deep_seconds": deep,
        "light_seconds": light,
        "rem_seconds": rem,
        "awake_seconds": _integer(row.get("awakeSleepSeconds")),
        "unmeasurable_seconds": unmeasurable,
        "nap_seconds": _integer(row.get("napTimeSeconds")),
        "score_overall": _integer(dig(row, "sleepScores", "overall", "value")),
        "score_qualifier": dig(row, "sleepScores", "overall", "qualifierKey"),
        "respiration_avg": _number(row.get("averageRespirationValue")),
        "respiration_low": _number(row.get("lowestRespirationValue")),
        "respiration_high": _number(row.get("highestRespirationValue")),
        "avg_sleep_stress": _number(row.get("avgSleepStress")),
        "awake_count": _integer(row.get("awakeCount")),
        "confirmation": row.get("sleepWindowConfirmationType"),
        "from_device": row.get("sleepFromDevice"),
        "rem_capable": row.get("deviceRemCapable"),
        "quality": quality,
    }, flags


def activity(row: dict) -> tuple[dict[str, Any], list[Flag]]:
    """One entry of the activity search. Names, notes and GPS stay in the raw record only."""
    activity_id = _integer(row.get("activityId"))
    if activity_id is None:
        raise BadRecord("activity without an activityId")
    type_key = dig(row, "activityType", "typeKey")
    discipline = discipline_of(type_key)
    duration = _number(row.get("duration"))
    distance = _number(row.get("distance"))
    speed = _number(row.get("averageSpeed"))
    avg_hr = _number(row.get("averageHR"))
    max_hr = _number(row.get("maxHR"))
    flags, quality = activity_checks(discipline, duration, distance, speed, avg_hr, max_hr)

    start_gmt = row.get("startTimeGMT")
    start_local = row.get("startTimeLocal")
    manual = bool(row.get("manualActivity") or row.get("isManualActivity"))
    return {
        "activity_id": activity_id,
        "parent_id": _integer(row.get("parentId")),
        "is_parent": bool(row.get("isParent") or row.get("parent")),
        "type_key": type_key,
        "discipline": discipline,
        "start_time": parse_utc(start_gmt),
        "local_date": parse_date(start_local),
        "utc_offset_minutes": offset_minutes(start_local, start_gmt),
        "duration_seconds": duration,
        "moving_seconds": _number(row.get("movingDuration")),
        "elapsed_seconds": _number(row.get("elapsedDuration")),
        "distance_m": distance,
        "avg_speed_mps": speed,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "garmin_load": _number(row.get("activityTrainingLoad")),
        "aerobic_effect": _number(row.get("aerobicTrainingEffect")),
        "anaerobic_effect": _number(row.get("anaerobicTrainingEffect")),
        "moderate_minutes": _integer(row.get("moderateIntensityMinutes")),
        "vigorous_minutes": _integer(row.get("vigorousIntensityMinutes")),
        "avg_power": _number(row.get("avgPower")),
        "max_power": _number(row.get("maxPower")),
        "norm_power": _number(row.get("normPower")),
        "pool_length_m": _number(row.get("poolLength")),
        "active_lengths": _integer(row.get("activeLengths")),
        "strokes": _number(row.get("strokes")),
        "avg_swolf": _number(row.get("averageSwolf")),
        "is_manual": manual,
        "quality": quality,
    }, flags


def activity_checks(discipline: str, duration: float | None, distance: float | None, speed: float | None,
                    avg_hr: float | None, max_hr: float | None) -> tuple[list[Flag], str]:
    """The same checks for an activity from any source. Returns its flags and its quality."""
    flags: list[Flag] = []
    quality = "ok"
    if duration is None or duration <= 0:
        flags.append(Flag("no_duration", "problem", "Activity has no duration."))
        quality = "flagged"
    elif duration < VERY_SHORT_ACTIVITY_SECONDS:
        flags.append(Flag("very_short", "info", f"Only {duration:.0f} s long."))
    for name, value in (("average HR", avg_hr), ("max HR", max_hr)):
        if value is not None and not 25 <= value <= 240:
            flags.append(Flag("impossible_hr", "problem", f"{name} was {value:g} bpm."))
            quality = "flagged"
    if avg_hr is not None and max_hr is not None and avg_hr > max_hr:
        flags.append(Flag("hr_order", "problem", f"Average HR {avg_hr:g} is above max HR {max_hr:g}."))
        quality = "flagged"
    if distance is not None and distance < 0:
        flags.append(Flag("impossible_distance", "problem", f"Distance was {distance:g} m."))
        quality = "flagged"
    limit = MAX_SPEED_MPS.get(discipline)
    if limit is not None and speed is not None and speed > limit:
        flags.append(Flag("impossible_speed", "problem", f"Average speed was {speed:.1f} m/s for a {discipline}."))
        quality = "flagged"
    return flags, quality


def fit_flags(discipline: str, fit: dict[str, Any]) -> list[Flag]:
    """Sensor problems visible in a FIT file's structure."""
    if fit.get("parse_error"):
        return [Flag("fit_unreadable", "problem", f"FIT file couldn't be read: {fit['parse_error']}")]
    flags: list[Flag] = []
    if fit.get("truncated"):
        flags.append(Flag("fit_truncated", "warning", "FIT file is shorter than its header says."))
    if not fit.get("record_count"):
        return flags
    coverage = fit.get("record_field_pct") or {}
    heart = coverage.get("heart_rate", 0)
    # Swim HR is never used for load, so a dropout there is worth noting but isn't a problem.
    if heart < 90:
        severity = "info" if discipline == "swim" else "warning"
        flags.append(Flag("hr_dropouts", severity, f"Heart rate present in {heart:.0f}% of samples."))
    speed = max(coverage.get("speed", 0), coverage.get("enhanced_speed", 0))
    if discipline in ("run", "bike") and speed < 90:
        flags.append(Flag("speed_dropouts", "warning", f"Speed present in {speed:.0f}% of samples."))
    return flags
