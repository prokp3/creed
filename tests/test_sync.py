"""The sync against a fake Garmin server and a real Postgres."""
from __future__ import annotations

import json
from datetime import date, timedelta

import psycopg
import pytest
from mock_garmin import GOOD_KEY, PLANTED_LATITUDE, MockGarmin, fake_jwt

from creed.db.migrate import migrate
from creed.db.store import Store
from creed.garmin.client import Client, jwt_expiry
from creed.sync.engine import TOKEN_SECRET, run_sync
from creed.sync.normalize import Flag, Metric

TODAY = date(2026, 11, 5)
TABLES = ("daily_metric", "sleep_night", "activity", "activity_file", "raw_record")


def client_for(server: MockGarmin, store: Store, *, key: str = GOOD_KEY, max_requests: int = 3000) -> Client:
    return Client(
        server.url, key, delay=0, max_requests=max_requests, sleep=lambda _s: None, backoff=0.01,
        token=store.get_secret(TOKEN_SECRET),
        on_token=lambda token, expires: store.set_secret(TOKEN_SECRET, token, expires),
    )


def sync(server: MockGarmin, store: Store, **kwargs):
    return run_sync(store, client_for(server, store, **kwargs), today=TODAY)


def counts(store: Store) -> dict[str, int]:
    return {t: store.conn.execute(f"select count(*) as n from {t}").fetchone()["n"] for t in TABLES}


def snapshot(store: Store) -> dict[str, list]:
    return {
        "daily_metric": store.conn.execute(
            "select calendar_date, metric, source, value_num, value_text, quality from daily_metric "
            "order by 1, 2, 3").fetchall(),
        "sleep_night": store.conn.execute(
            "select calendar_date, sleep_seconds, quality from sleep_night order by 1").fetchall(),
        "activity": store.conn.execute("select activity_id, discipline, fit_status from activity order by 1").fetchall(),
    }


def metric(store: Store, day: date, name: str):
    row = store.conn.execute(
        "select value_num from daily_metric where calendar_date = %s and metric = %s", (day, name)).fetchone()
    return row["value_num"] if row else None


def last_run(store: Store) -> dict:
    return store.conn.execute("select * from sync_run order by id desc limit 1").fetchone()


class TestFirstSync:
    def test_copies_every_dataset_back_to_the_start_of_history(self, store):
        with MockGarmin(TODAY, history_days=100, hrv_days=60) as server:
            result = sync(server, store)
        assert result.status == "ok"
        assert result.backfill_pending is False
        oldest = store.conn.execute("select min(calendar_date) as d from daily_metric where metric = 'resting_hr'").fetchone()["d"]
        assert oldest == TODAY - timedelta(days=100)
        oldest_hrv = store.conn.execute("select min(calendar_date) as d from daily_metric where metric = 'hrv_last_night_avg'").fetchone()["d"]
        assert oldest_hrv == TODAY - timedelta(days=60)
        assert store.conn.execute("select min(calendar_date) as d from sleep_night").fetchone()["d"] == TODAY - timedelta(days=100)

    def test_every_activity_gets_its_file(self, store):
        with MockGarmin(TODAY, history_days=100) as server:
            sync(server, store)
        total = counts(store)
        assert total["activity"] == 50
        assert total["activity_file"] == 50
        assert store.conn.execute("select distinct fit_status from activity").fetchall() == [{"fit_status": "ok"}]

    def test_unworn_days_have_no_rows(self, store):
        with MockGarmin(TODAY, history_days=100) as server:
            sync(server, store)
        # The fake watch is off whenever the days-ago count mod 50 is 7.
        assert metric(store, TODAY - timedelta(days=7), "resting_hr") is None
        assert metric(store, TODAY - timedelta(days=7), "steps") is None
        assert metric(store, TODAY - timedelta(days=8), "resting_hr") == 52

    def test_private_details_stay_out_of_normalized_tables(self, store):
        with MockGarmin(TODAY, history_days=30) as server:
            sync(server, store)
        columns = {c.name for c in store.conn.execute("select * from activity limit 1").description}
        assert not {"activity_name", "description", "start_latitude", "start_longitude"} & columns
        text = json.dumps(store.conn.execute("select * from activity limit 5").fetchall(), default=str)
        assert str(PLANTED_LATITUDE) not in text


class TestIdempotency:
    def test_repeating_a_sync_changes_nothing(self, store):
        with MockGarmin(TODAY, history_days=100) as server:
            sync(server, store)
            before = snapshot(store), counts(store)
            sync(server, store)
            assert (snapshot(store), counts(store)) == before
        assert store.conn.execute("select count(*) as n from sync_run").fetchone()["n"] == 2

    def test_a_finished_history_is_not_walked_again(self, store):
        with MockGarmin(TODAY, history_days=100) as server:
            sync(server, store)
            first = server.data_requests
            sync(server, store)
            second = server.data_requests - first
        # Three datasets over the recent days, one activity page, nothing else.
        assert second == 4

    def test_a_corrected_recent_value_replaces_the_old_one(self, store):
        with MockGarmin(TODAY, history_days=100) as server:
            sync(server, store)
            server.extra_summary_fields = {"heartRate": {"minValue": 40, "maxValue": 120, "restingValue": 49}}
            sync(server, store)
        assert metric(store, TODAY, "resting_hr") == 49
        assert metric(store, TODAY - timedelta(days=2), "resting_hr") == 49
        # Older than the refresh window, so it's left alone.
        assert metric(store, TODAY - timedelta(days=3), "resting_hr") == 52

    def test_a_value_garmin_withdraws_is_removed(self, store):
        with MockGarmin(TODAY, history_days=100) as server:
            sync(server, store)
            server.extra_summary_fields = {"bodyBattery": {"minValue": None, "maxValue": None}}
            sync(server, store)
        assert metric(store, TODAY, "body_battery_max") is None
        assert metric(store, TODAY, "resting_hr") == 52

    def test_days_missed_during_downtime_are_caught_up(self, store):
        with MockGarmin(TODAY, history_days=100) as server:
            sync(server, store)
            store.conn.execute("delete from daily_metric where calendar_date > %s", (TODAY - timedelta(days=10),))
            store.conn.execute("update sync_cursor set newest_date = %s where dataset = 'daily_summary'",
                               (TODAY - timedelta(days=10),))
            store.commit()
            sync(server, store)
        assert metric(store, TODAY - timedelta(days=9), "resting_hr") == 52


class TestResume:
    @pytest.mark.parametrize("budget", [6, 25])
    def test_many_small_runs_reach_the_same_result_as_one_big_run(self, store, budget):
        with MockGarmin(TODAY, history_days=100, hrv_days=60) as server:
            sync(server, store)
            whole = snapshot(store)
            store.conn.execute("truncate daily_metric, sleep_night, activity, raw_record, sync_cursor, sync_run, "
                               "quality_flag restart identity cascade")
            store.commit()
            runs = 0
            while True:
                result = sync(server, store, max_requests=budget)
                runs += 1
                # A very small budget can run out during the refresh, which is reported as partial.
                assert result.status in ("ok", "partial"), result.message
                if not result.backfill_pending:
                    break
                assert runs < 200
        assert runs > 1
        assert snapshot(store) == whole

    def test_running_out_of_budget_during_the_refresh_is_partial(self, store):
        with MockGarmin(TODAY, history_days=30) as server:
            result = sync(server, store, max_requests=3)
        assert result.status == "partial"
        assert "budget" in result.message

    def test_the_cursor_survives_a_cut_off_run(self, store):
        with MockGarmin(TODAY, history_days=100) as server:
            sync(server, store, max_requests=20)
        cursor = store.get_cursor("sleep_summary")
        assert cursor.newest_date == TODAY
        assert cursor.oldest_date is not None


class TestFailures:
    def test_a_bad_key_is_recorded_without_exposing_it(self, store):
        with MockGarmin(TODAY) as server:
            result = sync(server, store, key="not-the-right-key")
        assert result.status == "auth_failed"
        run = last_run(store)
        assert run["status"] == "auth_failed"
        assert "not-the-right-key" not in json.dumps(run, default=str)

    def test_rate_limiting_ends_the_run_politely(self, store):
        with MockGarmin(TODAY, always_429=True, retry_after="0") as server:
            result = sync(server, store)
        assert result.status == "partial"
        assert "429" in result.message
        assert last_run(store)["details"]["rate_limit_events"]

    def test_a_renamed_field_is_reported_and_other_datasets_continue(self, store):
        with MockGarmin(TODAY, history_days=30, hrv_renamed=True) as server:
            result = sync(server, store)
        assert result.status == "partial"
        changed = [e for e in result.errors if e["schema_changed"]]
        assert changed and "hrv" in changed[0]["message"]
        assert counts(store)["sleep_night"] > 0
        assert counts(store)["activity"] > 0

    def test_a_window_garmin_rejects_is_narrowed_and_remembered(self, store):
        with MockGarmin(TODAY, history_days=60, window_limits={"dailySleepSummaries": 7}) as server:
            result = sync(server, store)
        assert result.status == "ok"
        assert store.get_cursor("sleep_summary").window_days == 7
        assert store.conn.execute("select min(calendar_date) as d from sleep_night").fetchone()["d"] == TODAY - timedelta(days=60)

    def test_an_activity_with_no_file_is_not_asked_for_again(self, store):
        with MockGarmin(TODAY, history_days=20, file_status=404) as server:
            sync(server, store)
            assert store.conn.execute("select distinct fit_status from activity").fetchall() == [{"fit_status": "none"}]
            before = server.data_requests
            sync(server, store)
            assert server.data_requests - before == 4

    def test_a_failing_file_is_retried_a_limited_number_of_times(self, store):
        with MockGarmin(TODAY, history_days=4, file_status=410) as server:
            for _ in range(5):
                sync(server, store)
        rows = store.conn.execute("select fit_status, fit_attempts from activity").fetchall()
        assert all(r == {"fit_status": "failed", "fit_attempts": 3} for r in rows)
        assert last_run(store)["status"] == "ok"

    def test_an_unreadable_record_is_flagged_and_the_rest_are_saved(self, store):
        with MockGarmin(TODAY, history_days=10) as server:
            original = server.sleep_row
            server.sleep_row = lambda day: {"sleepTimeSeconds": 25200} if day == TODAY else original(day)
            result = sync(server, store)
        assert result.status == "ok"
        assert counts(store)["sleep_night"] > 0
        flag = store.conn.execute("select code from quality_flag where scope = 'sync' and resolved_at is null").fetchone()
        assert flag == {"code": "unreadable_records"}


class TestDerived:
    def test_each_file_is_read_once_and_its_numbers_kept(self, store):
        with MockGarmin(TODAY, history_days=20) as server:
            sync(server, store)
            count = store.conn.execute("select count(*) as n from activity_derived").fetchone()["n"]
            assert count == counts(store)["activity_file"]
            before = store.conn.execute("select max(updated_at) as t from activity_derived").fetchone()["t"]
            sync(server, store)
            assert store.conn.execute("select max(updated_at) as t from activity_derived").fetchone()["t"] == before

    def test_heart_rate_time_comes_from_the_file(self, store):
        with MockGarmin(TODAY, history_days=4) as server:
            sync(server, store)
        row = store.conn.execute("select samples, hr_coverage, hr_seconds from activity_derived limit 1").fetchone()
        # The fake file has 4 samples 2 s apart at 140, 142, dropout and 144 bpm.
        assert row["samples"] == 4
        assert row["hr_coverage"] == 0.75
        assert row["hr_seconds"] == {"140": 2, "142": 2}

    def test_raising_the_version_recalculates(self, store, monkeypatch):
        with MockGarmin(TODAY, history_days=4) as server:
            sync(server, store)
            monkeypatch.setattr("creed.sync.engine.DERIVE_VERSION", 99)
            sync(server, store)
        versions = store.conn.execute("select distinct derive_version from activity_derived").fetchall()
        assert versions == [{"derive_version": 99}]


class TestMetricsFromDatabase:
    def test_load_context_feeds_every_metric(self, store):
        from creed.db.reads import load_context
        from creed.metrics import compute_all
        with MockGarmin(TODAY, history_days=100, hrv_days=60) as server:
            sync(server, store)
        ctx = load_context(store.conn, TODAY)
        assert TODAY in ctx.hrv
        assert ctx.resting_hr[TODAY] == 52
        assert len(ctx.activities) == 50
        results = compute_all(ctx)
        assert results["fitness"].state == "ok"
        assert results["strain"].details["max_hr"] == 178

    def test_flagged_values_never_reach_the_metrics(self, store):
        from creed.db.reads import load_context
        store.replace_day_metrics(TODAY, "api", ["resting_hr"], [Metric("resting_hr", value_num=300, quality="flagged")])
        store.commit()
        assert TODAY not in load_context(store.conn, TODAY).resting_hr

    def test_local_time_is_worked_out_from_the_stored_offset(self, store):
        from creed.db.reads import load_context
        with MockGarmin(TODAY, history_days=4) as server:
            sync(server, store)
        night = next(n for n in load_context(store.conn, TODAY).sleep if n.day == TODAY)
        assert night.end_local_minutes == 6 * 60 + 30  # The fake watch wakes at 06:30 local time.


class CountingConnection:
    """Counts statements, because each one is a network trip to the real database."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self.statements = 0

    def execute(self, *args, **kwargs):
        self.statements += 1
        return self._conn.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class TestSpeed:
    def test_a_year_of_daily_data_takes_few_database_trips(self, store):
        """At about 45 ms per trip, row-by-row writes overran the function time limit on real data."""
        counting = CountingConnection(store.conn)
        store.conn = counting
        with MockGarmin(TODAY, history_days=365) as server:
            client = client_for(server, store)
            from creed.garmin import api
            from creed.sync.engine import _parse_daily, _Run
            run = _Run(store, client, TODAY)
            rows = api.daily_summaries(client, TODAY - timedelta(days=364), TODAY)
            assert len(rows) == 365
            cursor = store.get_cursor("daily_summary")
            before = counting.statements
            run._ingest_rows("daily_summary", _parse_daily, rows, "test", cursor)
            store.commit()
        assert counting.statements - before <= 15
        assert metric(store, TODAY - timedelta(days=364), "resting_hr") == 52

    def test_a_record_repeated_in_one_response_does_not_break_the_write(self, store):
        from creed.sync.engine import _parse_daily, _Run
        with MockGarmin(TODAY) as server:
            run = _Run(store, client_for(server, store), TODAY)
            row = server.v2_row(TODAY)
            run._ingest_rows("daily_summary", _parse_daily, [row, row], "test", store.get_cursor("daily_summary"))
            store.commit()
        assert metric(store, TODAY, "resting_hr") == 52

    def test_a_run_killed_from_outside_is_closed_by_the_next_one(self, store):
        store.conn.execute("insert into sync_run (trigger, started_at) values ('killed', now() - interval '1 hour')")
        store.conn.execute("insert into sync_run (trigger) values ('still-going')")
        store.commit()
        with MockGarmin(TODAY, history_days=10) as server:
            sync(server, store)
        rows = {r["trigger"]: r for r in store.conn.execute("select trigger, status, message from sync_run").fetchall()}
        assert rows["killed"]["status"] == "failed"
        assert "cut off" in rows["killed"]["message"]
        assert rows["still-going"]["status"] == "running"


class TestToken:
    def test_a_saved_token_is_reused_across_runs(self, store):
        with MockGarmin(TODAY, history_days=10) as server:
            sync(server, store)
            store.commit()
            sync(server, store)
            assert server.tokens_issued == 1
        assert store.get_secret(TOKEN_SECRET) is not None

    def test_a_token_near_expiry_is_replaced_and_saved(self, store):
        with MockGarmin(TODAY, history_days=10) as server:
            store.set_secret(TOKEN_SECRET, fake_jwt(lifetime=600), None)
            store.commit()
            sync(server, store)
            assert server.tokens_issued == 1
        assert jwt_expiry(store.get_secret(TOKEN_SECRET)) > jwt_expiry(fake_jwt(lifetime=3600))

    def test_a_revoked_token_is_replaced(self, store):
        with MockGarmin(TODAY, history_days=10) as server:
            store.set_secret(TOKEN_SECRET, fake_jwt(), None)
            store.commit()
            result = sync(server, store)
            assert server.tokens_issued == 1
        assert result.status == "ok"

    def test_no_token_or_key_appears_in_the_run_log(self, store):
        with MockGarmin(TODAY, history_days=10) as server:
            sync(server, store)
        text = json.dumps(store.conn.execute("select * from sync_run").fetchall(), default=str)
        assert GOOD_KEY not in text
        assert "eyJ" not in text


class TestQuality:
    def test_short_sleep_and_sensor_dropouts_reach_the_flag_table(self, store):
        with MockGarmin(TODAY, history_days=50) as server:
            sync(server, store)
        found = {r["code"] for r in store.conn.execute("select code from quality_flag where resolved_at is null").fetchall()}
        assert "short_record" in found
        assert "hr_dropouts" in found
        short = store.conn.execute("select quality from sleep_night where calendar_date = %s",
                                   (TODAY - timedelta(days=3),)).fetchone()
        assert short == {"quality": "flagged"}

    def test_a_flag_is_resolved_once_the_problem_goes_away(self, store):
        store.replace_flags("sleep", "2026-11-05", [Flag("short_record", "warning", "x")])
        store.replace_flags("sleep", "2026-11-05", [])
        row = store.conn.execute("select resolved_at from quality_flag").fetchone()
        assert row["resolved_at"] is not None

    def test_a_flag_that_returns_is_reopened(self, store):
        store.replace_flags("sleep", "2026-11-05", [Flag("short_record", "warning", "x")])
        store.replace_flags("sleep", "2026-11-05", [])
        store.replace_flags("sleep", "2026-11-05", [Flag("short_record", "warning", "x")])
        assert store.conn.execute("select resolved_at from quality_flag").fetchone()["resolved_at"] is None


class TestSchema:
    def test_migrating_twice_changes_nothing(self, conn):
        assert migrate(conn) == ["0001_init.sql", "0002_activity_derived.sql"]
        assert migrate(conn) == []

    def test_every_table_has_row_level_security(self, store):
        rows = store.conn.execute(
            "select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity").fetchall()
        assert rows == []

    def test_supabases_public_roles_can_read_nothing(self, conn):
        # Supabase gives these roles schema access and default grants on every new table.
        for role in ("anon", "authenticated"):
            conn.execute(f"do $$ begin create role {role}; exception when duplicate_object then null; end $$")
            conn.execute(f"grant usage on schema public to {role}")
            conn.execute(f"alter default privileges in schema public grant all on tables to {role}")
            conn.execute(f"alter default privileges in schema public grant all on sequences to {role}")
        conn.commit()
        migrate(conn)
        # A table added by a later migration must be closed to them as well.
        conn.execute("create table later_table (id integer)")
        conn.commit()
        conn.execute("insert into app_secret (name, value) values ('garmin_token', 'secret')")
        conn.commit()
        for role in ("anon", "authenticated"):
            conn.execute(f"set role {role}")
            for table in ("app_secret", "daily_metric", "daily_metric_best", "sleep_night_best", "activity_file",
                          "later_table"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(f"select * from {table}")
                conn.rollback()
                conn.execute(f"set role {role}")
            conn.execute("reset role")
            conn.commit()

    def test_a_manual_entry_beats_the_api_and_the_api_beats_the_export(self, store):
        day = date(2026, 11, 5)
        for source, value in (("export", 50.0), ("api", 60.0)):
            store.replace_day_metrics(day, source, ["weight"], [Metric("weight", value_num=value)])
        best = "select value_num from daily_metric_best where metric = 'weight'"
        assert store.conn.execute(best).fetchone()["value_num"] == 60.0
        store.replace_day_metrics(day, "manual", ["weight"], [Metric("weight", value_num=70.0)])
        assert store.conn.execute(best).fetchone()["value_num"] == 70.0

    def test_a_new_manual_metric_needs_no_schema_change(self, store):
        store.replace_day_metrics(TODAY, "manual", ["hydration_ml"], [Metric("hydration_ml", value_num=2500)])
        assert metric(store, TODAY, "hydration_ml") == 2500
