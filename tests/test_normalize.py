"""Hand-checked examples for turning Garmin responses into normalized rows."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from creed.sync import normalize


def values(record):
    return {m.metric: m.value_num if m.value_text is None else m.value_text for m in record.metrics}


def codes(flags):
    return {f.code for f in flags}


class TestDailySummary:
    def row(self, **extra):
        return {
            "calendarDate": "2026-11-04",
            "heartRate": {"restingValue": 59, "minValue": 52, "maxValue": 140},
            "movement": {"steps": {"value": 8000, "distanceInMeters": 6200.5}},
            "intensityMinutes": {"moderate": 0, "vigorous": 20},
            "stress": {"avgLevel": 28, "maxLevel": 90, "qualifier": "BALANCED", "totalDurationInMillis": 50_000_000},
            "bodyBattery": {"minValue": 12, "maxValue": 80, "chargedValue": 60, "drainedValue": 55, "latestValue": 40},
            "respiration": {"avgValue": 13, "minValue": 9, "maxValue": 19},
            **extra,
        }

    def test_reads_each_field(self):
        got = values(normalize.daily_summary(self.row()))
        assert got["resting_hr"] == 59
        assert got["steps"] == 8000
        assert got["step_distance_m"] == 6200.5
        assert got["stress_qualifier"] == "BALANCED"
        assert got["body_battery_charged"] == 60
        assert got["respiration_avg"] == 13

    def test_zero_intensity_is_a_real_value(self):
        assert values(normalize.daily_summary(self.row()))["intensity_moderate"] == 0

    def test_negative_stress_means_not_measured(self):
        row = self.row(stress={"avgLevel": -1, "maxLevel": -2})
        got = normalize.daily_summary(row)
        assert "stress_avg" not in values(got)
        assert "stress_max" not in values(got)
        assert not got.flags

    def test_missing_values_are_never_filled_in(self):
        row = self.row(respiration=None)
        assert "respiration_avg" not in values(normalize.daily_summary(row))

    def test_unworn_day_is_empty_rather_than_zeros(self):
        row = {"calendarDate": "2026-11-04", "heartRate": {"restingValue": None},
               "movement": {"steps": {"value": 0}}, "intensityMinutes": {"moderate": 0, "vigorous": 0}}
        record = normalize.daily_summary(row)
        assert record.has_data is False
        assert record.metrics == []

    def test_impossible_value_is_kept_but_flagged(self):
        record = normalize.daily_summary(self.row(heartRate={"restingValue": 300}))
        metric = next(m for m in record.metrics if m.metric == "resting_hr")
        assert metric.value_num == 300
        assert metric.quality == "flagged"
        assert "impossible_resting_hr" in codes(record.flags)

    def test_low_wear_is_noted(self):
        record = normalize.daily_summary(self.row(stress={"avgLevel": 20, "totalDurationInMillis": 3_600_000}))
        assert "low_wear" in codes(record.flags)

    def test_no_date_is_a_bad_record(self):
        with pytest.raises(normalize.BadRecord):
            normalize.daily_summary({"heartRate": {"restingValue": 59}})


class TestHrv:
    def row(self, **extra):
        return {"calendarDate": "2026-10-28", "lastNightAvg": 63, "lastNight5MinHigh": 92, "weeklyAvg": 60,
                "status": "BALANCED", "baseline": {"balancedLow": 57, "balancedUpper": 75, "lowUpper": 53}, **extra}

    def test_reads_garmin_values_unchanged(self):
        got = values(normalize.hrv_summary(self.row()))
        assert got["hrv_last_night_avg"] == 63
        assert got["hrv_status"] == "BALANCED"
        assert got["hrv_balanced_low"] == 57

    def test_status_none_means_no_status(self):
        got = values(normalize.hrv_summary(self.row(status="NONE")))
        assert "hrv_status" not in got
        assert got["hrv_last_night_avg"] == 63

    def test_night_without_average_has_no_data(self):
        record = normalize.hrv_summary({"calendarDate": "2026-10-28", "status": "NONE"})
        assert record.has_data is False
        assert record.metrics == []


class TestSleep:
    # 23:15 to 06:30 at UTC+5:30, as epoch milliseconds, the way Garmin sends them.
    START_GMT = int(datetime(2026, 10, 27, 17, 45, tzinfo=timezone.utc).timestamp() * 1000)
    END_GMT = int(datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc).timestamp() * 1000)
    END_LOCAL = int(datetime(2026, 10, 28, 6, 30, tzinfo=timezone.utc).timestamp() * 1000)

    def row(self, **extra):
        return {
            "calendarDate": "2026-10-28", "sleepTimeSeconds": 25200, "deepSleepSeconds": 4560,
            "lightSleepSeconds": 15000, "remSleepSeconds": 5640, "awakeSleepSeconds": 900,
            "sleepStartTimestampGMT": self.START_GMT, "sleepEndTimestampGMT": self.END_GMT,
            "sleepEndTimestampLocal": self.END_LOCAL, "averageRespirationValue": 14.0,
            "sleepScores": {"overall": {"value": 78, "qualifierKey": "FAIR"}}, **extra,
        }

    def test_reads_times_as_utc_with_local_offset(self):
        values_, flags = normalize.sleep_night(self.row())
        assert values_["sleep_end"] == datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)
        assert values_["utc_offset_minutes"] == 330
        assert values_["calendar_date"] == date(2026, 10, 28)
        assert values_["score_overall"] == 78
        assert values_["quality"] == "ok"
        assert flags == []

    def test_no_sleep_recorded_gives_nothing(self):
        assert normalize.sleep_night(self.row(sleepTimeSeconds=None)) is None
        assert normalize.sleep_night(self.row(sleepTimeSeconds=0)) is None

    def test_short_record_is_flagged_so_metrics_can_leave_it_out(self):
        values_, flags = normalize.sleep_night(self.row(
            sleepTimeSeconds=7200, deepSleepSeconds=1000, lightSleepSeconds=5000, remSleepSeconds=1200))
        assert values_["quality"] == "flagged"
        assert codes(flags) == {"short_record"}

    def test_impossible_duration_is_flagged(self):
        values_, flags = normalize.sleep_night(self.row(
            sleepTimeSeconds=70000, deepSleepSeconds=20000, lightSleepSeconds=30000, remSleepSeconds=20000))
        assert values_["quality"] == "flagged"
        assert "impossible_duration" in codes(flags)

    def test_stages_that_miss_the_total_are_flagged(self):
        _, flags = normalize.sleep_night(self.row(deepSleepSeconds=100))
        assert "stage_mismatch" in codes(flags)

    def test_filing_under_the_wrong_day_is_flagged(self):
        _, flags = normalize.sleep_night(self.row(calendarDate="2026-10-27"))
        assert "date_not_wake_date" in codes(flags)


class TestActivity:
    def row(self, **extra):
        return {
            "activityId": 123, "activityName": "Private name", "startLatitude": 15.5,
            "activityType": {"typeKey": "running"}, "startTimeGMT": "2026-09-25 00:40:00",
            "startTimeLocal": "2026-09-25 06:10:00", "duration": 3600.0, "movingDuration": 3500.0,
            "distance": 10200.0, "averageSpeed": 2.9, "averageHR": 148.0, "maxHR": 178.0,
            "activityTrainingLoad": 96.5, "avgPower": 280.0, **extra,
        }

    def test_reads_fields_and_time_zone(self):
        values_, flags = normalize.activity(self.row())
        assert values_["discipline"] == "run"
        assert values_["start_time"] == datetime(2026, 9, 25, 0, 40, tzinfo=timezone.utc)
        assert values_["local_date"] == date(2026, 9, 25)
        assert values_["utc_offset_minutes"] == 330
        assert values_["garmin_load"] == 96.5
        assert values_["avg_power"] == 280.0
        assert flags == []

    def test_names_and_gps_stay_out_of_the_normalized_row(self):
        values_, _ = normalize.activity(self.row())
        assert "Private name" not in values_.values()
        assert 15.5 not in values_.values()

    @pytest.mark.parametrize("extra, code", [
        ({"duration": 0}, "no_duration"),
        ({"averageHR": 400.0}, "impossible_hr"),
        ({"averageHR": 190.0, "maxHR": 150.0}, "hr_order"),
        ({"distance": -5.0}, "impossible_distance"),
        ({"averageSpeed": 20.0}, "impossible_speed"),
    ])
    def test_impossible_values_are_flagged(self, extra, code):
        values_, flags = normalize.activity(self.row(**extra))
        assert values_["quality"] == "flagged"
        assert code in codes(flags)

    def test_a_fast_ride_is_not_impossible_but_the_same_speed_running_is(self):
        ride, _ = normalize.activity(self.row(activityType={"typeKey": "cycling"}, averageSpeed=15.0))
        run, _ = normalize.activity(self.row(averageSpeed=15.0))
        assert ride["quality"] == "ok"
        assert run["quality"] == "flagged"

    def test_no_id_is_a_bad_record(self):
        with pytest.raises(normalize.BadRecord):
            normalize.activity({"activityType": {"typeKey": "running"}})


class TestFitFlags:
    def test_clean_file_has_no_flags(self):
        fit = {"parse_error": None, "record_count": 100, "record_field_pct": {"heart_rate": 100, "enhanced_speed": 100}}
        assert normalize.fit_flags("run", fit) == []

    def test_heart_rate_dropouts_are_a_warning_on_a_run(self):
        fit = {"record_count": 100, "record_field_pct": {"heart_rate": 70, "enhanced_speed": 100}}
        assert [(f.code, f.severity) for f in normalize.fit_flags("run", fit)] == [("hr_dropouts", "warning")]

    def test_heart_rate_dropouts_are_only_a_note_on_a_swim(self):
        fit = {"record_count": 100, "record_field_pct": {"heart_rate": 70}}
        assert [(f.code, f.severity) for f in normalize.fit_flags("swim", fit)] == [("hr_dropouts", "info")]

    def test_missing_speed_is_flagged_on_a_ride(self):
        fit = {"record_count": 100, "record_field_pct": {"heart_rate": 100}}
        assert "speed_dropouts" in codes(normalize.fit_flags("bike", fit))

    def test_unreadable_file_is_a_problem(self):
        assert codes(normalize.fit_flags("run", {"parse_error": "bad"})) == {"fit_unreadable"}
