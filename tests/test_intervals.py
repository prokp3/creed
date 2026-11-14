"""intervals.icu as a data source: its client, how its records become rows, and the sync against a fake server."""
from __future__ import annotations

import gzip
from datetime import date, timedelta

import pytest
from mock_intervals import GOOD_KEY, NOT_SHARED_FILE, MockIntervals

from creed import config
from creed.db import reads
from creed.db.store import Store
from creed.garmin import fit, track
from creed.garmin.client import AuthFailed
from creed.intervals import api
from creed.intervals import normalize as inorm
from creed.intervals.client import Client, check_base_url, gunzipped
from creed.metrics import compute_all
from creed.metrics.base import OK
from creed.sync.intervals import ACTIVITIES, WELLNESS, run_intervals_sync

TODAY = date(2026, 11, 5)
NORMALIZED = ("daily_metric", "sleep_night", "activity", "quality_flag")


def client_for(server: MockIntervals, *, key: str = GOOD_KEY, max_requests: int = 3000) -> Client:
    return Client(server.url, key, delay=0, max_requests=max_requests, sleep=lambda _s: None, backoff=0.01)


def sync(server: MockIntervals, store: Store, *, athlete: str = "0", **kwargs):
    return run_intervals_sync(store, client_for(server, **kwargs), athlete=athlete, today=TODAY)


def count(store: Store, table: str, where: str = "true") -> int:
    return store.conn.execute(f"select count(*) as n from {table} where {where}").fetchone()["n"]


# ---------------------------------------------------------------- choosing the source

class TestDataSource:
    def test_garmin_unless_told_otherwise(self, monkeypatch):
        monkeypatch.delenv(config.DATA_SOURCE_ENV_VAR, raising=False)
        assert config.data_source() == "garmin"
        assert config.source_label() == "Garmin"

    def test_intervals_when_asked(self, monkeypatch):
        monkeypatch.setenv(config.DATA_SOURCE_ENV_VAR, " Intervals ")
        assert config.data_source() == "intervals"
        assert config.source_label() == "intervals.icu"

    def test_a_typo_stops_rather_than_syncing_the_wrong_place(self, monkeypatch):
        monkeypatch.setenv(config.DATA_SOURCE_ENV_VAR, "strava")
        with pytest.raises(RuntimeError, match="garmin, intervals or none"):
            config.data_source()

    def test_the_athlete_id_defaults_to_the_keys_own(self, monkeypatch):
        monkeypatch.delenv(api.ATHLETE_ENV_VAR, raising=False)
        assert api.athlete_id() == "0"
        monkeypatch.setenv(api.ATHLETE_ENV_VAR, "i12345")
        assert api.athlete_id() == "i12345"

    def test_an_athlete_id_that_could_change_the_url_is_refused(self, monkeypatch):
        monkeypatch.setenv(api.ATHLETE_ENV_VAR, "0/../../oauth")
        with pytest.raises(AuthFailed):
            api.athlete_id()

    def test_a_missing_key_says_where_to_find_one(self, monkeypatch):
        monkeypatch.delenv(api.KEY_ENV_VAR, raising=False)
        with pytest.raises(AuthFailed, match="Developer Settings"):
            api.resolve_api_key()


# ---------------------------------------------------------------- client

class TestClient:
    def test_the_key_only_goes_to_intervals_icu(self):
        assert check_base_url("https://intervals.icu/") == "https://intervals.icu"
        for url in ("http://intervals.icu", "https://intervals.icu.evil.example", "https://example.com"):
            with pytest.raises(AuthFailed):
                check_base_url(url)

    def test_an_empty_key_is_refused_before_any_request(self):
        with pytest.raises(AuthFailed):
            Client("https://intervals.icu", "  ")

    def test_a_wrong_key_stops_the_sync(self):
        with MockIntervals(TODAY) as server:
            with pytest.raises(AuthFailed, match="401"):
                client_for(server, key="SECRET_WRONG").get("/api/v1/athlete/0/wellness", {"oldest": "2026-11-01"})

    def test_rate_limits_are_waited_out(self):
        waits = []
        with MockIntervals(TODAY, rate_limit_hits=2) as server:
            client = Client(server.url, GOOD_KEY, delay=0, sleep=waits.append, backoff=0.01)
            rows = api.wellness(client, "0", TODAY, TODAY)
        assert rows and waits == [1.0, 1.0]
        assert len(client.rate_limit_events) == 2

    def test_the_key_never_appears_in_messages(self):
        client = Client("https://intervals.icu", GOOD_KEY)
        assert GOOD_KEY not in client.redact(f"failed with key {GOOD_KEY}")

    def test_gzip_is_unwrapped_and_anything_else_passes_through(self):
        assert gunzipped(gzip.compress(b".FIT data")) == b".FIT data"
        assert gunzipped(b".FIT data") == b".FIT data"
        assert gunzipped(b"\x1f\x8bnot really gzip") == b"\x1f\x8bnot really gzip"


# ---------------------------------------------------------------- normalizing

class TestWellness:
    def test_a_day_becomes_the_same_metrics_garmin_gives(self):
        record, sleep, flags = inorm.wellness({"id": "2026-11-04", "restingHR": 47, "hrv": 66.5, "steps": 12000,
                                               "spO2": 97, "sleepSecs": 26000, "sleepScore": 84, "respiration": 14.2})
        values = {m.metric: m.value_num for m in record.metrics}
        assert values == {"resting_hr": 47, "hrv_last_night_avg": 66.5, "steps": 12000, "spo2_avg": 97}
        assert record.has_data and not flags
        assert sleep["sleep_seconds"] == 26000 and sleep["score_overall"] == 84 and sleep["respiration_avg"] == 14.2

    def test_sleep_has_no_stages_or_times_rather_than_made_up_ones(self):
        _record, sleep, _flags = inorm.wellness({"id": "2026-11-04", "sleepSecs": 26000})
        assert sleep["deep_seconds"] is None and sleep["sleep_start"] is None and sleep["sleep_end"] is None

    def test_an_unworn_day_stays_empty(self):
        record, sleep, _ = inorm.wellness({"id": "2026-11-04", "steps": 0, "ctl": 40})
        assert record.metrics == [] and not record.has_data and sleep is None

    def test_an_impossible_value_is_kept_but_flagged(self):
        record, _, _ = inorm.wellness({"id": "2026-11-04", "restingHR": 250})
        assert [(m.metric, m.quality) for m in record.metrics] == [("resting_hr", "flagged")]
        assert record.flags[0].code == "impossible_resting_hr"

    def test_a_short_night_is_flagged(self):
        _, sleep, flags = inorm.wellness({"id": "2026-11-04", "sleepSecs": 3600})
        assert sleep["quality"] == "flagged" and flags[0].code == "short_record"

    def test_a_record_without_a_date_cant_be_used(self):
        with pytest.raises(inorm.BadRecord):
            inorm.wellness({"restingHR": 50})


class TestActivity:
    ROW = {"id": "i123", "start_date_local": "2026-11-04T06:30:00", "start_date": "2026-11-04T01:00:00Z",
           "type": "Run", "moving_time": 3000, "elapsed_time": 3300, "distance": 10000.0, "average_speed": 3.3,
           "average_heartrate": 150, "max_heartrate": 175, "name": "SECRET_NAME", "source": "COROS"}

    def test_a_run_becomes_the_same_row_garmin_gives(self):
        values, flags = inorm.activity(self.ROW)
        assert values["activity_id"] == inorm.ID_OFFSET + 123
        assert (values["type_key"], values["discipline"]) == ("running", "run")
        assert values["local_date"] == date(2026, 11, 4) and values["utc_offset_minutes"] == 330
        assert values["duration_seconds"] == 3000 and values["elapsed_seconds"] == 3300
        assert values["garmin_load"] is None and not flags
        assert "SECRET_NAME" not in str(values)

    def test_ids_round_trip_and_stay_exact_in_a_browser(self):
        stored = inorm.activity_id("i98765432")
        assert inorm.intervals_id(stored) == "i98765432"
        assert stored < 2**53

    @pytest.mark.parametrize(("kind", "trainer", "key", "discipline"), [
        ("Ride", False, "cycling", "bike"),
        ("Ride", True, "indoor_cycling", "bike"),
        ("VirtualRide", False, "virtual_ride", "bike"),
        ("Run", True, "treadmill_running", "run"),
        ("VirtualRun", False, "virtual_run", "run"),
        ("OpenWaterSwim", False, "open_water_swimming", "swim"),
        ("WeightTraining", False, "strength_training", "other"),
        ("Snowshoe", False, "snowshoe", "other"),
    ])
    def test_types_map_to_disciplines(self, kind, trainer, key, discipline):
        values, _ = inorm.activity({**self.ROW, "type": kind, "trainer": trainer})
        assert (values["type_key"], values["discipline"]) == (key, discipline)

    def test_indoor_runs_and_rides_have_no_map(self):
        for kind, trainer in (("Run", True), ("VirtualRun", False), ("Ride", True), ("VirtualRide", False)):
            values, _ = inorm.activity({**self.ROW, "type": kind, "trainer": trainer})
            assert not track.can_have_map(values["discipline"], values["type_key"])

    def test_a_pool_swim_is_a_lap_swim_and_one_without_a_pool_isnt(self):
        pool, _ = inorm.activity({**self.ROW, "type": "Swim", "pool_length": 25, "lengths": 80})
        assert pool["type_key"] == "lap_swimming" and pool["active_lengths"] == 80
        loose, _ = inorm.activity({**self.ROW, "type": "Swim"})
        assert loose["type_key"] == "swimming"

    def test_the_same_checks_as_garmin_apply(self):
        values, flags = inorm.activity({**self.ROW, "average_heartrate": 190, "max_heartrate": 170})
        assert values["quality"] == "flagged" and flags[0].code == "hr_order"

    def test_strava_stubs_are_unavailable_not_broken(self):
        with pytest.raises(inorm.Unavailable):
            inorm.activity({"id": "16000001", "source": "STRAVA", "start_date_local": "2026-11-04T07:00:00"})
        with pytest.raises(inorm.Unavailable):
            inorm.activity({**self.ROW, "source": "STRAVA"})


# ---------------------------------------------------------------- the sync

class TestSync:
    def test_copies_the_whole_history(self, store):
        with MockIntervals(TODAY, history_days=120) as server:
            result = sync(server, store)
        assert result.status == "ok", result.message
        assert result.backfill_pending is False
        oldest = store.conn.execute(
            "select min(calendar_date) as d from daily_metric where metric = 'resting_hr'").fetchone()["d"]
        assert oldest == TODAY - timedelta(days=120)
        assert count(store, "sleep_night", "source = 'intervals'") > 100
        assert count(store, "activity") == 120 // 3 + 1
        assert count(store, "daily_metric", "source <> 'intervals'") == 0

    def test_every_activity_gets_its_file_unless_intervals_wont_share_it(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
        statuses = {r["fit_status"]: r["n"] for r in store.conn.execute(
            "select fit_status, count(*) as n from activity group by 1").fetchall()}
        assert statuses == {"ok": count(store, "activity") - 1, "none": 1}
        refused = inorm.ID_OFFSET + 5_000_000 + NOT_SHARED_FILE
        flag = store.conn.execute("select code from quality_flag where scope = 'activity_file' and ref_key = %s",
                                  (str(refused),)).fetchone()
        assert flag["code"] == "file_not_shared"

    def test_files_are_stored_unzipped_and_read_like_garmins(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
        run = store.conn.execute("select activity_id from activity where type_key = 'running' and fit_status = 'ok' "
                                 "order by start_time desc limit 1").fetchone()
        content = reads.activity_file(store.conn, run["activity_id"])
        assert content[8:12] == b".FIT"
        points, problem = fit.read_track(fit.unzip_fit(content))
        assert problem is None and len(points) == 30
        assert count(store, "activity_derived") == count(store, "activity_file")

    def test_strava_uploads_are_counted_and_explained(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
        flag = store.conn.execute(
            "select detail from quality_flag where code = 'not_shared_strava' and resolved_at is null").fetchone()
        assert "Strava" in flag["detail"]

    def test_private_details_stay_out_of_normalized_tables(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
        for table in NORMALIZED:
            text = str(store.conn.execute(f"select * from {table}").fetchall())
            assert "SECRET_" not in text, table

    def test_repeating_a_sync_changes_nothing(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
            before = store.conn.execute("select * from daily_metric order by calendar_date, metric").fetchall()
            sync(server, store)
            after = store.conn.execute("select * from daily_metric order by calendar_date, metric").fetchall()
        strip = lambda rows: [{k: v for k, v in r.items() if k != "updated_at"} for r in rows]  # noqa: E731
        assert strip(before) == strip(after)

    def test_a_finished_history_isnt_walked_again(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
            first = server.data_requests
            sync(server, store)
            second = server.data_requests - first
        assert second == 2  # Just the recent window of wellness and of activities.

    def test_many_small_runs_reach_the_same_result_as_one_big_one(self, store, conn):
        with MockIntervals(TODAY, history_days=400) as server:
            for _ in range(200):
                result = sync(server, store, max_requests=6)
                if not result.backfill_pending:
                    break
        assert result.backfill_pending is False
        assert count(store, "activity") == 400 // 3 + 1
        assert count(store, "activity", "fit_status = 'pending'") == 0

    def test_a_corrected_value_replaces_the_old_one(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
            server.overrides[TODAY.isoformat()] = {"restingHR": 41}
            sync(server, store)
        value = store.conn.execute("select value_num from daily_metric where calendar_date = %s "
                                   "and metric = 'resting_hr'", (TODAY,)).fetchone()["value_num"]
        assert value == 41

    def test_a_night_removed_upstream_is_removed_here(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
            server.overrides[TODAY.isoformat()] = {"sleepSecs": None}
            sync(server, store)
        assert count(store, "sleep_night", f"calendar_date = '{TODAY.isoformat()}'") == 0

    def test_a_wrong_key_is_recorded_as_auth_failed(self, store):
        with MockIntervals(TODAY) as server:
            result = sync(server, store, key="SECRET_WRONG_KEY")
        assert result.status == "auth_failed"
        run = store.conn.execute("select status, message from sync_run order by id desc limit 1").fetchone()
        assert run["status"] == "auth_failed" and "SECRET" not in run["message"]

    def test_someone_elses_athlete_id_is_recorded_as_auth_failed(self, store):
        with MockIntervals(TODAY) as server:
            result = sync(server, store, athlete="i999")
        assert result.status == "auth_failed" and "INTERVALS_ATHLETE_ID" in result.message

    def test_garmin_files_are_left_to_garmin(self, store):
        store.conn.execute("insert into activity (activity_id, source, discipline, start_time) "
                           "values (12345, 'api', 'run', now())")
        store.commit()
        with MockIntervals(TODAY) as server:
            sync(server, store)
        assert not any("/activity/12345" in path or "i-" in path for path in server.log)
        assert store.conn.execute("select fit_status from activity where activity_id = 12345").fetchone()[
            "fit_status"] == "pending"

    def test_the_metrics_work_from_intervals_data(self, store):
        with MockIntervals(TODAY, history_days=120) as server:
            sync(server, store)
        ctx = reads.load_context(store.conn, TODAY)
        assert ctx.hrv and ctx.resting_hr and ctx.sleep and ctx.activities
        results = compute_all(ctx)
        assert results["recovery"].state == OK
        assert results["fitness"].state == OK
        assert results["sleep"].state == OK

    def test_cursors_dont_collide_with_garmins(self, store):
        with MockIntervals(TODAY) as server:
            sync(server, store)
        names = {r["dataset"] for r in store.conn.execute("select dataset from sync_cursor").fetchall()}
        assert names == {WELLNESS, ACTIVITIES}


class TestScreens:
    def test_values_are_tagged_with_where_they_came_from(self, store, monkeypatch):
        from creed import settings as app_settings
        from creed.api import views

        with MockIntervals(TODAY) as server:
            sync(server, store)
        monkeypatch.setenv(config.DATA_SOURCE_ENV_VAR, "intervals")
        ctx = reads.load_context(store.conn, TODAY)
        view = views.today_view(ctx, compute_all(ctx), {"tag": config.source_label()}, [], {})
        tags = {ring["tag"] for ring in view["rings"] if ring["key"] == "resting_hr"} | {view["garmin"]["tag"]}
        assert tags <= {"intervals.icu"}
        settings = views.settings_view(app_settings.load(store.conn), ctx)
        assert settings["data_source"] == {"key": "intervals", "label": "intervals.icu"}


class TestApi:
    @pytest.fixture
    def app_client(self, store, database_url, monkeypatch):
        from fastapi.testclient import TestClient

        from creed import auth
        from creed.api import app as api_module
        from creed.intervals.client import BASE_URL_ENV_VAR

        server = MockIntervals(config.local_today(), history_days=30)
        server.__enter__()
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv(config.DATA_SOURCE_ENV_VAR, "intervals")
        monkeypatch.setenv(api.KEY_ENV_VAR, GOOD_KEY)
        monkeypatch.setenv(BASE_URL_ENV_VAR, server.url)
        auth.save_dev_session(store.conn, "test-session-token")
        store.commit()
        yield TestClient(api_module.app, headers={"Cookie": f"{auth.SESSION_COOKIE}=test-session-token"})
        server.__exit__()

    def test_sync_now_reads_intervals_and_every_screen_shows_it(self, app_client):
        assert app_client.post("/api/sync").json()["status"] == "ok"
        today = app_client.get("/api/today").json()
        assert today["garmin"]["tag"] == "intervals.icu"
        assert today["garmin"]["body_battery"] is None  # Only Garmin measures it, so nothing is shown.
        assert app_client.get("/api/in-depth?days=30").json()["garmin"]["tag"] == "intervals.icu"
        settings = app_client.get("/api/settings").json()
        assert settings["data_source"]["label"] == "intervals.icu"

    def test_activities_and_their_maps_work(self, app_client):
        app_client.post("/api/sync")
        rows = app_client.get("/api/activities?discipline=run").json()["activities"]
        assert rows and all(r["activity_id"] > inorm.ID_OFFSET for r in rows)
        outdoor = next(r for r in rows if r["type_key"] == "running")
        route = app_client.get(f"/api/activities/{outdoor['activity_id']}/route").json()
        assert route["incomplete"] is False and route["segments"]

    def test_a_missing_key_says_so(self, app_client, monkeypatch):
        monkeypatch.delenv(api.KEY_ENV_VAR)
        assert app_client.post("/api/sync").json()["status"] == "auth_failed"


class TestCheckTool:
    def test_it_reports_counts_and_never_the_key_or_names(self, monkeypatch, capsys):
        import intervals_check

        from creed.intervals.client import BASE_URL_ENV_VAR

        with MockIntervals(config.local_today(), history_days=40) as server:
            monkeypatch.setenv(api.KEY_ENV_VAR, GOOD_KEY)
            monkeypatch.setenv(BASE_URL_ENV_VAR, server.url)
            assert intervals_check.main() == 0
        out = capsys.readouterr().out
        assert "The key works" in out and "from STRAVA: 1" in out
        assert "SECRET_" not in out

    def test_a_wrong_key_is_reported_plainly(self, monkeypatch, capsys):
        import intervals_check

        from creed.intervals.client import BASE_URL_ENV_VAR

        with MockIntervals(config.local_today()) as server:
            monkeypatch.setenv(api.KEY_ENV_VAR, "SECRET_WRONG")
            monkeypatch.setenv(BASE_URL_ENV_VAR, server.url)
            assert intervals_check.main() == 2
        assert "Key problem" in capsys.readouterr().out


class TestNoWatch:
    def test_none_is_a_valid_source(self, monkeypatch):
        monkeypatch.setenv(config.DATA_SOURCE_ENV_VAR, "none")
        assert config.data_source() == "none" and config.source_label() == "No watch"

    def test_syncing_is_skipped_and_nothing_is_recorded_as_failed(self, store, database_url, monkeypatch):
        from fastapi.testclient import TestClient

        from creed import auth
        from creed.api import app as api_module

        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("CRON_SECRET", "test-cron")
        monkeypatch.setenv(config.DATA_SOURCE_ENV_VAR, "none")
        auth.save_dev_session(store.conn, "test-session-token")
        store.commit()
        client = TestClient(api_module.app, headers={"Cookie": f"{auth.SESSION_COOKIE}=test-session-token"})
        assert client.post("/api/sync").json()["status"] == "skipped"
        cron = client.post("/api/cron/sync", headers={"Authorization": "Bearer test-cron"}).json()
        assert cron["status"] == "skipped"
        assert count(store, "sync_run") == 0
        today = client.get("/api/today").json()
        assert today["garmin"]["source"] == "none"
        assert client.get("/api/settings").json()["data_source"]["key"] == "none"
