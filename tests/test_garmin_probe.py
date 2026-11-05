"""Run with: python -m unittest discover -s tests -v   (no install needed, no network beyond localhost)"""
from __future__ import annotations

import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import garmin_probe as gp  # noqa: E402
from creed.garmin import keys  # noqa: E402
from mock_garmin import GOOD_KEY, PLANTED_LATITUDE, PLANTED_PROFILE_ID, MockGarmin, build_fit, fit_definition  # noqa: E402

TODAY = date(2026, 11, 5)


def make_client(server: MockGarmin, *, key: str = GOOD_KEY, waits: list[float] | None = None, max_requests: int = 3000) -> gp.Client:
    return gp.Client(server.url, key, delay=0, max_requests=max_requests,
                     sleep=(waits.append if waits is not None else lambda _s: None), backoff=0.01)


def run_probe(server: MockGarmin, out: Path, years: float = 2, **kwargs) -> tuple[gp.Probe, dict, str, str, str]:
    client = make_client(server, **kwargs)
    probe = gp.Probe(client, years=years, today=TODAY)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        probe.run()
    md_path, json_path, summary = gp.write_reports(probe, out)
    return probe, summary, md_path.read_text(encoding="utf-8"), json_path.read_text(encoding="utf-8"), captured.getvalue()


def verdicts(summary: dict) -> dict[str, dict]:
    return {v["item"]: v for v in summary["verdicts"]}


class FullRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        with MockGarmin(TODAY, history_days=300, hrv_days=120) as server:
            cls.server_log = server.log
            cls.probe, cls.summary, cls.md, cls.json_text, cls.stdout = run_probe(server, Path(cls.tmp.name))
        cls.v = verdicts(cls.summary)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_completes_without_stopping(self) -> None:
        self.assertIsNone(self.summary["stopped_early"])

    def test_available_items_show_data(self) -> None:
        for item in ("Activities: list", "Activities: FIT download", "Daily summaries", "Sleep: duration",
                     "Sleep: stages", "Sleep: score", "HRV: nightly average", "HRV: status", "HRV: overnight readings",
                     "Resting HR", "Stress", "Body Battery", "Respiration: during sleep", "Steps",
                     "Intensity minutes", "VO2 max", "Training Load: per activity", "Heart rate zones"):
            self.assertEqual(self.v[item]["verdict"], "DATA", item)

    def test_items_absent_from_the_api_are_reported_as_such(self) -> None:
        for item in ("Training Status", "Training Readiness", "Recovery Time", "Training Load: acute, chronic, balance"):
            self.assertEqual(self.v[item]["verdict"], "NOT IN API", item)

    def test_recovery_heart_rate_is_not_mistaken_for_recovery_time(self) -> None:
        self.assertIn("summaryDTO.recoveryHeartRate", self.probe.results["activity_detail"].shape.paths)
        self.assertEqual(self.v["Recovery Time"]["verdict"], "NOT IN API")

    def test_endpoint_answering_with_no_values_is_empty_not_data(self) -> None:
        self.assertEqual(self.v["SpO2"]["verdict"], "EMPTY")
        self.assertEqual(self.v["Hydration (later)"]["verdict"], "EMPTY")
        self.assertEqual(self.v["Weight (later)"]["verdict"], "EMPTY")

    def test_earliest_date_reflects_real_history_per_endpoint(self) -> None:
        # Mock activities stop at 238 days; daily data predating them must still be found.
        self.assertEqual(self.v["Sleep: duration"]["earliest"], (TODAY - timedelta(days=300)).isoformat())
        self.assertEqual(self.v["HRV: nightly average"]["earliest"], (TODAY - timedelta(days=120)).isoformat())

    def test_body_battery_rows_with_only_an_array_do_not_count_as_data(self) -> None:
        by_id = {e["id"]: e for e in self.summary["endpoints"]}
        self.assertEqual(by_id["body_battery_daily"]["earliest"], (TODAY - timedelta(days=300)).isoformat())

    def test_single_night_endpoints_test_dates_known_to_have_data(self) -> None:
        by_id = {e["id"]: e for e in self.summary["endpoints"]}
        # The oldest known night answers, so depth comes from real dates rather than blind samples.
        self.assertEqual(by_id["hrv_chart"]["earliest"], (TODAY - timedelta(days=120)).isoformat())
        self.assertEqual(by_id["daily_sleep"]["earliest"], (TODAY - timedelta(days=300)).isoformat())
        self.assertTrue(any("6 returned data here" in note for note in by_id["hrv_chart"]["notes"]))

    def test_walk_stops_after_a_long_empty_stretch_and_says_so(self) -> None:
        by_id = {e["id"]: e for e in self.summary["endpoints"]}
        self.assertLess(by_id["sleep_summaries"]["requests"], 730 / 31)
        self.assertTrue(any("in a row with no data" in n for n in by_id["sleep_summaries"]["notes"]))

    def test_gap_days_do_not_count_as_data(self) -> None:
        # The mock watch is off every 50th day; that must lower the count instead of being imputed.
        self.assertLess(self.v["Steps"]["last_90_days"], 90)
        self.assertLess(self.v["Sleep: duration"]["last_90_days"], 90)

    def test_paging_continues_when_server_caps_page_size(self) -> None:
        self.assertEqual(self.summary["discipline_counts"]["run"], 20)
        self.assertEqual(len(self.probe.activities), 120)

    def test_disciplines_are_classified_and_swim_hr_is_absent_in_coverage(self) -> None:
        coverage = self.summary["discipline_field_coverage"]
        self.assertNotIn("averageHR", coverage["swim"])
        self.assertIn("averageHR", coverage["run"])

    def test_fit_samples_cover_each_discipline_and_the_oldest(self) -> None:
        labels = {f["sample"] for f in self.summary["fit_samples"]}
        self.assertTrue({"latest run", "latest bike", "latest swim", "latest multisport", "oldest activity"} <= labels)
        self.assertTrue(all(f["http"] == 200 and f["parse_error"] is None for f in self.summary["fit_samples"]))

    def test_sleep_day_attribution_is_measured(self) -> None:
        checks = self.summary["sleep_checks"]
        self.assertGreater(checks["nights"], 100)
        self.assertEqual(checks["calendar_is_wake_date"], checks["nights"])
        # Only the fake watch's 2-hour nights start after midnight, so they match both dates.
        self.assertEqual(checks["calendar_is_bed_date"], checks["under_3_hours"])
        self.assertEqual(checks["local_minus_gmt_hours"], {"5.5": checks["nights"]})
        self.assertGreater(checks["under_3_hours"], 0)

    def test_resting_hr_sources_are_compared(self) -> None:
        compare = self.summary["resting_hr_v2_vs_daily"]
        self.assertGreater(compare["compared"], 0)
        self.assertEqual(compare["equal"], 0)
        self.assertEqual(compare["max_abs_difference"], 1)

    def test_hrv_measure_is_cross_checked_against_labelled_rmssd(self) -> None:
        check = self.summary["hrv_measure_check"]
        self.assertGreater(check["compared_to_last_night_avg"], 0)
        self.assertEqual(check["median_abs_difference_ms"], 1.0)  # 55 ms vs 54 ms in the mock.
        self.assertGreater(check["days_with_sdrr"], 0)

    def test_only_documented_paths_are_called(self) -> None:
        documented = (
            "/userprofile-service/", "/biometric-service/heartRateZones/v2", "/activitylist-service/",
            "/activity-service/activity/", "/download-service/files/activity/", "/usersummary-service/",
            "/hrv-service/hrv/", "/sleep-service/sleep/", "/wellness-service/wellness/", "/weight-service/weight/",
            "/fitnessage-service/fitnessage/v2/", "/wellnessactivity-service/", "/goal-service/", "/nutrition-service/",
        )
        for path in self.server_log:
            self.assertTrue(path.startswith(documented), path)
            self.assertNotIn("menstrual", path)

    def test_no_secrets_or_personal_data_in_any_output(self) -> None:
        for name, text in (("markdown", self.md), ("json", self.json_text), ("stdout", self.stdout)):
            for planted in (GOOD_KEY, "SECRET_", str(PLANTED_LATITUDE), str(PLANTED_PROFILE_ID), "eyJ"):
                self.assertNotIn(planted, text, f"{planted} leaked into {name}")

    def test_token_facts_are_reported_without_token_or_subject(self) -> None:
        token = self.summary["token"]
        self.assertEqual(token["lifetime_hours"], 24)
        self.assertEqual(token["scope"], ["CONNECT_READ", "PERSONAL_API_WELLNESS_READ"])
        self.assertEqual(token["response_format"], "raw text JWT")
        self.assertIn("sub", token["claim_names"])

    def test_report_is_valid_json(self) -> None:
        self.assertEqual(json.loads(self.json_text)["generated_utc"], self.summary["generated_utc"])


class WindowsAndBackoff(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def test_window_shrinks_when_server_is_stricter_than_swagger(self) -> None:
        with MockGarmin(TODAY, history_days=400, window_limits={"steps": 7, "dailysummaries": 180}) as server:
            probe, summary, *_ = run_probe(server, self.out)
        by_id = {e["id"]: e for e in summary["endpoints"]}
        self.assertEqual(by_id["steps_daily"]["accepted_window"], 7)
        self.assertEqual(by_id["steps_daily"]["rejected_windows"], {"28": 400, "14": 400})
        self.assertEqual(by_id["daily_summaries_v2"]["accepted_window"], 180)
        self.assertEqual(verdicts(summary)["Steps"]["verdict"], "DATA")

    def test_accepted_window_is_the_span_really_asked_not_the_nominal_one(self) -> None:
        # A half-year limit clips the 365-day first window, which proves nothing about 365 days.
        with MockGarmin(TODAY, history_days=60) as server:
            _, summary, *_ = run_probe(server, self.out, years=0.5)
        accepted = {e["id"]: e["accepted_window"] for e in summary["endpoints"]}["daily_summaries_v2"]
        self.assertLess(accepted, 365)

    def test_reaching_the_years_limit_with_data_is_flagged(self) -> None:
        with MockGarmin(TODAY, history_days=300) as server:
            _, summary, *_ = run_probe(server, self.out, years=0.5)
        notes = {e["id"]: e["notes"] for e in summary["endpoints"]}["sleep_summaries"]
        self.assertTrue(any("history may go back further" in n for n in notes))

    def test_status_of_none_on_every_night_is_empty_not_data(self) -> None:
        shape = gp.Shape()
        shape.observe({"status": "NONE"}, date(2026, 1, 1))
        self.assertEqual(shape.paths["status"].measured, 0)
        self.assertEqual(shape.paths["status"].positive_dates, set())
        self.assertEqual(shape.paths["status"].values["NONE"], 1)  # Still visible in the report.

    def test_retry_after_is_honoured_then_the_call_succeeds(self) -> None:
        waits: list[float] = []
        with MockGarmin(TODAY, history_days=30, rate_limit_hits={"heartRateZones": 2}, retry_after="7") as server:
            _, summary, *_ = run_probe(server, self.out, waits=waits)
        self.assertEqual(waits.count(7.0), 2)
        self.assertEqual(len(summary["rate_limit"]["events"]), 2)
        self.assertIn("X-RateLimit-Remaining", summary["rate_limit"]["headers_seen"])
        self.assertEqual(verdicts(summary)["Heart rate zones"]["verdict"], "DATA")

    def test_persistent_429_stops_early_but_still_writes_a_report(self) -> None:
        with MockGarmin(TODAY, always_429=True, retry_after="0") as server:
            _, summary, md, *_ = run_probe(server, self.out)
        self.assertIn("kept answering HTTP 429", summary["stopped_early"])
        self.assertIn("STOPPED EARLY", md)
        self.assertEqual(verdicts(summary)["Sleep: duration"]["verdict"], "NOT RUN")
        self.assertTrue((self.out / "probe-report.md").exists())

    def test_request_budget_stops_early_and_says_so(self) -> None:
        with MockGarmin(TODAY, history_days=200) as server:
            _, summary, md, *_ = run_probe(server, self.out, max_requests=30)
            self.assertLessEqual(server.data_requests + server.tokens_issued, 30)
        self.assertIn("budget", summary["stopped_early"])
        self.assertIn("STOPPED EARLY", md)

    def test_token_expiring_midway_is_renewed_once(self) -> None:
        with MockGarmin(TODAY, history_days=30, expire_token_after=5) as server:
            _, summary, *_ = run_probe(server, self.out)
            self.assertEqual(server.tokens_issued, 2)
        self.assertIsNone(summary["stopped_early"])
        self.assertEqual(summary["token"]["minted"], 2)

    def test_bad_key_is_a_clear_auth_failure(self) -> None:
        with MockGarmin(TODAY) as server:
            client = make_client(server, key="not-the-right-key")
            with self.assertRaises(gp.AuthFailed) as caught:
                client.mint_token()
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertNotIn("not-the-right-key", str(caught.exception))

    def test_cross_host_redirect_does_not_forward_the_token(self) -> None:
        with MockGarmin(TODAY, history_days=30, redirect_fit=True) as server:
            _, summary, *_ = run_probe(server, self.out)
            self.assertIs(server.cdn_saw_authorization, False)
        self.assertTrue(all(f["parse_error"] is None for f in summary["fit_samples"]))

    def test_unexpected_readiness_field_flips_the_verdict(self) -> None:
        with MockGarmin(TODAY, history_days=30, extra_summary_fields={"trainingReadiness": {"score": 70}}) as server:
            _, summary, *_ = run_probe(server, self.out)
        verdict = verdicts(summary)["Training Readiness"]
        self.assertEqual(verdict["verdict"], "CHECK: FIELD SEEN")
        self.assertIn("trainingReadiness", verdict["source"])


class FitReader(unittest.TestCase):
    def test_counts_messages_and_ignores_invalid_sentinels(self) -> None:
        fit = gp.read_fit(build_fit())
        self.assertIsNone(fit["parse_error"])
        self.assertEqual(fit["record_count"], 4)
        self.assertEqual(fit["messages"]["record"], 4)
        self.assertEqual(fit["messages"]["session"], 1)
        self.assertEqual(fit["messages"]["length"], 1)
        self.assertEqual(fit["record_field_pct"]["heart_rate"], 75.0)  # One 0xFF dropout in four.
        self.assertEqual(fit["record_field_pct"]["enhanced_speed"], 100.0)
        self.assertEqual(fit["record_median_interval_s"], 2)

    def test_message_140_reports_only_valid_field_numbers(self) -> None:
        fit = gp.read_fit(build_fit())
        self.assertEqual(fit["message_140_field_numbers"], [7])
        self.assertIn(140, fit["undocumented_messages"])

    def test_session_fields_are_named_and_unknown_ones_kept_by_number(self) -> None:
        fit = gp.read_fit(build_fit())
        self.assertEqual(fit["session_fields"], sorted(["sport", "total_timer_time", "avg_heart_rate", "field_200"]))

    def test_no_field_values_are_retained(self) -> None:
        text = json.dumps(gp.read_fit(build_fit()))
        for value in ("123456789", "1234567", "5000"):  # latitude, serial number, message 140 value
            self.assertNotIn(value, text)

    def test_compressed_timestamp_headers(self) -> None:
        base = 1_000_000_000 & ~0x1F  # Low five bits zero, so offsets are easy to reason about.
        body = fit_definition(0, 20, [(253, 4, 0x86), (3, 1, 0x02)])
        body += bytes([0x00]) + struct.pack("<IB", base + 30, 120)
        body += fit_definition(1, 20, [(3, 1, 0x02)])
        # Compressed header, local type 1: offset 31 is +1 s; offset 2 wraps past 32, so it is +4 s.
        body += bytes([0x80 | (1 << 5) | 31, 121])
        body += bytes([0x80 | (1 << 5) | 2, 122])
        data = bytes([14, 0x20, 0, 0]) + struct.pack("<I", len(body)) + b".FIT\x00\x00" + body + b"\x00\x00"
        fit = gp.read_fit(data)
        self.assertIsNone(fit["parse_error"])
        self.assertEqual(fit["record_count"], 3)
        self.assertEqual(fit["record_median_interval_s"], 2.0)  # Intervals of 1 s and 3 s.

    def test_big_endian_definition(self) -> None:
        body = fit_definition(0, 20, [(253, 4, 0x86), (3, 1, 0x02)], big=True)
        body += bytes([0x00]) + struct.pack(">IB", 1_000_000_000, 130)
        data = bytes([14, 0x20, 0, 0]) + struct.pack("<I", len(body)) + b".FIT\x00\x00" + body + b"\x00\x00"
        fit = gp.read_fit(data)
        self.assertEqual(fit["messages"], {"record": 1})
        self.assertEqual(fit["record_field_pct"]["heart_rate"], 100.0)

    def test_developer_fields_are_skipped_correctly(self) -> None:
        body = bytes([0x40 | 0x20, 0, 0]) + struct.pack("<H", 20) + bytes([1, 3, 1, 0x02]) + bytes([1, 0, 2, 0])
        body += bytes([0x00, 130, 0xAA, 0xBB])
        body += bytes([0x00, 131, 0xAA, 0xBB])
        data = bytes([14, 0x20, 0, 0]) + struct.pack("<I", len(body)) + b".FIT\x00\x00" + body + b"\x00\x00"
        fit = gp.read_fit(data)
        self.assertIsNone(fit["parse_error"])
        self.assertEqual(fit["record_count"], 2)

    def test_two_chained_files(self) -> None:
        self.assertEqual(gp.read_fit(build_fit() + build_fit())["record_count"], 8)

    def test_truncated_file_is_flagged_without_crashing(self) -> None:
        data = build_fit()
        fit = gp.read_fit(data[: len(data) // 2])
        self.assertTrue(fit["truncated"])
        self.assertGreater(fit["record_count"], 0)

    def test_garbage_is_reported_not_raised(self) -> None:
        for bad in (b"", b"not a fit file at all", bytes(range(256))):
            self.assertIsNotNone(gp.read_fit(bad)["parse_error"])

    def test_zip_without_a_fit_entry_is_reported(self) -> None:
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("activity.tcx", "<xml/>")
        result = gp.read_activity_zip(buffer.getvalue())
        self.assertEqual(result["parse_error"], "no .fit entry in the archive")
        self.assertEqual(result["extensions"], [".tcx"])


class Credentials(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_only_garmin_and_local_hosts_are_allowed(self) -> None:
        self.assertEqual(gp.check_base_url("https://personal.connectapi.garmin.com/"), "https://personal.connectapi.garmin.com")
        self.assertTrue(gp.check_base_url("http://127.0.0.1:9000"))
        for bad in ("http://personal.connectapi.garmin.com", "https://evil.example.com",
                    "https://personal.connectapi.garmin.com.evil.example"):
            with self.assertRaises(gp.AuthFailed):
                gp.check_base_url(bad)

    def test_explicit_file_beats_environment(self) -> None:
        path = self.dir / "k"
        path.write_text("from-file\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {gp.KEY_ENV_VAR: "from-env"}):
            self.assertEqual(gp.resolve_api_key(str(path)), "from-file")
            self.assertEqual(gp.resolve_api_key(), "from-env")

    def test_environment_beats_default_file_and_empty_is_an_error(self) -> None:
        with mock.patch.dict(os.environ, {gp.KEY_ENV_VAR: "   "}):
            with self.assertRaises(gp.AuthFailed):
                gp.resolve_api_key()

    def test_missing_key_explains_how_to_create_one(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != gp.KEY_ENV_VAR}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(keys, "DEFAULT_KEY_FILE", self.dir / "none"):
            with self.assertRaises(gp.AuthFailed) as caught:
                gp.resolve_api_key()
        self.assertIn("--save-key", str(caught.exception))

    def test_a_key_file_with_a_bom_is_read_cleanly(self) -> None:
        path = self.dir / "k"
        path.write_bytes("﻿abc123\r\n".encode())
        self.assertEqual(gp.resolve_api_key(str(path)), "abc123")

    def test_save_key_round_trip_and_rejects_empty(self) -> None:
        path = gp.save_api_key("  abc123\n", self.dir / "nested" / "key")
        self.assertEqual(path.read_text(encoding="utf-8"), "abc123")
        with self.assertRaises(gp.AuthFailed):
            gp.save_api_key("   ", self.dir / "other")

    def test_save_key_command_never_echoes_the_key(self) -> None:
        captured = io.StringIO()
        with mock.patch.object(keys, "DEFAULT_KEY_FILE", self.dir / "key"), \
                mock.patch.object(gp.getpass, "getpass", return_value="super-secret-value"), \
                contextlib.redirect_stdout(captured):
            self.assertEqual(gp.main(["--save-key"]), gp.EXIT_OK)
        self.assertNotIn("super-secret-value", captured.getvalue())

    def test_redact_catches_key_token_and_any_jwt(self) -> None:
        client = gp.Client("http://127.0.0.1:1", "my-key", delay=0)
        client._token = "my-token"
        text = client.redact("my-key my-token eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0abc.c2ln")
        self.assertEqual(text, "[REDACTED] [REDACTED] [REDACTED-JWT]")


class Helpers(unittest.TestCase):
    def test_discipline_mapping(self) -> None:
        cases = {
            "running": "run", "treadmill_running": "run", "trail_running": "run", "lap_swimming": "swim",
            "open_water_swimming": "swim", "road_biking": "bike", "indoor_cycling": "bike", "virtual_ride": "bike",
            "gravel_cycling": "bike", "mountain_biking": "bike", "multi_sport": "multisport", "transition_v2": "multisport",
            "strength_training": "other", "walking": "other", None: "other",
        }
        for key, expected in cases.items():
            self.assertEqual(gp.discipline_of(key), expected, key)

    def test_date_parsing_handles_each_format_the_spec_describes(self) -> None:
        self.assertEqual(gp.date_of("2026-08-31"), date(2026, 8, 31))
        self.assertEqual(gp.date_of("2026-08-31 06:00:00"), date(2026, 8, 31))
        self.assertEqual(gp.date_of("2026-08-31T06:00:00.0"), date(2026, 8, 31))
        self.assertEqual(gp.date_of(1788148800000), date(2026, 8, 31))
        self.assertIsNone(gp.date_of(None))
        self.assertIsNone(gp.date_of(True))
        self.assertIsNone(gp.date_of("not a date"))

    def test_timestamps_parse_without_assuming_a_zone(self) -> None:
        self.assertEqual(gp.timestamp_of("2026-08-31T06:00:00.0"), datetime(2026, 8, 31, 6, 0))
        self.assertEqual(gp.timestamp_of("2026-08-31T06:00:00Z"), datetime(2026, 8, 31, 6, 0))
        self.assertEqual(gp.timestamp_of(1788134400000), datetime(2026, 8, 31, 0, 0))
        self.assertEqual(gp.timestamp_of({"date": "2026-08-31T06:00:00.0"}), datetime(2026, 8, 31, 6, 0))
        self.assertIsNone(gp.timestamp_of("nope"))

    def test_shape_keeps_values_only_for_allowlisted_fields(self) -> None:
        shape = gp.Shape()
        shape.observe({"displayName": "Someone", "status": "BALANCED", "lastNightAvg": 55, "startLatitude": 15.4}, date(2026, 1, 1))
        self.assertEqual(shape.paths["status"].values["BALANCED"], 1)
        self.assertEqual(shape.paths["lastNightAvg"].numbers, [55.0])
        self.assertEqual(shape.paths["displayName"].values, {})
        self.assertEqual(shape.paths["startLatitude"].numbers, [])

    def test_negative_sentinels_are_not_counted_as_measured_days(self) -> None:
        shape = gp.Shape()
        shape.observe({"overallStressLevel": -1}, date(2026, 1, 1))
        shape.observe({"overallStressLevel": 30}, date(2026, 1, 2))
        self.assertEqual(shape.paths["overallStressLevel"].positive_dates, {date(2026, 1, 2)})

    def test_dates_used_as_object_keys_are_collapsed(self) -> None:
        shape = gp.Shape()
        shape.observe({"2026-01-01": {"a": 1}, "2026-01-02": {"a": 2}})
        self.assertEqual(shape.paths["<key>.a"].present, 2)
        self.assertNotIn("2026-01-01", shape.paths)

    def test_rows_of_rows_are_not_descended_into(self) -> None:
        shape = gp.Shape()
        shape.observe({"heartRateValues": [[1, 60], [2, 61]]})
        self.assertEqual(list(shape.paths), ["heartRateValues"])
        self.assertEqual(shape.paths["heartRateValues"].types["array-of-rows"], 1)

    def test_nested_keys_are_found_through_wrappers_the_spec_omits(self) -> None:
        wrapped = {"dailySleepDTO": {"sleepTimeSeconds": 100}}
        self.assertTrue(gp._pos(wrapped, "sleepTimeSeconds"))
        self.assertFalse(gp._pos({"dailySleepDTO": {"sleepTimeSeconds": None}}, "sleepTimeSeconds"))


if __name__ == "__main__":
    unittest.main()
