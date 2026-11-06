"""The account-export importer, against a small fake export with the same layout as Garmin's."""
from __future__ import annotations

import io
import json
import struct
import zipfile
from datetime import date, datetime, timezone

import pytest
from mock_garmin import fit_definition

from creed.db import reads
from creed.garmin.fit import read_messages
from creed.sync import export
from creed.sync.normalize import Flag, Metric

ZONE = "Asia/Kolkata"
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
PREFIX = "DI_CONNECT/"


def uds(day: str, resting: int = 52, steps: int = 8000, worn_seconds: int = 80000) -> dict:
    return {
        "calendarDate": day,
        "currentDayRestingHeartRate": resting,
        "restingHeartRate": resting + 7,  # Garmin's other, unmatched figure. Must not be used.
        "minAvgHeartRate": 48, "maxAvgHeartRate": 150, "minHeartRate": 40, "maxHeartRate": 170,
        "totalSteps": steps, "totalDistanceMeters": steps * 0.8,
        "moderateIntensityMinutes": 20, "vigorousIntensityMinutes": 5,
        "allDayStress": {"aggregatorList": [
            {"type": "ASLEEP", "averageStressLevel": 10, "maxStressLevel": 40, "totalDuration": 20000},
            {"type": "TOTAL", "averageStressLevel": 30, "maxStressLevel": 90, "totalDuration": worn_seconds},
        ]},
        "bodyBattery": {"chargedValue": 60, "drainedValue": 55, "bodyBatteryStatList": [
            {"bodyBatteryStatType": "HIGHEST", "statsValue": 90}, {"bodyBatteryStatType": "LOWEST", "statsValue": 20},
            {"bodyBatteryStatType": "MOSTRECENT", "statsValue": 35}]},
        "respiration": {"avgWakingRespirationValue": 15.0, "lowestRespirationValue": 10.0,
                        "highestRespirationValue": 22.0},
        "hydration": {"valueInML": 1500.0},
        "totalKilocalories": 2400.0, "activeKilocalories": 500.0,
        "wellnessStartTimeGmt": f"{day}T00:00:00.0", "wellnessStartTimeLocal": f"{day}T05:30:00.0",
    }


def unworn(day: str) -> dict:
    return {"calendarDate": day, "totalSteps": 0, "moderateIntensityMinutes": 0}


def night(day: str, deep: int | None = 5400, light: int = 14400, rem: int = 5400) -> dict:
    return {
        "calendarDate": day,
        "sleepStartTimestampGMT": f"{day}T17:30:00.0".replace(day, "2024-05-31") if day == "2024-06-01" else None,
        "sleepEndTimestampGMT": f"{day}T01:00:00.0",
        "deepSleepSeconds": deep, "lightSleepSeconds": light, "remSleepSeconds": rem,
        "awakeSleepSeconds": 600, "unmeasurableSeconds": 0,
        "sleepScores": {"overallScore": 81}, "averageRespiration": 14.0,
    }


def hrv_fit(moments: list[tuple[datetime, int, int]]) -> bytes:
    """HRV Status summaries: (time, last night's average in ms, status code)."""
    fields = [(253, 4, 0x86), (0, 2, 0x84), (1, 2, 0x84), (2, 2, 0x84), (3, 2, 0x84), (4, 2, 0x84),
              (5, 2, 0x84), (6, 1, 0x00)]
    body = fit_definition(0, export.FIT_MSG_HRV_STATUS_SUMMARY, fields)
    for when, average, status in moments:
        seconds = int((when - FIT_EPOCH).total_seconds())
        scaled = [round(v * export.HRV_SCALE) for v in (average + 2, average, average + 20, 40, 45, 70)]
        body += bytes([0x00]) + struct.pack("<I6HB", seconds, *scaled, status)
    header = bytes([14, 0x20]) + struct.pack("<H", 2132) + struct.pack("<I", len(body)) + b".FIT" + b"\x00\x00"
    return header + body + b"\x00\x00"


def build_export(path, daily=(), sleep=(), hrv=(), activity_ids=()) -> None:
    uploads = io.BytesIO()
    with zipfile.ZipFile(uploads, "w") as inner:
        for n, moments in enumerate(hrv):
            inner.writestr(f"someone@example.com_{n}.fit", hrv_fit(moments))
        inner.writestr("someone@example.com_999.fit", b"not a fit file")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{PREFIX}DI-Connect-Aggregator/UDSFile_2024-05-20_2024-08-28.json", json.dumps(list(daily)))
        archive.writestr(f"{PREFIX}DI-Connect-Wellness/2024-05-12_2024-08-20_1_sleepData.json", json.dumps(list(sleep)))
        archive.writestr(f"{PREFIX}DI-Connect-Uploaded-Files/UploadedFiles_0-_Part1.zip", uploads.getvalue())
        archive.writestr(f"{PREFIX}DI-Connect-Fitness/someone@example.com_1_summarizedActivities.json",
                         json.dumps([{"summarizedActivitiesExport": [{"activityId": i} for i in activity_ids]}]))
        archive.writestr(f"{PREFIX}DI-Connect-User/user_profile.json", json.dumps({"private": "never read"}))


def best(store, day: str, metric: str):
    row = store.conn.execute(
        "select value_num, source from daily_metric_best where calendar_date = %s and metric = %s",
        (date.fromisoformat(day), metric),
    ).fetchone()
    store.commit()
    return (row["value_num"], row["source"]) if row else None


def count(store, sql: str, *args) -> int:
    n = store.conn.execute(sql, args).fetchone()["n"]
    store.commit()
    return n


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "export.zip"
    build_export(
        path,
        daily=[uds("2024-06-01"), uds("2024-06-02", resting=54), unworn("2024-06-03")],
        sleep=[night("2024-06-01"), night("2024-06-02")],
        hrv=[[(datetime(2024, 6, 1, 1, 0, tzinfo=timezone.utc), 60, 4)],
             [(datetime(2024, 6, 1, 20, 0, tzinfo=timezone.utc), 55, 3)]],
        activity_ids=[1, 2],
    )
    return path


class TestReshaping:
    def test_daily_uses_the_fields_that_match_the_api(self):
        api = export.daily_as_api(uds("2024-06-01", resting=52))
        assert api["heartRate"] == {"restingValue": 52, "minValue": 48, "maxValue": 150}
        assert api["bodyBattery"]["maxValue"] == 90
        assert api["bodyBattery"]["latestValue"] == 35
        assert api["stress"]["avgLevel"] == 30  # The whole day's, not just asleep.

    def test_stress_time_becomes_milliseconds(self):
        assert export.daily_as_api(uds("2024-06-01", worn_seconds=3600))["stress"]["totalDurationInMillis"] == 3_600_000

    def test_sleep_total_is_the_three_stages(self):
        assert export.sleep_as_api(night("2024-06-01"), None)["sleepTimeSeconds"] == 5400 + 14400 + 5400

    def test_a_missing_stage_means_no_total_rather_than_a_guess(self):
        assert export.sleep_as_api(night("2024-06-01", deep=None), None)["sleepTimeSeconds"] is None

    def test_hrv_lands_on_the_local_morning(self):
        from zoneinfo import ZoneInfo
        evening_utc = datetime(2024, 6, 1, 20, 0, tzinfo=timezone.utc)  # 1:30 AM on the 2nd in India.
        message = {253: int((evening_utc - FIT_EPOCH).total_seconds()), 1: 55 * export.HRV_SCALE, 6: 3}
        row = export.hrv_as_api(message, ZoneInfo(ZONE))
        assert row["calendarDate"] == "2024-06-02"
        assert row["lastNightAvg"] == 55
        assert row["status"] == "UNBALANCED"

    def test_hrv_status_codes(self):
        assert {code: export.HRV_STATUS_NAMES[code] for code in (2, 3, 4)} == {2: "LOW", 3: "UNBALANCED", 4: "BALANCED"}

    def test_read_messages_returns_only_valid_fields_with_the_timestamp(self):
        when = datetime(2024, 6, 1, 1, 0, tzinfo=timezone.utc)
        messages, problem = read_messages(hrv_fit([(when, 60, 4)]), export.FIT_MSG_HRV_STATUS_SUMMARY)
        assert problem is None
        assert messages[0][1] == 60 * export.HRV_SCALE
        assert messages[0][253] == int((when - FIT_EPOCH).total_seconds())


class TestImport:
    def test_fills_in_days_the_api_does_not_have(self, store, sample):
        report = export.import_export(store, sample, ZONE)
        assert best(store, "2024-06-01", "resting_hr") == (52, "export")
        assert best(store, "2024-06-02", "steps") == (8000, "export")
        assert report.days == {"daily": 2, "sleep": 2, "hrv": 2}
        assert report.added == {"daily": 2, "sleep": 2, "hrv": 2}
        assert report.first_day["daily"] == date(2024, 6, 1)

    def test_an_unworn_day_stays_empty(self, store, sample):
        export.import_export(store, sample, ZONE)
        assert count(store, "select count(*) as n from daily_metric where calendar_date = '2024-06-03'") == 0

    def test_the_api_wins_where_both_have_a_day(self, store, sample):
        store.replace_metrics({date(2024, 6, 1): [Metric("resting_hr", 50.0)]}, "api", ("resting_hr",))
        store.commit()
        report = export.import_export(store, sample, ZONE)
        assert best(store, "2024-06-01", "resting_hr") == (50.0, "api")
        assert report.added["daily"] == 1
        assert count(store, "select count(*) as n from daily_metric where source = 'api'") == 1

    def test_running_it_twice_changes_nothing(self, store, sample):
        export.import_export(store, sample, ZONE)
        tables = ("daily_metric", "sleep_night", "raw_record", "quality_flag")
        before = {t: count(store, f"select count(*) as n from {t}") for t in tables}
        export.import_export(store, sample, ZONE)
        assert {t: count(store, f"select count(*) as n from {t}") for t in tables} == before

    def test_sleep_and_hrv_arrive(self, store, sample):
        export.import_export(store, sample, ZONE)
        row = store.conn.execute("select sleep_seconds, source from sleep_night_best where calendar_date = '2024-06-01'").fetchone()
        store.commit()
        assert dict(row) == {"sleep_seconds": 25200, "source": "export"}
        assert best(store, "2024-06-01", "hrv_last_night_avg") == (60, "export")
        assert best(store, "2024-06-02", "hrv_last_night_avg") == (55, "export")

    def test_the_exports_flags_never_replace_the_apis(self, store, sample):
        store.replace_flags("daily", "2024-06-01", [Flag("low_wear", "info", "From the API.")])
        store.commit()
        export.import_export(store, sample, ZONE)
        assert count(store, "select count(*) as n from quality_flag where scope = 'daily' and resolved_at is null") == 1

    def test_counts_activities_only_in_the_export(self, store, sample):
        assert export.import_export(store, sample, ZONE).activities_only_in_export == 2

    def test_a_broken_fit_file_is_skipped(self, store, sample):
        report = export.import_export(store, sample, ZONE)
        assert report.days["hrv"] == 2

    def test_nothing_from_the_profile_is_stored(self, store, sample):
        export.import_export(store, sample, ZONE)
        assert count(store, "select count(*) as n from raw_record where body::text like '%%never read%%'") == 0

    def test_report_says_what_happened_in_plain_words(self, store, sample):
        lines = export.import_export(store, sample, ZONE).lines()
        assert lines[0].startswith("Daily summaries: 2 days read, 2 not already from the API, from 2024-06-01")
        assert "only in the export" in lines[-1]


class TestBadFiles:
    def test_a_zip_that_is_not_an_export_is_refused(self, store, tmp_path):
        path = tmp_path / "photos.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("holiday.jpg", b"...")
        with pytest.raises(export.ExportError, match="doesn't look like"):
            export.import_export(store, path, ZONE)

    def test_a_file_that_is_not_a_zip_is_refused(self, store, tmp_path):
        path = tmp_path / "export.zip"
        path.write_text("not a zip")
        with pytest.raises(export.ExportError, match="Couldn't open"):
            export.import_export(store, path, ZONE)

    def test_an_unreadable_json_file_is_counted_not_fatal(self, store, tmp_path):
        path = tmp_path / "export.zip"
        build_export(path, daily=[uds("2024-06-01")])
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr(f"{PREFIX}DI-Connect-Aggregator/UDSFile_2024-08-28_2024-12-06.json", "{broken")
        report = export.import_export(store, path, ZONE)
        assert report.unreadable["daily"] == 1
        assert report.days["daily"] == 1


class TestCommand:
    def test_an_import_does_not_change_the_synced_time(self, store, sample, database_url, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", database_url)
        store.start_run("cron")
        store.commit()
        assert export.main([str(sample)]) == 0
        latest = reads.latest_run(store.conn)
        store.commit()
        assert latest["trigger"] == "cron"
        assert count(store, "select count(*) as n from sync_run where trigger = 'export' and status = 'ok'") == 1

    def test_says_where_to_put_the_file_when_there_is_none(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(export, "EXPORT_DIR", tmp_path)
        monkeypatch.setattr(export, "newest_export", lambda folder=tmp_path: None)
        assert export.main([]) == 1
        assert "Put Garmin's zip in" in capsys.readouterr().err
