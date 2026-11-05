"""The API against a real Postgres, including what must stay private."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from mock_garmin import GOOD_KEY, PLANTED_LATITUDE, PLANTED_PROFILE_ID, MockGarmin

from creed import auth, config
from creed.api import app as api_module
from creed.db.store import Store
from creed.garmin.client import Client
from creed.sync.engine import TOKEN_SECRET, run_sync

TOKEN = "test-session-token"
CRON = "test-cron-secret"
AUTH = {"Cookie": f"{auth.SESSION_COOKIE}={TOKEN}"}
TODAY = config.local_today()
DATA_ROUTES = ["/api/race", "/api/today", "/api/in-depth", "/api/activities", "/api/activities/1", "/api/data-quality",
               "/api/settings"]


@pytest.fixture
def client(store, database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("CREED_CRON_SECRET", CRON)
    auth.save_dev_session(store.conn, TOKEN)
    store.commit()
    return TestClient(api_module.app)


@pytest.fixture
def synced(client, store):
    with MockGarmin(TODAY, history_days=120, hrv_days=100, hrv_varies=True) as server:
        result = run_sync(store, Client(server.url, GOOD_KEY, delay=0, sleep=lambda _s: None), today=TODAY)
    assert result.status == "ok"
    return client


def wipe_overnight_data(store: Store) -> None:
    store.conn.execute("delete from sleep_night")
    store.conn.execute("delete from daily_metric where metric like 'hrv%%'")
    store.commit()


class TestAccess:
    @pytest.mark.parametrize("route", DATA_ROUTES)
    def test_data_routes_refuse_without_a_session(self, client, route):
        assert client.get(route).status_code == 401

    @pytest.mark.parametrize("route", DATA_ROUTES)
    def test_data_routes_refuse_a_wrong_session(self, client, route):
        assert client.get(route, headers={"Cookie": f"{auth.SESSION_COOKIE}=nope"}).status_code == 401

    @pytest.mark.parametrize("route", DATA_ROUTES)
    def test_a_session_token_in_a_header_is_not_a_way_in(self, client, route, monkeypatch):
        monkeypatch.setenv("CREED_API_TOKEN", TOKEN)
        assert client.get(route, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401

    def test_settings_cannot_be_changed_without_a_session(self, client):
        assert client.put("/api/settings", json={"trimp_curve": "female"}).status_code == 401

    def test_health_reveals_nothing(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_api_docs_are_not_published(self, client):
        for route in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(route).status_code == 404

    def test_personal_data_is_never_cached(self, synced):
        assert synced.get("/api/today", headers=AUTH).headers["Cache-Control"] == "no-store"

    def test_the_session_token_is_not_accepted_for_the_sync(self, client):
        assert client.post("/api/cron/sync", headers=AUTH).status_code == 401
        assert client.post("/api/cron/sync").status_code == 401


class TestPrivacy:
    def test_no_private_detail_in_any_response(self, synced, store):
        activity_id = store.conn.execute("select activity_id from activity limit 1").fetchone()["activity_id"]
        store.commit()
        routes = ["/api/today", "/api/in-depth?days=180", "/api/activities?limit=100",
                  f"/api/activities/{activity_id}", "/api/data-quality", "/api/settings"]
        for route in routes:
            response = synced.get(route, headers=AUTH)
            assert response.status_code == 200, route
            text = response.text
            for planted in ("SECRET_", str(PLANTED_LATITUDE), str(PLANTED_PROFILE_ID), GOOD_KEY, "eyJ"):
                assert planted not in text, f"{planted} leaked from {route}"

    def test_the_saved_garmin_token_is_never_returned(self, synced, store):
        store.set_secret(TOKEN_SECRET, "stored-token-value", None)
        store.commit()
        for route in ("/api/today", "/api/settings", "/api/data-quality"):
            assert "stored-token-value" not in synced.get(route, headers=AUTH).text

    def test_a_bad_request_body_does_not_echo_secrets_or_crash(self, client):
        response = client.put("/api/settings", json=["not", "an", "object"], headers=AUTH)
        assert response.status_code == 422


class TestTodayScreen:
    def test_three_rings_when_there_is_enough_data(self, synced):
        data = synced.get("/api/today", headers=AUTH).json()
        assert [r["key"] for r in data["rings"]] == ["recovery", "strain", "sleep"]
        assert data["hidden"] == []
        assert data["tiles"]["resting_hr"]["value"] == 52
        assert data["tiles"]["sleep_vs_need"]["need_seconds"] > 0

    def test_without_nights_rings_hide_and_resting_hr_steps_in(self, synced, store):
        wipe_overnight_data(store)
        data = synced.get("/api/today", headers=AUTH).json()
        assert [r["key"] for r in data["rings"]] == ["strain", "resting_hr"]
        assert {h["key"] for h in data["hidden"]} == {"recovery", "sleep"}
        assert all(h["reason"] for h in data["hidden"])
        assert data["rings"][1]["value"] == 52
        assert data["rings"][1]["tag"] == "Garmin"
        assert "resting_hr" not in data["tiles"]  # It's a ring now, so not shown twice.

    def test_one_ring_can_return_on_its_own(self, synced, store):
        store.conn.execute("delete from daily_metric where metric like 'hrv%%'")
        store.commit()
        data = synced.get("/api/today", headers=AUTH).json()
        assert [r["key"] for r in data["rings"]] == ["strain", "sleep", "resting_hr"]
        assert [h["key"] for h in data["hidden"]] == ["recovery"]

    def test_garmin_section_has_the_tag_and_real_values(self, synced):
        garmin = synced.get("/api/today", headers=AUTH).json()["garmin"]
        assert garmin["tag"] == "Garmin"
        assert garmin["hrv_status"] == "BALANCED"
        assert garmin["sleep_score"] == 78

    def test_a_garmin_value_with_no_data_is_null_not_zero(self, synced, store):
        wipe_overnight_data(store)
        garmin = synced.get("/api/today", headers=AUTH).json()["garmin"]
        assert garmin["sleep_score"] is None
        assert garmin["hrv_status"] is None

    def test_includes_race_countdown_with_seconds(self, synced):
        race = synced.get("/api/today", headers=AUTH).json()["race"]
        assert set(race["countdown"]) >= {"days", "hours", "minutes", "seconds"}
        assert race["race_date"] == "2027-11-01"

    def test_includes_sync_status(self, synced):
        sync = synced.get("/api/today", headers=AUTH).json()["sync"]
        assert sync["latest_run"]["status"] == "ok"
        assert sync["last_good_finish"] is not None

    def test_short_sleep_counts_as_attention(self, synced, store):
        store.conn.execute("update sleep_night set sleep_seconds = 14400 where calendar_date = %s", (TODAY,))
        store.commit()
        rings = synced.get("/api/today", headers=AUTH).json()["rings"]
        assert next(r for r in rings if r["key"] == "sleep")["attention"] is True
        assert next(r for r in rings if r["key"] == "strain")["attention"] is False

    def test_today_and_week_by_discipline(self, synced):
        data = synced.get("/api/today", headers=AUTH).json()
        assert set(data["today_by_discipline"]) == {"swim", "bike", "run"}
        assert set(data["week_by_discipline"]) == {"swim", "bike", "run"}

    def test_recent_issues_are_listed_and_old_ones_are_not(self, synced, store):
        issues = synced.get("/api/today", headers=AUTH).json()["issues"]
        days = [i["day"] for i in issues]
        assert all(d >= (TODAY - timedelta(days=7)).isoformat() for d in days)
        assert "short_record" in {i["code"] for i in issues}  # The fake watch has one 3 days ago.


class TestInDepth:
    def test_has_every_section_with_a_why_panel(self, synced):
        data = synced.get("/api/in-depth", headers=AUTH).json()
        for section in ("form", "recovery", "sleep", "load", "aerobic"):
            assert data[section]["why"]["citation"], section

    @pytest.mark.parametrize("days", [7, 30, 90, 180])
    def test_series_length_follows_the_range(self, synced, days):
        data = synced.get(f"/api/in-depth?days={days}", headers=AUTH).json()
        assert len(data["recovery"]["hrv"]) == days

    def test_rejects_other_ranges(self, synced):
        assert synced.get("/api/in-depth?days=12", headers=AUTH).status_code == 422

    def test_missing_nights_stay_null(self, synced):
        data = synced.get("/api/in-depth?days=180", headers=AUTH).json()
        # The fake watch is off whenever the days-ago count mod 50 is 7.
        by_day = {r["day"]: r["value"] for r in data["recovery"]["hrv"]}
        assert by_day[(TODAY - timedelta(days=7)).isoformat()] is None
        assert by_day[(TODAY - timedelta(days=8)).isoformat()] == 58  # 50 + 8 in the fake watch's pattern.

    def test_daily_load_has_fourteen_days(self, synced):
        data = synced.get("/api/in-depth", headers=AUTH).json()
        assert len(data["load"]["daily"]) == 14
        assert len(data["sleep"]["nights"]) == 14
        assert len(data["load"]["weekly"]) == 8


class TestRace:
    def test_gives_the_countdown_without_any_health_data(self, client):
        data = client.get("/api/race", headers=AUTH).json()
        assert set(data) == {"race_date", "timezone", "countdown"}
        assert data["race_date"] == "2027-11-01"
        assert data["countdown"]["total_seconds"] > 0

    def test_follows_the_race_date_in_settings(self, client):
        before = client.get("/api/race", headers=AUTH).json()["countdown"]["days"]
        client.put("/api/settings", json={"race_date": "2027-11-02"}, headers=AUTH)
        assert client.get("/api/race", headers=AUTH).json()["countdown"]["days"] == before + 1


class TestActivities:
    def test_each_activity_has_its_computed_load_and_method(self, synced):
        rows = synced.get("/api/activities?limit=100", headers=AUTH).json()["activities"]
        run = next(r for r in rows if r["discipline"] == "run")
        swim = next(r for r in rows if r["discipline"] == "swim")
        assert run["load"] > 0
        assert run["load_method"] == "samples"
        assert swim["load"] > 0
        assert swim["load_method"] == "swim"

    def test_the_load_curve_changes_each_activitys_load(self, synced):
        def first_run():
            rows = synced.get("/api/activities?discipline=run", headers=AUTH).json()["activities"]
            return rows[0]["load"]

        men = first_run()
        synced.put("/api/settings", json={"trimp_curve": "female"}, headers=AUTH)
        assert first_run() > men

    def test_lists_newest_first_and_leaves_out_parents(self, synced):
        rows = synced.get("/api/activities?limit=100", headers=AUTH).json()["activities"]
        assert rows
        assert all(r["discipline"] != "multisport" for r in rows)
        dates = [r["local_date"] for r in rows]
        assert dates == sorted(dates, reverse=True)

    def test_filters_by_discipline(self, synced):
        rows = synced.get("/api/activities?discipline=swim", headers=AUTH).json()["activities"]
        assert rows and all(r["discipline"] == "swim" for r in rows)

    def test_rejects_unknown_discipline(self, synced):
        assert synced.get("/api/activities?discipline=chess", headers=AUTH).status_code == 422

    def test_pages(self, synced):
        first = synced.get("/api/activities?limit=5", headers=AUTH).json()["activities"]
        second = synced.get("/api/activities?limit=5&offset=5", headers=AUTH).json()["activities"]
        assert len(first) == 5
        assert not {r["activity_id"] for r in first} & {r["activity_id"] for r in second}

    def test_detail_includes_its_flags(self, synced, store):
        row = store.conn.execute("select activity_id from activity where discipline = 'run' limit 1").fetchone()
        store.commit()
        data = synced.get(f"/api/activities/{row['activity_id']}", headers=AUTH).json()
        assert data["discipline"] == "run"
        assert "hr_dropouts" in {f["code"] for f in data["flags"]}

    def test_unknown_activity_is_404(self, synced):
        assert synced.get("/api/activities/999999", headers=AUTH).status_code == 404


class TestSettings:
    def test_defaults(self, client):
        data = client.get("/api/settings", headers=AUTH).json()
        assert data["trimp_curve"] == "male"
        assert data["race_date"] == "2027-11-01"
        assert data["timezone"] == "Asia/Kolkata"

    def test_the_load_curve_can_be_switched_and_changes_load_at_once(self, synced):
        def strain_total():
            return sum(d["run"] + d["bike"] + d["swim"] for d in
                       synced.get("/api/in-depth", headers=AUTH).json()["load"]["daily"])

        men = strain_total()
        response = synced.put("/api/settings", json={"trimp_curve": "female"}, headers=AUTH)
        assert response.status_code == 200
        assert response.json()["trimp_curve"] == "female"
        women = strain_total()
        assert women > men
        synced.put("/api/settings", json={"trimp_curve": "male"}, headers=AUTH)
        assert strain_total() == pytest.approx(men)

    def test_settings_survive_between_requests(self, client):
        client.put("/api/settings", json={"race_date": "2027-11-07"}, headers=AUTH)
        assert client.get("/api/settings", headers=AUTH).json()["race_date"] == "2027-11-07"

    def test_race_date_moves_the_countdown(self, synced):
        before = synced.get("/api/today", headers=AUTH).json()["race"]["countdown"]["days"]
        synced.put("/api/settings", json={"race_date": "2027-11-11"}, headers=AUTH)
        assert synced.get("/api/today", headers=AUTH).json()["race"]["countdown"]["days"] == before + 10

    def test_max_hr_override_replaces_the_estimate_and_can_be_cleared(self, synced):
        estimate = synced.get("/api/settings", headers=AUTH).json()["estimates"]["max_hr"]
        changed = synced.put("/api/settings", json={"max_hr": 185}, headers=AUTH).json()
        assert changed["estimates"]["max_hr"] == 185
        assert "Settings" in changed["estimates"]["max_hr_source"]
        cleared = synced.put("/api/settings", json={"max_hr": None}, headers=AUTH).json()
        assert cleared["estimates"]["max_hr"] == estimate

    @pytest.mark.parametrize("changes, message", [
        ({"trimp_curve": "other"}, "Load curve"),
        ({"max_hr": 500}, "between"),
        ({"resting_hr": "fast"}, "between"),
        ({"race_date": "soon"}, "date"),
        ({"timezone": "Mars/Olympus"}, "time zone"),
        ({"recovery_notify_time": "25:00"}, "Time"),
        ({"notify_recovery": "yes"}, "on or off"),
        ({"made_up": 1}, "Unknown"),
        ({"max_hr": 110, "resting_hr": 115}, "below"),
    ])
    def test_bad_values_are_refused_with_a_clear_reason(self, client, changes, message):
        response = client.put("/api/settings", json=changes, headers=AUTH)
        assert response.status_code == 422
        assert message in response.json()["detail"]

    def test_one_bad_value_means_nothing_changes(self, client):
        client.put("/api/settings", json={"race_date": "2027-11-07", "max_hr": 500}, headers=AUTH)
        assert client.get("/api/settings", headers=AUTH).json()["race_date"] == "2027-11-01"


class TestDataQuality:
    def test_summary_and_counts(self, synced):
        data = synced.get("/api/data-quality", headers=AUTH).json()
        assert "short_record" in {row["code"] for row in data["summary"]}
        assert data["nights_recorded_last_28"] > 0
        assert data["sync"]["latest_run"]["status"] == "ok"
        assert data["garmin_key_expires"] is None

    def test_key_expiry_comes_from_settings(self, client):
        client.put("/api/settings", json={"garmin_key_expires": "2027-02-03"}, headers=AUTH)
        assert client.get("/api/data-quality", headers=AUTH).json()["garmin_key_expires"] == "2027-02-03"


class TestCronSync:
    def test_runs_a_sync_with_the_right_secret(self, client, store, monkeypatch):
        with MockGarmin(TODAY, history_days=20) as server:
            monkeypatch.setenv("GARMIN_PERSONAL_API_BASE_URL", server.url)
            monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", GOOD_KEY)
            monkeypatch.setattr(Client.__init__, "__kwdefaults__", {**Client.__init__.__kwdefaults__, "delay": 0})
            response = client.post("/api/cron/sync", headers={"Authorization": f"Bearer {CRON}"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["records"] > 0
        assert store.conn.execute("select trigger from sync_run order by id desc limit 1").fetchone() == {"trigger": "cron"}

    def test_reports_a_bad_key_without_exposing_it(self, client, monkeypatch):
        with MockGarmin(TODAY) as server:
            monkeypatch.setenv("GARMIN_PERSONAL_API_BASE_URL", server.url)
            monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "bad-key-value")
            monkeypatch.setattr(Client.__init__, "__kwdefaults__", {**Client.__init__.__kwdefaults__, "delay": 0})
            response = client.post("/api/cron/sync", headers={"Authorization": f"Bearer {CRON}"})
        assert response.json()["status"] == "auth_failed"
        assert "bad-key-value" not in json.dumps(response.json())
