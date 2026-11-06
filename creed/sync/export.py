"""Import Garmin's account export: the zip you get from Garmin's "Export Your Data" request.

Each record is reshaped into what the Personal API returns and then goes through the same checks in normalize.py,
so the export can't get a softer validation than the API. Rows are stored with source "export". Where the API
has the same day, the API's value wins in every screen; the export fills in what the API doesn't have. Running it
again changes nothing.

What's read:
  * Daily summaries: DI_CONNECT/DI-Connect-Aggregator/UDSFile_*.json
  * Sleep: DI_CONNECT/DI-Connect-Wellness/*_sleepData.json
  * Overnight HRV: HRV Status FIT files in DI-Connect-Uploaded-Files/*.zip (message 370, hrv_status_summary).
    Checked against the API on a real account: 200 of 200 overlapping nights matched.
Activities aren't imported: the export's activities match the API's. Any that don't are counted in the report.

Run it with `python -m creed.sync.export`. It reads the newest zip in exports/ unless given a path.
"""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from creed.db.store import Batch, Store
from creed.garmin.fit import MAX_FIT_BYTES, read_messages
from creed.sync import normalize
from creed.sync.normalize import BadRecord

SOURCE = "export"
EXPORT_DIR = Path("exports")
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
MAX_ENTRY_BYTES = 512 * 1024 * 1024  # A guard against a damaged or hostile zip claiming an enormous file.

FIT_MSG_HRV_STATUS_SUMMARY = 370
HRV_SCALE = 128  # The FIT profile stores these in 1/128 ms.
# field number: where it goes in the API's HRV summary. Matched against the API on a real account.
HRV_FIELDS = {0: ("weeklyAvg",), 1: ("lastNightAvg",), 2: ("lastNight5MinHigh",),
              3: ("baseline", "lowUpper"), 4: ("baseline", "balancedLow"), 5: ("baseline", "balancedUpper")}
HRV_STATUS_FIELD = 6
# 2, 3 and 4 were confirmed against the API's statuses. 1 is the FIT profile's "poor", not yet seen on a real account.
HRV_STATUS_NAMES = {0: "NONE", 1: "POOR", 2: "LOW", 3: "UNBALANCED", 4: "BALANCED"}

DAILY_FILE = re.compile(r"DI-Connect-Aggregator/UDSFile_[^/]*\.json$")
SLEEP_FILE = re.compile(r"DI-Connect-Wellness/[^/]*_sleepData\.json$")
ACTIVITY_FILE = re.compile(r"DI-Connect-Fitness/[^/]*summarizedActivities\.json$")
UPLOADED_FILES = re.compile(r"DI-Connect-Uploaded-Files/[^/]*\.zip$")

# Flags get their own scopes, so the export never overwrites what the API reported about the same day.
SCOPES = {"daily": "export_daily", "sleep": "export_sleep", "hrv": "export_hrv"}


class ExportError(Exception):
    """The file isn't a readable Garmin export. The message is safe to show."""


@dataclass
class Report:
    """What an import found. Counts only, never values."""

    days: dict[str, int] = field(default_factory=dict)
    added: dict[str, int] = field(default_factory=dict)
    unreadable: dict[str, int] = field(default_factory=dict)
    flagged: dict[str, int] = field(default_factory=dict)
    first_day: dict[str, date] = field(default_factory=dict)
    activities_only_in_export: int = 0

    def lines(self) -> list[str]:
        names = {"daily": "Daily summaries", "sleep": "Sleep", "hrv": "Overnight HRV"}
        out = []
        for kind, name in names.items():
            if kind not in self.days:
                continue
            line = f"{name}: {self.days[kind]} days read, {self.added.get(kind, 0)} not already from the API"
            if kind in self.first_day:
                line += f", from {self.first_day[kind]}"
            extras = [f"{n} {label}" for label, n in (("unreadable", self.unreadable.get(kind, 0)),
                                                      ("flagged", self.flagged.get(kind, 0))) if n]
            out.append(line + (f" ({', '.join(extras)})" if extras else "") + ".")
        if self.activities_only_in_export:
            out.append(f"Activities: {self.activities_only_in_export} are only in the export and weren't imported.")
        else:
            out.append("Activities: nothing new; the API already has every one.")
        return out


# -- reshaping export records into API records -------------------------------


def _stat(stats: list[dict], kind: str) -> Any:
    return next((s.get("statsValue") for s in stats if s.get("bodyBatteryStatType") == kind), None)


def daily_as_api(row: dict) -> dict:
    """A UDSFile day in the shape of /usersummary-service/v2/dailysummaries."""
    stress = next((x for x in (row.get("allDayStress") or {}).get("aggregatorList", []) if x.get("type") == "TOTAL"), {})
    battery = row.get("bodyBattery") or {}
    stats = battery.get("bodyBatteryStatList") or []
    breathing = row.get("respiration") or {}
    worn_seconds = stress.get("totalDuration")
    return {
        "calendarDate": row.get("calendarDate"),
        # Matched against the API on a real account: these, not restingHeartRate, minHeartRate or maxHeartRate.
        "heartRate": {"restingValue": row.get("currentDayRestingHeartRate"), "minValue": row.get("minAvgHeartRate"),
                      "maxValue": row.get("maxAvgHeartRate")},
        "movement": {"steps": {"value": row.get("totalSteps"), "distanceInMeters": row.get("totalDistanceMeters")}},
        "intensityMinutes": {"moderate": row.get("moderateIntensityMinutes"),
                             "vigorous": row.get("vigorousIntensityMinutes")},
        "stress": {"avgLevel": stress.get("averageStressLevel"), "maxLevel": stress.get("maxStressLevel"),
                   # The export counts seconds where the API counts milliseconds.
                   "totalDurationInMillis": worn_seconds * 1000 if isinstance(worn_seconds, (int, float)) else None},
        "bodyBattery": {"minValue": _stat(stats, "LOWEST"), "maxValue": _stat(stats, "HIGHEST"),
                        "latestValue": _stat(stats, "MOSTRECENT"), "chargedValue": battery.get("chargedValue"),
                        "drainedValue": battery.get("drainedValue")},
        "respiration": {"avgValue": breathing.get("avgWakingRespirationValue"),
                        "minValue": breathing.get("lowestRespirationValue"),
                        "maxValue": breathing.get("highestRespirationValue")},
        "hydration": {"consumedInMl": (row.get("hydration") or {}).get("valueInML")},
        "calories": {"burnedTotal": row.get("totalKilocalories"), "burnedActive": row.get("activeKilocalories")},
    }


def _local_offsets(daily_rows: list[dict]) -> dict[str, timedelta]:
    """Each day's offset from UTC, from the daily summary's own local and UTC times."""
    offsets = {}
    for row in daily_rows:
        local, utc = row.get("wellnessStartTimeLocal"), row.get("wellnessStartTimeGmt")
        try:
            offsets[row["calendarDate"]] = datetime.fromisoformat(local) - datetime.fromisoformat(utc)
        except (KeyError, TypeError, ValueError):
            continue
    return offsets


def sleep_as_api(row: dict, offset: timedelta | None) -> dict:
    """A sleepData night in the shape of /sleep-service/sleep/dailySleepSummariesByDate."""
    stages = [row.get(k) for k in ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds")]
    # The export has no total. The API's total is these three stages added up; a missing stage means no total.
    total = sum(stages) if all(isinstance(s, (int, float)) for s in stages) else None
    end_local = None
    if offset is not None and row.get("sleepEndTimestampGMT"):
        try:
            end_local = (datetime.fromisoformat(row["sleepEndTimestampGMT"]) + offset).isoformat()
        except ValueError:
            end_local = None
    scores = row.get("sleepScores") or {}
    return {
        "calendarDate": row.get("calendarDate"),
        "sleepTimeSeconds": total,
        "sleepStartTimestampGMT": row.get("sleepStartTimestampGMT"),
        "sleepEndTimestampGMT": row.get("sleepEndTimestampGMT"),
        "sleepEndTimestampLocal": end_local,
        "deepSleepSeconds": row.get("deepSleepSeconds"),
        "lightSleepSeconds": row.get("lightSleepSeconds"),
        "remSleepSeconds": row.get("remSleepSeconds"),
        "awakeSleepSeconds": row.get("awakeSleepSeconds"),
        "unmeasurableSleepSeconds": row.get("unmeasurableSeconds"),
        "sleepScores": {"overall": {"value": scores.get("overallScore")}},
        "averageRespirationValue": row.get("averageRespiration"),
        "lowestRespirationValue": row.get("lowestRespiration"),
        "highestRespirationValue": row.get("highestRespiration"),
        "avgSleepStress": row.get("avgSleepStress"),
        "awakeCount": row.get("awakeCount"),
        "sleepWindowConfirmationType": row.get("sleepWindowConfirmationType"),
    }


def hrv_as_api(message: dict[int, int], zone: ZoneInfo) -> dict | None:
    """An HRV Status FIT summary in the shape of /hrv-service/hrv/daily. It belongs to the local morning."""
    if 253 not in message:
        return None
    day = (FIT_EPOCH + timedelta(seconds=message[253])).astimezone(zone).date()
    row: dict[str, Any] = {"calendarDate": day.isoformat(), "baseline": {}}
    for number, path in HRV_FIELDS.items():
        if number in message:
            target = row if len(path) == 1 else row["baseline"]
            target[path[-1]] = message[number] / HRV_SCALE
    row["status"] = HRV_STATUS_NAMES.get(message.get(HRV_STATUS_FIELD))
    return row


# -- reading the zip ---------------------------------------------------------


def _entries(archive: zipfile.ZipFile, pattern: re.Pattern) -> Iterator[zipfile.ZipInfo]:
    for info in archive.infolist():
        if pattern.search(info.filename) and info.file_size <= MAX_ENTRY_BYTES:
            yield info


def _json_rows(archive: zipfile.ZipFile, pattern: re.Pattern, report: Report, kind: str) -> list[dict]:
    rows: list[dict] = []
    for info in _entries(archive, pattern):
        try:
            data = json.loads(archive.read(info))
        except (json.JSONDecodeError, UnicodeDecodeError):
            report.unreadable[kind] = report.unreadable.get(kind, 0) + 1
            continue
        rows.extend(r for r in (data if isinstance(data, list) else [data]) if isinstance(r, dict))
    return rows


def _hrv_messages(archive: zipfile.ZipFile, report: Report) -> list[dict[int, int]]:
    found: list[dict[int, int]] = []
    for info in _entries(archive, UPLOADED_FILES):
        with zipfile.ZipFile(io.BytesIO(archive.read(info))) as inner:
            for item in inner.infolist():
                if not item.filename.lower().endswith(".fit") or item.file_size > MAX_FIT_BYTES:
                    continue
                messages, problem = read_messages(inner.read(item), FIT_MSG_HRV_STATUS_SUMMARY)
                found.extend(messages)
                if problem and messages:
                    report.unreadable["hrv"] = report.unreadable.get("hrv", 0) + 1
    return found


def _activity_ids(archive: zipfile.ZipFile) -> set[int]:
    ids: set[int] = set()
    for info in _entries(archive, ACTIVITY_FILE):
        try:
            data = json.loads(archive.read(info))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for block in data if isinstance(data, list) else [data]:
            for item in (block.get("summarizedActivitiesExport") or []) if isinstance(block, dict) else []:
                if isinstance(item, dict) and isinstance(item.get("activityId"), int):
                    ids.add(item["activityId"])
    return ids


# -- importing ---------------------------------------------------------------


def _api_days(store: Store, metric: str | None, table: str = "daily_metric") -> set[date]:
    if table == "sleep_night":
        rows = store.conn.execute("select calendar_date from sleep_night where source = 'api'").fetchall()
    else:
        rows = store.conn.execute(
            "select distinct calendar_date from daily_metric where source = 'api' and metric = %s", (metric,)
        ).fetchall()
    return {row["calendar_date"] for row in rows}


def _load(store: Store, report: Report, kind: str, rows: list[dict], parse: Callable[[Batch, dict], date | None],
          already: set[date], key: str) -> None:
    batch = Batch()
    days: set[date] = set()
    for row in rows:
        try:
            day = parse(batch, row)
        except (BadRecord, TypeError, ValueError, AttributeError, KeyError):
            report.unreadable[kind] = report.unreadable.get(kind, 0) + 1
            continue
        if day is not None:
            days.add(day)
    report.days[kind] = len(days)
    report.added[kind] = len(days - already)
    report.flagged[kind] = sum(1 for flags in batch.flags.get(SCOPES[kind], {}).values()
                               if any(f.severity != "info" for f in flags))
    if days:
        report.first_day[kind] = min(days)
    store.write_batch(batch, SOURCE)
    store.commit()


def import_export(store: Store, path: Path, tz_name: str, progress: Callable[[str], None] = lambda _m: None) -> Report:
    """Read one export zip into the database. Safe to run again: it replaces its own rows and nothing else."""
    report = Report()
    zone = ZoneInfo(tz_name)
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError) as exc:
        raise ExportError(f"Couldn't open {path.name} as a zip: {type(exc).__name__}.") from None
    with archive:
        if not any(DAILY_FILE.search(i.filename) or SLEEP_FILE.search(i.filename) for i in archive.infolist()):
            raise ExportError("This zip doesn't look like a Garmin account export: no daily summaries or sleep found.")

        progress("Reading daily summaries...")
        daily_rows = _json_rows(archive, DAILY_FILE, report, "daily")

        def parse_daily(batch: Batch, row: dict) -> date | None:
            record = normalize.daily_summary(daily_as_api(row))
            key = record.calendar_date.isoformat()
            if record.metrics:
                batch.raw[("export_daily", key)] = row
            batch.add_metrics(record.calendar_date, normalize.DAILY_METRICS, record.metrics)
            batch.add_flags(SCOPES["daily"], key, record.flags)
            return record.calendar_date if record.has_data else None

        _load(store, report, "daily", daily_rows, parse_daily, _api_days(store, "resting_hr"), "daily")

        progress("Reading sleep...")
        offsets = _local_offsets(daily_rows)

        def parse_sleep(batch: Batch, row: dict) -> date | None:
            parsed = normalize.sleep_night(sleep_as_api(row, offsets.get(row.get("calendarDate"))))
            if parsed is None:
                return None
            values, flags = parsed
            key = values["calendar_date"].isoformat()
            batch.raw[("export_sleep", key)] = row
            batch.sleep[values["calendar_date"]] = values
            batch.add_flags(SCOPES["sleep"], key, flags)
            return values["calendar_date"]

        _load(store, report, "sleep", _json_rows(archive, SLEEP_FILE, report, "sleep"), parse_sleep,
              _api_days(store, None, "sleep_night"), "sleep")

        progress("Reading overnight HRV from the watch's files (this is the slow part)...")
        hrv_rows = [row for message in _hrv_messages(archive, report) if (row := hrv_as_api(message, zone))]

        def parse_hrv(batch: Batch, row: dict) -> date | None:
            record = normalize.hrv_summary(row)
            key = record.calendar_date.isoformat()
            batch.add_metrics(record.calendar_date, normalize.HRV_METRICS, record.metrics)
            batch.add_flags(SCOPES["hrv"], key, record.flags)
            return record.calendar_date if record.has_data else None

        _load(store, report, "hrv", hrv_rows, parse_hrv, _api_days(store, "hrv_last_night_avg"), "hrv")

        progress("Comparing activities...")
        known = {row["activity_id"] for row in store.conn.execute("select activity_id from activity").fetchall()}
        report.activities_only_in_export = len(_activity_ids(archive) - known)
    return report


def newest_export(folder: Path = EXPORT_DIR) -> Path | None:
    zips = sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def main(argv: list[str] | None = None) -> int:
    from creed import config, settings as app_settings
    from creed.db import connect

    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else newest_export()
    if path is None:
        print(f"No export found. Put Garmin's zip in {EXPORT_DIR}/ and run this again.", file=sys.stderr)
        return 1
    config.load_dotenv()
    with connect(config.database_url()) as conn:
        store = Store(conn)
        tz_name = app_settings.load(conn).timezone
        run_id = store.start_run("export")
        store.commit()
        try:
            report = import_export(store, path, tz_name, progress=print)
        except ExportError as exc:
            store.finish_run(run_id, status="failed", requests=0, records=0, backfill_pending=False,
                             message=str(exc), details={})
            store.commit()
            print(exc, file=sys.stderr)
            return 1
        total = sum(report.days.values())
        store.finish_run(run_id, status="ok", requests=0, records=total, backfill_pending=False,
                         message=" ".join(report.lines()), details={})
        store.commit()
    print()
    for line in report.lines():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
