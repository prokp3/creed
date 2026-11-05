"""Every formula against an example worked out by hand. The working is in each test's comments."""
from __future__ import annotations

import math
import struct
from datetime import date, datetime, timedelta, timezone

import pytest
from mock_garmin import build_fit, fit_definition

from creed.garmin.fit import Sample, read_samples
from creed.metrics import aerobic, backtest, compute_all, fitness, hr_params, race, recovery, sleep, strain, weekly
from creed.metrics.base import INSUFFICIENT, OK, ActivityRecord, MetricContext, Settings, SleepRecord
from creed.metrics.derive import averaged_speed_cv, derive, hr_seconds

TODAY = date(2026, 11, 5)  # A Thursday.
NOW = datetime(2026, 11, 5, 2, 0, tzinfo=timezone.utc)


def ctx(**kwargs) -> MetricContext:
    return MetricContext(today=TODAY, now=NOW, **kwargs)


def days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def run(day=TODAY, **kwargs) -> ActivityRecord:
    defaults = {"activity_id": 1, "day": day, "discipline": "run", "duration_seconds": 3600.0,
                "distance_m": 10000.0, "avg_hr": 150.0, "max_hr": 180.0}
    return ActivityRecord(**{**defaults, **kwargs})


def night(day=TODAY, hours=8.0, **kwargs) -> SleepRecord:
    return SleepRecord(day=day, seconds=int(hours * 3600), **kwargs)


class TestBanisterTrimp:
    def test_men(self):
        # x = (150 - 50) / (190 - 50) = 0.714286
        # weight = 0.64 * e^(1.92 * 0.714286) = 0.64 * 3.94098 = 2.52223
        # 60 * 0.714286 * 2.52223 = 108.10
        assert strain.trimp_from_average(60, 150, 50, 190, "male") == pytest.approx(108.10, abs=0.01)

    def test_women(self):
        # weight = 0.86 * e^(1.67 * 0.714286) = 0.86 * 3.29646 = 2.83496
        # 60 * 0.714286 * 2.83496 = 121.50
        assert strain.trimp_from_average(60, 150, 50, 190, "female") == pytest.approx(121.50, abs=0.01)

    def test_at_resting_hr_there_is_no_load(self):
        assert strain.trimp_from_average(60, 50, 50, 190) == 0

    def test_a_spike_above_max_counts_as_max(self):
        assert strain.trimp_from_average(10, 250, 50, 190) == strain.trimp_from_average(10, 190, 50, 190)

    def test_histogram_adds_up_each_heart_rate(self):
        # 30 min at 150 is half of 108.10. 30 min at 50 adds nothing.
        assert strain.trimp_from_histogram({150: 1800, 50: 1800}, 50, 190) == pytest.approx(54.05, abs=0.01)

    def test_samples_beat_an_average_for_a_mixed_session(self):
        # Half hard and half easy costs more than steady at the average, because the weighting is exponential.
        mixed = strain.trimp_from_histogram({180: 1800, 120: 1800}, 50, 190)
        steady = strain.trimp_from_average(60, 150, 50, 190)
        assert mixed > steady


class TestSwimLoad:
    def test_hand_example(self):
        # 1500 m in 30 min = 0.8333 m/s. Against 1.0 m/s: 0.8333^3 = 0.5787.
        # 0.5787 * 0.5 h * 100 = 28.94
        assert strain.swim_load(1800, 1500, 1.0) == pytest.approx(28.94, abs=0.01)

    def test_threshold_is_the_fastest_long_swim(self):
        swims = [
            run(discipline="swim", distance_m=1500, duration_seconds=1800),   # 0.833 m/s
            run(discipline="swim", distance_m=1000, duration_seconds=1000),   # 1.0 m/s
            run(discipline="swim", distance_m=100, duration_seconds=50),      # 2.0 m/s, too short to count
        ]
        assert strain.swim_threshold_speed(swims) == pytest.approx(1.0)

    def test_swim_load_ignores_heart_rate(self):
        params = hr_params.HrParams(190, "", 50, "")
        slow_hr = run(discipline="swim", distance_m=1500, duration_seconds=1800, avg_hr=90.0)
        high_hr = run(discipline="swim", distance_m=1500, duration_seconds=1800, avg_hr=180.0,
                      hr_seconds={180: 1800})
        assert strain.activity_load(slow_hr, params, 1.0, "male") == strain.activity_load(high_hr, params, 1.0, "male")
        assert strain.activity_load(slow_hr, params, 1.0, "male")[1] == "swim"


class TestHrParams:
    def test_max_is_the_median_of_the_top_three(self):
        activities = [run(max_hr=v) for v in (200, 199, 197, 150, 140)]
        params = hr_params.estimate(ctx(activities=activities))
        assert params.max_hr == 199
        assert "200, 199, 197" in params.max_source

    def test_swims_are_left_out_of_max(self):
        activities = [run(max_hr=v) for v in (190, 180, 170, 160, 150)] + [run(discipline="swim", max_hr=220.0)]
        assert hr_params.estimate(ctx(activities=activities)).max_hr == 180

    def test_resting_is_the_recent_median(self):
        rhr = {days_ago(i): 50.0 + i for i in range(7)}  # 50 to 56
        assert hr_params.estimate(ctx(resting_hr=rhr)).resting_hr == 53

    def test_old_resting_values_are_ignored(self):
        rhr = {days_ago(100 + i): 50.0 for i in range(20)}
        assert hr_params.estimate(ctx(resting_hr=rhr)).resting_hr is None

    def test_settings_override_both(self):
        params = hr_params.estimate(ctx(settings=Settings(max_hr=185, resting_hr=48)))
        assert (params.max_hr, params.resting_hr) == (185, 48)
        assert "Settings" in params.max_source


class TestStrainMetric:
    def full_ctx(self, **kwargs):
        # Max: median of 180, 180, 180 = 180. Resting: 50.
        history = [run(day=days_ago(10 + i), activity_id=100 + i) for i in range(5)]
        return ctx(activities=history + kwargs.pop("today", []),
                   resting_hr={days_ago(i): 50.0 for i in range(10)}, **kwargs)

    def test_insufficient_without_heart_rate_settings(self):
        result = strain.compute(ctx())
        assert result.state == INSUFFICIENT
        assert result.value is None
        assert "activities" in result.reason

    def test_splits_by_discipline(self):
        result = strain.compute(self.full_ctx(today=[
            run(activity_id=1), run(activity_id=2, discipline="bike"),
        ]))
        assert result.state == OK
        assert set(result.details["by_discipline"]) == {"run", "bike"}
        assert result.value == pytest.approx(sum(result.details["by_discipline"].values()))

    def test_a_rest_day_is_zero_not_missing(self):
        result = strain.compute(self.full_ctx())
        assert result.state == OK
        assert result.value == 0

    def test_multisport_parent_is_not_double_counted(self):
        parent = run(activity_id=3, discipline="multisport", is_parent=True)
        leg = run(activity_id=4)
        with_parent = strain.compute(self.full_ctx(today=[parent, leg]))
        without = strain.compute(self.full_ctx(today=[leg]))
        assert with_parent.value == pytest.approx(without.value)

    def test_flagged_activities_are_left_out(self):
        assert strain.compute(self.full_ctx(today=[run(activity_id=5, flagged=True)])).value == 0

    def test_few_swims_lower_confidence(self):
        swim = run(activity_id=6, discipline="swim", distance_m=1500, duration_seconds=1800)
        assert strain.compute(self.full_ctx(today=[swim])).confidence == "low"


class TestFitnessModel:
    def test_hand_example(self):
        # Day 1, load 100: fitness = 100/42 = 2.3810, fatigue = 100/7 = 14.2857. Form starts at 0.
        # Day 2, load 0: fitness = 2.3810 * 41/42 = 2.3243, fatigue = 14.2857 * 6/7 = 12.2449.
        #                form = yesterday's 2.3810 - 14.2857 = -11.9048
        # Day 3, load 0: form = 2.3243 - 12.2449 = -9.9206
        rows = fitness.series({date(2026, 1, 1): 100.0}, date(2026, 1, 3))
        assert [r.load for r in rows] == [100, 0, 0]
        assert rows[0].fitness == pytest.approx(2.3810, abs=1e-3)
        assert rows[0].fatigue == pytest.approx(14.2857, abs=1e-3)
        assert rows[0].form == 0
        assert rows[1].fitness == pytest.approx(2.3243, abs=1e-3)
        assert rows[1].fatigue == pytest.approx(12.2449, abs=1e-3)
        assert rows[1].form == pytest.approx(-11.9048, abs=1e-3)
        assert rows[2].form == pytest.approx(-9.9206, abs=1e-3)

    def test_steady_load_settles_at_that_load(self):
        loads = {date(2024, 1, 1) + timedelta(days=i): 50.0 for i in range(1000)}
        last = fitness.series(loads, date(2024, 1, 1) + timedelta(days=999))[-1]
        assert last.fitness == pytest.approx(50, abs=0.01)
        assert last.fatigue == pytest.approx(50, abs=0.01)
        assert last.form == pytest.approx(0, abs=0.01)

    def test_insufficient_with_no_load(self):
        assert fitness.compute(ctx()).state == INSUFFICIENT

    def test_a_short_history_has_low_confidence(self):
        result = fitness.compute(ctx(
            activities=[run(day=days_ago(i), activity_id=i, max_hr=180.0) for i in range(5)],
            resting_hr={days_ago(i): 50.0 for i in range(10)}))
        assert result.state == OK
        assert result.confidence == "low"


class TestSleepFormulas:
    def test_need_is_the_median_of_the_longest_third(self):
        # 15 nights of 1..15 h: the longest third is 11..15, whose median is 13.
        nights = [night(days_ago(i), hours=i + 1) for i in range(15)]
        assert sleep.sleep_need_seconds(nights) == 13 * 3600

    def test_need_needs_enough_nights(self):
        assert sleep.sleep_need_seconds([night(days_ago(i)) for i in range(13)]) is None

    def test_flagged_nights_are_left_out_of_need(self):
        nights = [night(days_ago(i), hours=8) for i in range(14)] + [night(days_ago(20), hours=15, flagged=True)]
        assert sleep.sleep_need_seconds(nights) == 8 * 3600

    def test_debt_adds_shortfalls_only(self):
        # Need 8 h. Nights of 6, 7 and 9 h: 2 + 1 + 0 = 3 h. The partial night is left out.
        nights = [night(hours=6), night(hours=7), night(hours=9), night(hours=1, flagged=True)]
        assert sleep.sleep_debt_seconds(nights, 8 * 3600) == 3 * 3600

    def test_bedtime_spread_handles_midnight(self):
        # 23:50, 00:10, 23:50, 00:10, 00:00 are -10, +10, -10, +10, 0 minutes around midnight.
        # Sample standard deviation: sqrt(400 / 4) = 10.
        assert sleep.clock_spread_minutes([1430, 10, 1430, 10, 0]) == pytest.approx(10)

    def test_spread_needs_enough_nights(self):
        assert sleep.clock_spread_minutes([1430, 10]) is None


class TestSleepMetric:
    def test_insufficient_without_a_record_for_last_night(self):
        result = sleep.compute(ctx(sleep=[night(days_ago(i + 1)) for i in range(20)]))
        assert result.state == INSUFFICIENT
        assert "last night" in result.reason

    def test_insufficient_without_enough_nights(self):
        result = sleep.compute(ctx(sleep=[night(days_ago(i)) for i in range(5)]))
        assert result.state == INSUFFICIENT
        assert "You have 5" in result.reason

    def test_performance_and_debt(self):
        nights = [night(days_ago(i + 1), hours=8) for i in range(20)] + [night(TODAY, hours=6)]
        result = sleep.compute(ctx(sleep=nights))
        assert result.state == OK
        assert result.value == 6 * 3600
        assert result.details["need_seconds"] == 8 * 3600
        assert result.details["performance"] == pytest.approx(0.75)
        assert result.details["debt_seconds"] == 2 * 3600

    def test_missing_nights_add_no_debt(self):
        nights = [night(days_ago(i + 10), hours=8) for i in range(20)] + [night(TODAY, hours=8)]
        result = sleep.compute(ctx(sleep=nights))
        assert result.details["debt_seconds"] == 0
        assert result.details["debt_nights_counted"] == 1

    def test_stages_are_labelled_approximate(self):
        nights = [night(days_ago(i), hours=8) for i in range(20)]
        assert "approximate" in sleep.compute(ctx(sleep=nights)).details["stages_note"]


class TestRecoveryFormulas:
    def test_z_score(self):
        # Mean 5, sample SD of 4, 5, 6 is 1. A value of 7 is 2 SD above.
        assert recovery.z_score(7, [4, 5, 6]) == pytest.approx(2)

    def test_z_score_needs_spread(self):
        assert recovery.z_score(7, [5, 5, 5]) is None

    def test_sleep_z_limits(self):
        assert recovery.sleep_z(1.0) == 0
        assert recovery.sleep_z(0.85) == pytest.approx(-1)
        assert recovery.sleep_z(0.5) == -2
        assert recovery.sleep_z(1.5) == 1

    def test_composite_all_inputs(self):
        # 0.5*1 + 0.2*1 + 0.1*1 + 0.2*0 = 0.8. Score = 50 + 25*0.8 = 70.
        assert recovery.composite_score({"hrv": 1, "resting_hr": 1, "respiration": 1, "sleep": 0}) == pytest.approx(70)

    def test_missing_input_rescales_rather_than_filling_in(self):
        # HRV and sleep only: (0.5*1 + 0.2*0) / 0.7 = 0.7143. Score = 50 + 25*0.7143 = 67.86.
        assert recovery.composite_score({"hrv": 1, "sleep": 0}) == pytest.approx(67.857, abs=0.001)

    def test_score_stays_within_range(self):
        assert recovery.composite_score({"hrv": 50}) == 100
        assert recovery.composite_score({"hrv": -50}) == 0


class TestRecoveryMetric:
    def alternating(self, low, high, nights=14):
        return {days_ago(i + 1): (low if i % 2 else high) for i in range(nights)}

    def test_hand_example(self):
        # HRV baseline alternates e^4.0 and e^4.2. ln mean 4.1, sample SD 0.1*sqrt(14/13) = 0.103775.
        # Tonight e^4.2: z = 0.1 / 0.103775 = +0.9636.
        # Resting HR alternates 58, 60: mean 59, SD 1.03775. Tonight 58: z = -0.9636, flipped to +0.9636.
        # Respiration alternates 13, 15: mean 14, SD 1.03775. Tonight 13: flipped to +0.9636.
        # Sleep exactly at need: 0.
        # composite = 0.5*0.9636 + 0.2*0.9636 + 0.1*0.9636 + 0.2*0 = 0.77088. Score = 50 + 25*0.77088 = 69.27.
        hrv = self.alternating(math.exp(4.0), math.exp(4.2))
        hrv[TODAY] = math.exp(4.2)
        rhr = self.alternating(58.0, 60.0)
        rhr[TODAY] = 58.0
        sleeps = [night(day, hours=8, respiration=v) for day, v in self.alternating(13.0, 15.0).items()]
        sleeps.append(night(TODAY, hours=8, respiration=13.0))
        result = recovery.compute(ctx(hrv=hrv, resting_hr=rhr, sleep=sleeps))
        assert result.state == OK
        assert result.value == pytest.approx(69.27, abs=0.01)
        assert set(result.details["used"]) == {"hrv", "resting_hr", "respiration", "sleep"}

    def test_tonight_is_not_part_of_its_own_baseline(self):
        hrv = self.alternating(50.0, 60.0)
        hrv[TODAY] = 500.0  # Tonight's outlier must not dilute the comparison.
        _, info = recovery.score_on(ctx(hrv=hrv), TODAY)
        assert info["baseline_nights"] == 14
        assert info["inputs"]["hrv"]["z"] > 10

    def test_nights_older_than_the_window_are_ignored(self):
        hrv = {days_ago(i + 29): 60.0 + i % 2 for i in range(20)}
        hrv[TODAY] = 60.0
        result = recovery.compute(ctx(hrv=hrv))
        assert result.state == INSUFFICIENT
        assert "You have 0" in result.reason

    def test_insufficient_without_last_nights_hrv(self):
        result = recovery.compute(ctx(hrv=self.alternating(50.0, 60.0)))
        assert result.state == INSUFFICIENT
        assert "last night" in result.reason
        assert result.value is None

    def test_insufficient_below_minimum_nights(self):
        hrv = self.alternating(50.0, 60.0, nights=13)
        hrv[TODAY] = 55.0
        result = recovery.compute(ctx(hrv=hrv))
        assert result.state == INSUFFICIENT
        assert "You have 13" in result.reason

    def test_exactly_the_minimum_is_enough(self):
        hrv = self.alternating(50.0, 60.0, nights=14)
        hrv[TODAY] = 55.0
        result = recovery.compute(ctx(hrv=hrv))
        assert result.state == OK
        assert result.confidence == "low"  # Only HRV was available.

    def test_full_inputs_and_baseline_give_high_confidence(self):
        hrv = self.alternating(50.0, 60.0, nights=25)
        hrv[TODAY] = 55.0
        rhr = self.alternating(58.0, 60.0, nights=25)
        rhr[TODAY] = 59.0
        sleeps = [night(day, hours=8, respiration=v) for day, v in self.alternating(13.0, 15.0, nights=25).items()]
        sleeps.append(night(TODAY, hours=8, respiration=14.0))
        assert recovery.compute(ctx(hrv=hrv, resting_hr=rhr, sleep=sleeps)).confidence == "high"

    def test_ui_text_keeps_the_required_statements(self):
        why = recovery.compute(ctx()).why
        assert "Whoop" in why.note
        assert "proprietary" in why.note
        assert "doesn't publish" in why.note
        assert "Plews" in why.citation


class TestWeekly:
    def full(self, activities):
        return ctx(activities=[run(day=days_ago(30 + i), activity_id=900 + i, discipline="other") for i in range(5)]
                   + activities, resting_hr={days_ago(i): 50.0 for i in range(10)})

    def test_weeks_start_on_monday(self):
        assert weekly.week_start(TODAY) == date(2026, 11, 2)
        assert weekly.week_start(date(2026, 11, 2)) == date(2026, 11, 2)
        assert weekly.week_start(date(2026, 11, 1)) == date(2026, 10, 26)

    def test_sums_and_shares(self):
        result = weekly.compute(self.full([
            run(day=date(2026, 11, 3), activity_id=1, distance_m=8000.0),
            run(day=date(2026, 11, 4), activity_id=2, distance_m=2000.0),
            run(day=date(2026, 11, 4), activity_id=3, discipline="bike", distance_m=20000.0),
        ]))
        week = result.details["weeks"][-1]
        assert week["week_start"] == "2026-11-02"
        assert week["disciplines"]["run"]["distance_m"] == 10000
        assert week["disciplines"]["run"]["activities"] == 2
        assert week["disciplines"]["bike"]["distance_m"] == 20000
        # Two runs against one ride of identical HR and duration: 2/3 and 1/3.
        assert week["disciplines"]["run"]["share"] == pytest.approx(2 / 3)
        assert week["disciplines"]["swim"]["share"] == 0

    def test_shows_eight_weeks(self):
        result = weekly.compute(self.full([run(day=TODAY, activity_id=1)]))
        assert len(result.details["weeks"]) == 8

    def test_last_weeks_activity_lands_in_last_week(self):
        result = weekly.compute(self.full([run(day=date(2026, 11, 1), activity_id=1, distance_m=5000.0)]))
        assert result.details["weeks"][-2]["disciplines"]["run"]["distance_m"] == 5000
        assert result.details["weeks"][-1]["disciplines"]["run"]["distance_m"] == 0

    def test_insufficient_with_nothing_recent(self):
        assert weekly.compute(ctx(activities=[run(day=days_ago(200))])).state == INSUFFICIENT


def samples(minutes, speed=3.0, hr=150, second_half_hr=None, step=10):
    total = minutes * 60
    rows = []
    for t in range(0, total + 1, step):
        beat = second_half_hr if second_half_hr is not None and t > 600 + (total - 600) / 2 else hr
        rows.append(Sample(timestamp=1000 + t, heart_rate=beat, speed_mps=speed))
    return rows


class TestDerive:
    def test_hr_seconds_counts_each_gap(self):
        rows = [Sample(0, heart_rate=100), Sample(10, heart_rate=100), Sample(20, heart_rate=120), Sample(25)]
        assert hr_seconds(rows) == {100: 20, 120: 5}

    def test_a_pause_is_not_training_time(self):
        rows = [Sample(0, heart_rate=100), Sample(10, heart_rate=100), Sample(1000, heart_rate=100), Sample(1010)]
        assert hr_seconds(rows) == {100: 20}

    def test_efficiency_factor_hand_example(self):
        # 3 m/s = 180 m/min. 180 / 150 bpm = 1.2.
        result = derive(samples(40), "run")
        assert result.steady is True
        assert result.efficiency == pytest.approx(1.2)
        assert result.decoupling_pct == pytest.approx(0, abs=1e-9)

    def test_decoupling_hand_example(self):
        # First half 180/150 = 1.2. Second half 180/160 = 1.125. (1.2 - 1.125) / 1.2 = 6.25%.
        result = derive(samples(60, second_half_hr=160), "run")
        assert result.decoupling_pct == pytest.approx(6.25, abs=0.3)

    def test_a_short_run_is_not_steady(self):
        assert derive(samples(25), "run").steady is False

    def test_a_variable_run_is_not_steady(self):
        rows = [Sample(1000 + t, heart_rate=150, speed_mps=2.0 if (t // 60) % 2 else 4.5)
                for t in range(0, 2400, 10)]
        assert derive(rows, "run").steady is False

    def test_gps_jitter_alone_does_not_fail_an_even_run(self):
        # Each sample swings between 2.2 and 3.8 m/s, but every minute averages 3.0.
        rows = [Sample(1000 + t, heart_rate=150, speed_mps=2.2 if (t // 10) % 2 else 3.8)
                for t in range(0, 2400, 10)]
        assert derive(rows, "run").steady is True

    def test_a_big_change_of_pace_is_not_steady(self):
        # Alternating 5-minute blocks at 2 and 4 m/s: mean 3, SD 1, so 33% against a 15% limit.
        rows = [Sample(1000 + t, heart_rate=150, speed_mps=2.0 if (t // 300) % 2 else 4.0)
                for t in range(0, 2400, 10)]
        assert derive(rows, "run").steady is False

    def test_averaged_speed_variation_hand_example(self):
        # Two 60-second blocks averaging 2 and 4: mean 3, population SD 1, so 1/3.
        rows = [Sample(60 * (i // 6) + 10 * (i % 6), speed_mps=2.0 if i < 6 else 4.0) for i in range(12)]
        assert averaged_speed_cv(rows, 60) == pytest.approx(1 / 3)

    def test_a_run_with_hr_dropouts_is_not_steady(self):
        rows = [Sample(s.timestamp, heart_rate=None if i % 3 == 0 else 150, speed_mps=3.0)
                for i, s in enumerate(samples(40))]
        assert derive(rows, "run").steady is False

    def test_treadmill_and_other_sports_are_not_compared(self):
        assert derive(samples(40), "run", "treadmill_running").steady is False
        assert derive(samples(40), "bike").steady is False

    def test_but_they_still_get_heart_rate_time(self):
        assert derive(samples(40), "bike").hr_seconds == {150: 2400}


class TestFitSamples:
    def test_reads_values_with_their_scales(self):
        rows, error = read_samples(build_fit())
        assert error is None
        assert len(rows) == 4
        assert rows[0].heart_rate == 140
        assert rows[0].speed_mps == 3.0  # 3000 mm/s
        assert rows[1].timestamp - rows[0].timestamp == 2

    def test_a_dropout_stays_missing(self):
        rows, _ = read_samples(build_fit())
        assert rows[2].heart_rate is None

    def test_position_is_never_read(self):
        rows, _ = read_samples(build_fit())
        assert not hasattr(rows[0], "position_lat")
        assert 123456789 not in vars(rows[0]).values()  # The planted latitude in the test file.

    def test_distance_scale(self):
        body = fit_definition(0, 20, [(253, 4, 0x86), (5, 4, 0x86)])
        body += bytes([0x00]) + struct.pack("<II", 1_000_000_000, 123456)
        data = bytes([14, 0x20, 0, 0]) + struct.pack("<I", len(body)) + b".FIT\x00\x00" + body + b"\x00\x00"
        rows, _ = read_samples(data)
        assert rows[0].distance_m == 1234.56

    def test_garbage_is_reported(self):
        rows, error = read_samples(b"not a fit file at all")
        assert rows == []
        assert error


class TestAerobic:
    def steady(self, days_back, efficiency=1.2, speed=3.0, hr=150.0, drift=3.0):
        return run(day=days_ago(days_back), activity_id=days_back + 1, steady=True, efficiency=efficiency,
                   decoupling_pct=drift, steady_speed_mps=speed, steady_hr=hr)

    def test_insufficient_below_minimum(self):
        result = aerobic.compute(ctx(activities=[self.steady(i) for i in range(5)]))
        assert result.state == INSUFFICIENT
        assert result.reason == "Needs 6 steady runs in 42 days. You have 5."

    def test_median_efficiency_and_drift(self):
        result = aerobic.compute(ctx(activities=[self.steady(i, efficiency=1.0 + i / 10, drift=i) for i in range(6)]))
        assert result.state == OK
        # Median of 1.0..1.5 is 1.25. Median of 0..5 is 2.5.
        assert result.value == pytest.approx(1.25)
        assert result.details["median_drift_pct"] == pytest.approx(2.5)
        assert result.confidence == "medium"

    def test_heart_rate_at_a_given_pace(self):
        # HR = 100 + 15 * speed. At the median speed of 3.0 m/s: 145 bpm.
        runs = [self.steady(i, speed=s, hr=100 + 15 * s) for i, s in enumerate((2.5, 2.8, 3.0, 3.0, 3.2, 3.5))]
        result = aerobic.compute(ctx(activities=runs))
        assert result.details["reference_speed_mps"] == pytest.approx(3.0)
        assert result.details["hr_at_reference_speed"] == pytest.approx(145)

    def test_compares_with_the_previous_window(self):
        runs = [self.steady(i) for i in range(6)] + [self.steady(50 + i, efficiency=1.0) for i in range(6)]
        assert aerobic.compute(ctx(activities=runs)).details["previous_efficiency"] == pytest.approx(1.0)

    def test_old_runs_do_not_count(self):
        assert aerobic.compute(ctx(activities=[self.steady(50 + i) for i in range(10)])).state == INSUFFICIENT

    def test_line_fit_hand_example(self):
        slope, intercept = aerobic.fit_line([(1, 3), (2, 5), (3, 7)])
        assert (slope, intercept) == pytest.approx((2, 1))
        assert aerobic.fit_line([(1, 3), (1, 5)]) is None


class TestRace:
    def test_countdown_hand_example(self):
        # Now is 5 Nov 2026 02:00 UTC = 07:30 IST. Race starts 1 Nov 2027 00:00 IST.
        # 5 Nov 2026 to 31 Oct 2027 07:30 is 360 days, leaving 16 h 30 min.
        left = race.countdown(NOW, date(2027, 11, 1), "Asia/Kolkata")
        assert (left["days"], left["hours"], left["minutes"], left["seconds"]) == (360, 16, 30, 0)

    def test_a_past_race_stops_at_zero(self):
        assert race.countdown(NOW, date(2026, 1, 1), "Asia/Kolkata")["total_seconds"] == 0

    def test_date_comes_from_settings(self):
        result = race.compute(ctx(settings=Settings(race_date=date(2026, 11, 6))))
        assert result.value == 0
        assert result.details["race_date"] == "2026-11-06"

    def test_makes_no_readiness_prediction(self):
        result = race.compute(ctx())
        assert "doesn't predict" in result.why.note
        assert "readiness" not in result.details


class TestBacktest:
    def test_spearman_hand_examples(self):
        assert backtest.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1)
        assert backtest.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1)
        # Ranks x 1,2,3,4 and y 1,3,2,4: 1 - 6*(0+1+1+0) / (4*15) = 0.8.
        assert backtest.spearman([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)

    def test_spearman_shares_ranks_for_ties(self):
        assert backtest._ranks([5, 5, 7]) == [1.5, 1.5, 3]

    def test_spearman_without_variation_says_so(self):
        assert backtest.spearman([1, 1, 1], [1, 2, 3]) is None
        assert backtest.spearman([1, 2], [1, 2]) is None

    def synthetic(self, hard_lowers_hrv: bool) -> MetricContext:
        activities, hrv = [], {}
        for i in range(120):
            day = days_ago(120 - i)
            hard = i % 3 == 0
            if hard:
                activities.append(run(day=day, activity_id=i + 1, duration_seconds=5400.0, avg_hr=170.0))
            elif i % 3 == 1:
                activities.append(run(day=day, activity_id=i + 1, duration_seconds=1800.0, avg_hr=120.0))
            drop = 12 if hard and hard_lowers_hrv else 0
            hrv[day + timedelta(days=1)] = 65.0 - drop + (i % 5) * 0.5
        return ctx(activities=activities, hrv=hrv, resting_hr={days_ago(i): 50.0 for i in range(30)})

    def test_finds_the_expected_effect_when_it_is_there(self):
        response = backtest.load_vs_next_hrv(self.synthetic(hard_lowers_hrv=True))
        assert response.correlation < -0.5
        assert response.after_hard_days < 0
        assert response.after_hard_days < response.after_rest_days
        assert response.enough_data is True

    def test_does_not_find_it_when_it_is_not(self):
        response = backtest.load_vs_next_hrv(self.synthetic(hard_lowers_hrv=False))
        assert abs(response.correlation) < 0.3

    def test_harder_sessions_raise_strain(self):
        params = hr_params.HrParams(190, "", 50, "")
        easy = strain.activity_load(run(avg_hr=120.0, hr_seconds=None), params, None, "male")[0]
        hard = strain.activity_load(run(avg_hr=170.0, hr_seconds=None), params, None, "male")[0]
        longer = strain.activity_load(run(avg_hr=120.0, duration_seconds=7200.0, hr_seconds=None), params, None, "male")[0]
        assert hard > easy
        assert longer == pytest.approx(easy * 2)

    def test_reports_when_there_is_too_little_data(self):
        assert backtest.load_vs_next_hrv(ctx()).enough_data is False


class TestEveryMetric:
    def test_an_empty_account_gives_explicit_states_and_never_a_number(self):
        results = compute_all(ctx())
        assert set(results) == {"recovery", "strain", "fitness", "sleep", "weekly", "aerobic", "race"}
        for key, result in results.items():
            if key == "race":
                continue
            assert result.state == INSUFFICIENT, key
            assert result.value is None, key
            assert result.confidence == "none", key
            assert result.reason, key

    def test_every_metric_has_a_full_why_panel(self):
        for key, result in compute_all(ctx()).items():
            assert result.why.formula, key
            assert result.why.inputs, key
            assert result.why.window, key
            assert result.why.citation, key
            assert result.tag == "Computed", key

    def test_metrics_package_has_no_web_or_database_imports(self):
        import pathlib
        import re
        folder = pathlib.Path(strain.__file__).parent
        for path in folder.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"^\s*(import|from)\s+(fastapi|flask|psycopg|creed\.db|creed\.sync)", text, re.M), path.name
