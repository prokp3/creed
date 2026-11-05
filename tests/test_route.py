"""The route map: reading GPS from a FIT file, turning it into a line, and who can ask for it."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from mock_garmin import GOOD_KEY, MockGarmin, build_fit, build_gps_fit

from creed import auth, config
from creed.api import app as api_module
from creed.garmin import fit, track
from creed.garmin.client import Client
from creed.garmin.fit import TrackPoint
from creed.sync.engine import run_sync

TOKEN = "test-session-token"
AUTH = {"Cookie": f"{auth.SESSION_COOKIE}={TOKEN}"}
TODAY = config.local_today()
# Fake places, far from anywhere the tests' watch has been. Easy to spot if they leak into another response.
LAT, LON = -41.2345, 174.7654


def point(seconds: int, latitude: float = LAT, longitude: float = LON) -> TrackPoint:
    return TrackPoint(seconds, latitude, longitude)


def walking(seconds: int, metres_per_step: float = 10.0, step_seconds: int = 3) -> list[TrackPoint]:
    """A straight line north. One degree of latitude is 111,195 m, from a 6,371 km Earth radius."""
    degrees_per_step = metres_per_step / 111_195
    return [point(i * step_seconds, LAT + i * degrees_per_step) for i in range(seconds // step_seconds + 1)]


class TestReadingGps:
    def test_semicircles_become_degrees(self):
        data = build_gps_fit([(0, 90.0, -45.0), (2, -22.5, -180.0)])
        points, problem = fit.read_track(data)
        assert problem is None
        assert [(p.latitude, p.longitude) for p in points] == [
            pytest.approx((90.0, -45.0)), pytest.approx((-22.5, -180.0))]
        assert points[1].timestamp - points[0].timestamp == 2

    def test_samples_with_no_fix_are_left_out_not_filled_in(self):
        data = build_gps_fit([(0, 10.0, 20.0), (2, None, None), (4, 10.1, None), (6, 10.2, 20.2)])
        points, _ = fit.read_track(data)
        assert [p.timestamp - points[0].timestamp for p in points] == [0, 6]

    def test_a_latitude_with_no_longitude_is_not_a_position(self):
        assert fit.read_track(build_fit())[0] == []  # The test file plants a latitude alone.

    def test_a_broken_file_reports_it_rather_than_crashing(self):
        points, problem = fit.read_track(b"this is not a FIT file")
        assert points == []
        assert problem

    def test_samples_still_never_carry_a_position(self):
        rows, _ = fit.read_samples(build_gps_fit([(0, LAT, LON)]))
        assert not any(hasattr(row, "latitude") or hasattr(row, "position_lat") for row in rows)


class TestDistance:
    def test_one_degree_of_latitude(self):
        # 2 * pi * 6,371,000 / 360 = 111,194.93 m.
        assert track.metres_between(point(0, 0, 0), point(0, 1, 0)) == pytest.approx(111_194.93, abs=0.01)

    def test_a_degree_of_longitude_shrinks_towards_the_poles(self):
        # At 60 degrees it's half of the equator's, because cos(60) = 0.5.
        at_60 = track.metres_between(point(0, 60, 0), point(0, 60, 1))
        assert at_60 == pytest.approx(111_194.93 / 2, rel=0.001)


class TestSplitting:
    def test_a_continuous_recording_is_one_line(self):
        assert len(track.split_segments(walking(60))) == 1

    def test_a_long_gap_in_time_breaks_the_line(self):
        before, after = walking(30), [point(p.timestamp + 100, p.latitude + 0.001) for p in walking(30)]
        assert len(track.split_segments(before + after)) == 2

    def test_a_gap_at_the_limit_does_not_break_it(self):
        points = [point(0), point(track.MAX_GAP_SECONDS, LAT + 0.0001)]
        assert len(track.split_segments(points)) == 1

    def test_an_impossible_jump_breaks_the_line(self):
        # 1 km in 2 seconds is 500 m/s.
        points = [point(0), point(2, LAT + 1000 / 111_195), point(4, LAT + 1000 / 111_195 + 0.00001)]
        segments = track.split_segments(points)
        assert len(segments) == 1
        assert len(segments[0]) == 2  # The first point stands alone, so it can't be drawn.

    def test_a_fast_ride_is_not_a_jump(self):
        # 25 m/s, or 90 km/h downhill, is under the limit.
        points = [point(i, LAT + i * 25 / 111_195) for i in range(5)]
        assert len(track.split_segments(points)) == 1

    def test_impossible_coordinates_are_dropped(self):
        points = [point(0), point(1, 95.0, LON), point(2, LAT + 0.00001)]
        assert [p.timestamp for p in track.split_segments(points)[0]] == [0, 2]

    def test_a_lone_point_cannot_be_a_line(self):
        assert track.split_segments([point(0)]) == []
        assert track.split_segments([]) == []


class TestBuildingARoute:
    def test_no_gps_says_so(self):
        route = track.build_route([])
        assert route["segments"] == []
        assert route["reason"] == track.NO_GPS

    def test_coordinates_are_longitude_then_latitude(self):
        route = track.build_route(walking(60))
        assert route["start"] == [LON, LAT]
        assert route["segments"][0][0] == [LON, LAT]

    def test_bounds_wrap_the_whole_route(self):
        points = walking(60)
        route = track.build_route(points)
        assert route["bounds"][0] == [LON, LAT]
        assert route["bounds"][1][1] == round(points[-1].latitude, track.DECIMALS)

    def test_a_gap_is_counted_and_nothing_crosses_it(self):
        before = walking(30)
        after = [point(p.timestamp + 100, p.latitude + 0.01) for p in walking(30)]
        route = track.build_route(before + after)
        assert route["gaps"] == 1
        assert len(route["segments"]) == 2
        assert route["segments"][0][-1] != route["segments"][1][0]
        assert route["finish"] == route["segments"][1][-1]

    def test_close_points_are_thinned_but_the_ends_stay(self):
        points = walking(60, metres_per_step=1.0, step_seconds=1)  # 1 m apart, so every 5th is kept.
        route = track.build_route(points)
        line = route["segments"][0]
        assert len(line) == pytest.approx(len(points) / track.MIN_STEP_METRES, abs=2)
        assert line[0] == [LON, round(points[0].latitude, track.DECIMALS)]
        assert line[-1] == [LON, round(points[-1].latitude, track.DECIMALS)]

    def test_a_long_ride_stays_small_enough_for_a_phone(self):
        points = walking(4 * 3600, metres_per_step=20.0, step_seconds=2)  # 4 hours, 144 km.
        route = track.build_route(points)
        assert len(route["segments"][0]) <= track.MAX_POINTS + 2

    @pytest.mark.parametrize("discipline, type_key, expected", [
        ("run", "running", True),
        ("run", "trail_running", True),
        ("bike", "cycling", True),
        ("run", "treadmill_running", False),
        ("run", "indoor_running", False),
        ("bike", "indoor_cycling", False),
        ("bike", "virtual_ride", False),
        ("swim", "lap_swimming", False),
        ("other", "walking", False),
        (None, None, False),
    ])
    def test_which_activities_can_have_a_map(self, discipline, type_key, expected):
        assert track.can_have_map(discipline, type_key) is expected


@pytest.fixture
def client(store, database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    auth.save_dev_session(store.conn, TOKEN)
    store.commit()
    return TestClient(api_module.app)


@pytest.fixture
def run_id(client, store):
    """A synced run whose file holds a fake GPS track."""
    with MockGarmin(TODAY, history_days=20) as server:
        run_sync(store, Client(server.url, GOOD_KEY, delay=0, sleep=lambda _s: None), today=TODAY)
    row = store.conn.execute(
        "select a.activity_id from activity a join activity_file f using (activity_id) "
        "where a.discipline = 'run' limit 1"
    ).fetchone()
    assert row, "The fake watch should have a run with a file."
    gps = build_gps_fit([(i * 3, LAT + i * 0.0001, LON) for i in range(30)])
    store.conn.execute("update activity_file set content = %s where activity_id = %s", (gps, row["activity_id"]))
    store.commit()
    return row["activity_id"]


class TestRouteApi:
    def test_needs_a_session(self, client, run_id):
        assert client.get(f"/api/activities/{run_id}/route").status_code == 401
        wrong = {"Cookie": f"{auth.SESSION_COOKIE}=nope"}
        assert client.get(f"/api/activities/{run_id}/route", headers=wrong).status_code == 401

    def test_returns_the_line_for_a_run(self, client, run_id):
        data = client.get(f"/api/activities/{run_id}/route", headers=AUTH).json()
        assert data["discipline"] == "run"
        assert data["start"] == [LON, LAT]
        assert len(data["segments"]) == 1
        assert data["incomplete"] is False

    def test_is_never_cached(self, client, run_id):
        response = client.get(f"/api/activities/{run_id}/route", headers=AUTH)
        assert response.headers["Cache-Control"] == "no-store"

    def test_unknown_activity_is_404(self, client):
        assert client.get("/api/activities/999999/route", headers=AUTH).status_code == 404

    def test_a_swim_has_no_map(self, client, run_id, store):
        row = store.conn.execute("select activity_id from activity where discipline = 'swim' limit 1").fetchone()
        store.commit()
        assert client.get(f"/api/activities/{row['activity_id']}/route", headers=AUTH).status_code == 422

    def test_a_run_with_no_gps_says_so(self, client, run_id, store):
        store.conn.execute("update activity_file set content = %s where activity_id = %s", (build_fit(), run_id))
        store.commit()
        data = client.get(f"/api/activities/{run_id}/route", headers=AUTH).json()
        assert data["segments"] == []
        assert data["reason"] == track.NO_GPS

    def test_a_run_with_no_file_says_so(self, client, run_id, store):
        store.conn.execute("delete from activity_file where activity_id = %s", (run_id,))
        store.commit()
        data = client.get(f"/api/activities/{run_id}/route", headers=AUTH).json()
        assert data["segments"] == []

    def test_a_damaged_file_is_reported(self, client, run_id, store):
        whole = build_gps_fit([(i * 3, LAT + i * 0.0001, LON) for i in range(30)])
        damaged = whole[:14] + bytes([0x09]) + whole[15:]  # A data message with no definition.
        store.conn.execute("update activity_file set content = %s where activity_id = %s", (damaged, run_id))
        store.commit()
        data = client.get(f"/api/activities/{run_id}/route", headers=AUTH).json()
        assert data["incomplete"] is True

    def test_the_detail_screen_is_told_whether_to_offer_a_map(self, client, run_id, store):
        assert client.get(f"/api/activities/{run_id}", headers=AUTH).json()["map_available"] is True
        store.conn.execute("update activity set type_key = 'treadmill_running' where activity_id = %s", (run_id,))
        store.commit()
        assert client.get(f"/api/activities/{run_id}", headers=AUTH).json()["map_available"] is False

    def test_positions_appear_nowhere_but_the_route(self, client, run_id):
        fragments = (f"{LAT:.2f}", f"{LON:.2f}")
        for path in ("/api/today", "/api/in-depth?days=180", "/api/activities?limit=100",
                     f"/api/activities/{run_id}", "/api/data-quality", "/api/settings"):
            text = client.get(path, headers=AUTH).text
            for fragment in fragments:
                assert fragment not in text, f"{fragment} leaked from {path}"

    def test_opening_a_map_saves_nothing(self, client, run_id, store):
        def row_counts():
            names = store.conn.execute("select tablename from pg_tables where schemaname = 'public'").fetchall()
            counts = {r["tablename"]: store.conn.execute(f'select count(*) as n from "{r["tablename"]}"').fetchone()["n"]
                      for r in names}
            store.commit()
            return counts

        before = row_counts()
        assert client.get(f"/api/activities/{run_id}/route", headers=AUTH).status_code == 200
        assert row_counts() == before
