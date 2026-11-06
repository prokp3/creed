"""The food routes over HTTP, against a real Postgres: logging, undo, the day view, and keeping people apart."""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from creed import auth, config
from creed.api import app as api_module
from creed.food import day as food_day
from creed.food import targets
from creed.food.nutrition import Totals
from creed.food.targets import DayType, TargetSet

IST = timezone(timedelta(hours=5, minutes=30))
OWNER_TOKEN = "owner-session-token"
OTHER_TOKEN = "other-session-token"
TODAY = config.local_today()


def new_id() -> str:
    return str(uuid.uuid4())


def seed_id(user: str, key: str) -> str:
    return str(uuid.UUID(hex=hashlib.md5(f"{user}:{key}".encode()).hexdigest()))


def at(hour: int, minute: int = 0, day: date = TODAY) -> str:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST).isoformat()


@pytest.fixture
def people(store, database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    owner = auth.owner_id(store.conn, create=True)
    other = auth.create_user(store.conn)
    auth.save_dev_session(store.conn, OWNER_TOKEN, owner)
    auth.save_dev_session(store.conn, OTHER_TOKEN, other)
    store.commit()
    return {"owner": owner, "other": other}


@pytest.fixture
def owner(people):
    client = TestClient(api_module.app)
    client.cookies.set(auth.SESSION_COOKIE, OWNER_TOKEN)
    client.user_id = people["owner"]
    return client


@pytest.fixture
def other(people):
    client = TestClient(api_module.app)
    client.cookies.set(auth.SESSION_COOKIE, OTHER_TOKEN)
    client.user_id = people["other"]
    return client


def send(client, *changes) -> list[dict]:
    response = client.post("/api/food/changes", json={"changes": list(changes)})
    assert response.status_code == 200, response.text
    return response.json()["results"]


def eggs(client, quantity=6, when=None, group=None, label=None, kind="quick", entry_id=None) -> dict:
    """Six eggs, built the way the app builds an entry from its copy of the library."""
    library = client.get("/api/food/library").json()
    egg = next(f for f in library["foods"] if f["id"] == seed_id(client.user_id, "egg"))
    entry_id = entry_id or new_id()
    return {"id": entry_id, "group_id": group or entry_id, "kind": kind, "meal_label": label, "food_id": egg["id"],
            "logged_at": when or at(20), "quantity": quantity, "unit": "piece", "food_name": egg["name"],
            "base": egg["base"], "nutrients_per_100": egg["nutrients"], "unit_amounts": egg["units"]}


def log(client, *entries, when=None):
    return send(client, {"type": "entries.save", "records": list(entries), "changed_at": when or at(20)})


def day(client, on: date = TODAY) -> dict:
    response = client.get("/api/food/day", params={"date": on.isoformat()})
    assert response.status_code == 200, response.text
    return response.json()


class TestAccess:
    @pytest.mark.parametrize("method,path", [("get", "/api/food/library"), ("get", "/api/food/day"),
                                             ("post", "/api/food/changes")])
    def test_food_needs_a_session(self, people, method, path):
        assert getattr(TestClient(api_module.app), method)(path).status_code == 401

    def test_changes_from_another_site_are_refused(self, owner, monkeypatch):
        monkeypatch.setenv(auth.ORIGIN_ENV_VAR, "https://creed.example")
        response = owner.post("/api/food/changes", json={"changes": []}, headers={"Origin": "https://evil.example"})
        assert response.status_code == 403

    def test_someone_without_garmin_data_can_still_log_food(self, other):
        assert other.get("/api/today").status_code == 403
        assert other.get("/api/food/library").status_code == 200

    def test_nothing_personal_is_cached(self, owner):
        assert owner.get("/api/food/day").headers["Cache-Control"] == "no-store"


class TestLibrary:
    def test_a_new_person_starts_with_staples_and_nutrients(self, other):
        library = other.get("/api/food/library").json()
        assert len(library["foods"]) == 30
        assert [n["id"] for n in library["nutrients"]] == ["kcal", "protein", "carbs", "fat", "sodium",
                                                           "potassium", "magnesium"]
        assert library["presets"] == []
        assert library["recent_food_ids"] == []
        assert library["targets"] == []

    def test_target_sets_come_with_the_library(self, owner):
        send(owner, {"type": "targets.save", "day_type": "training", "effective_from": "2026-11-01",
                     "targets": {"kcal": 3000, "protein": 160}, "changed_at": at(9)},
             {"type": "targets.save", "day_type": "rest", "effective_from": "2026-11-01",
              "targets": {"kcal": 2400}, "changed_at": at(9)})
        assert owner.get("/api/food/library").json()["targets"] == [
            {"day_type": "rest", "effective_from": "2026-11-01", "targets": {"kcal": 2400.0}},
            {"day_type": "training", "effective_from": "2026-11-01", "targets": {"kcal": 3000.0, "protein": 160.0}},
        ]

    def test_a_saved_food_appears(self, owner):
        food_id = new_id()
        [result] = send(owner, {"type": "food.save", "changed_at": at(9), "record": {
            "id": food_id, "name": "Whey, my tub", "base": "g", "units": {"scoop": 32}, "default_unit": "scoop",
            "values_per": "scoop", "nutrients": {"kcal": 120, "protein": 24}, "barcode": "8901234567890"}})
        assert result == {"result": "applied"}
        saved = next(f for f in owner.get("/api/food/library").json()["foods"] if f["id"] == food_id)
        assert saved["nutrients"]["protein"] == pytest.approx(75)  # 24 g in 32 g is 75 g per 100 g.


class TestLogging:
    def test_six_eggs_for_dinner(self, owner):
        entry = eggs(owner)
        assert log(owner, entry) == [{"result": {entry["id"]: "applied"}}]
        view = day(owner)
        assert view["totals"]["kcal"] == pytest.approx(429)
        assert view["totals"]["protein"] == pytest.approx(37.8)
        [meal] = view["meals"]
        assert meal["label"] == "Quick add"
        assert meal["entries"][0]["base_amount"] == 300

    def test_a_preset_tap_is_one_meal_and_one_undo(self, owner):
        group = new_id()
        log(owner, eggs(owner, group=group, label="Dinner", kind="preset"),
            eggs(owner, quantity=2, group=group, label="Dinner", kind="preset"))
        [meal] = day(owner)["meals"]
        assert meal["label"] == "Dinner"
        assert len(meal["entries"]) == 2
        assert meal["totals"]["kcal"] == pytest.approx(429 + 143)
        assert send(owner, {"type": "group.delete", "group_id": group, "changed_at": at(20, 1)}) == [{"result": 2}]
        assert day(owner)["meals"] == []

    def test_meals_are_in_time_order(self, owner):
        log(owner, eggs(owner, when=at(20), label="Dinner", kind="preset"))
        log(owner, eggs(owner, when=at(8), label="Breakfast", kind="preset"))
        assert [m["label"] for m in day(owner)["meals"]] == ["Breakfast", "Dinner"]

    def test_sending_the_same_tap_twice_logs_it_once(self, owner):
        entry = eggs(owner)
        log(owner, entry)
        log(owner, entry)
        assert len(day(owner)["meals"]) == 1

    def test_editing_an_entry_updates_the_totals(self, owner):
        entry = eggs(owner)
        log(owner, entry)
        log(owner, {**entry, "quantity": 3}, when=at(20, 5))
        assert day(owner)["totals"]["kcal"] == pytest.approx(214.5)

    def test_moving_an_entry_to_yesterday(self, owner):
        entry = eggs(owner)
        log(owner, entry)
        log(owner, {**entry, "logged_at": at(20, day=TODAY - timedelta(days=1))}, when=at(20, 5))
        assert day(owner)["meals"] == []
        assert len(day(owner, TODAY - timedelta(days=1))["meals"]) == 1

    def test_one_bad_change_doesnt_stop_the_others(self, owner):
        good = eggs(owner)
        results = send(owner,
                       {"type": "entries.save", "records": [{**eggs(owner), "unit": "cup"}], "changed_at": at(20)},
                       {"type": "nonsense"},
                       {"type": "entries.save", "records": [good], "changed_at": at(20)})
        assert "error" in results[0]
        assert results[1] == {"error": "Unknown kind of change."}
        assert results[2] == {"result": {good["id"]: "applied"}}
        assert len(day(owner)["meals"]) == 1

    def test_a_change_without_a_time_is_refused(self, owner):
        [result] = send(owner, {"type": "food.delete", "id": new_id()})
        assert result == {"error": "Every change needs the time it was made."}

    def test_a_late_delete_beats_an_earlier_edit_arriving_after_it(self, owner):
        entry = eggs(owner)
        log(owner, entry)
        send(owner, {"type": "entries.delete", "ids": [entry["id"]], "changed_at": at(21)})
        [result] = log(owner, {**entry, "quantity": 2}, when=at(20, 30))
        assert result == {"result": {entry["id"]: "deleted"}}
        assert day(owner)["meals"] == []

    def test_an_empty_or_huge_batch_is_refused(self, owner):
        assert owner.post("/api/food/changes", json={"changes": []}).status_code == 422
        assert owner.post("/api/food/changes", json={"changes": [{}] * 201}).status_code == 422
        assert owner.post("/api/food/changes", content=b"not json").status_code == 422


class TestDayView:
    def test_rings_use_that_days_targets(self, owner):
        send(owner, {"type": "targets.save", "day_type": "rest", "effective_from": (TODAY - timedelta(days=30)).isoformat(),
                     "targets": {"kcal": 2400, "protein": 140}, "changed_at": at(7)})
        send(owner, {"type": "targets.save", "day_type": "rest", "effective_from": TODAY.isoformat(),
                     "targets": {"kcal": 2200, "protein": 150}, "changed_at": at(7)})
        log(owner, eggs(owner))
        view = day(owner)
        assert view["day_type"]["type"] == "rest"
        assert view["targets_from"] == TODAY.isoformat()
        kcal = next(r for r in view["rings"] if r["id"] == "kcal")
        assert kcal["target"] == 2200
        assert kcal["remaining"] == pytest.approx(2200 - 429)
        assert day(owner, TODAY - timedelta(days=1))["rings"][0]["target"] == 2400

    def test_without_targets_there_are_no_rings(self, owner):
        assert day(owner)["rings"] == []

    def test_a_day_set_by_hand_uses_training_targets(self, owner):
        send(owner, {"type": "targets.save", "day_type": "training", "effective_from": TODAY.isoformat(),
                     "targets": {"kcal": 3000}, "changed_at": at(7)},
             {"type": "day_type.set", "date": TODAY.isoformat(), "day_type": "training", "changed_at": at(7)})
        view = day(owner)
        assert view["day_type"] == {"type": "training", "how": "override",
                                    "threshold_minutes": targets.DEFAULT_TRAINING_MINUTES}
        assert view["rings"][0]["target"] == 3000

    def test_a_workout_synced_from_garmin_makes_a_training_day(self, owner, store):
        store.conn.execute("insert into activity (activity_id, source, discipline, local_date, duration_seconds) "
                           "values (1, 'api', 'run', %s, 2400)", (TODAY,))
        store.commit()
        assert day(owner)["day_type"]["type"] == "training"

    def test_the_owner_sees_garmins_burn_as_an_estimate(self, owner, store):
        store.conn.execute("insert into daily_metric (calendar_date, metric, source, value_num) "
                           "values (%s, 'calories_total', 'api', 2600)", (TODAY,))
        store.commit()
        log(owner, eggs(owner))
        balance = day(owner)["balance"]
        assert balance["burned_kcal"] == 2600
        assert balance["net_kcal"] == pytest.approx(429 - 2600)
        assert balance["estimate"] is True
        assert balance["so_far"] is True
        assert day(owner, TODAY - timedelta(days=1))["balance"]["so_far"] is False

    def test_no_burn_figure_means_no_balance(self, owner):
        assert day(owner)["balance"]["net_kcal"] is None

    def test_someone_else_never_gets_the_owners_garmin_figures(self, other, store):
        store.conn.execute("insert into daily_metric (calendar_date, metric, source, value_num) "
                           "values (%s, 'calories_total', 'api', 2600)", (TODAY,))
        store.conn.execute("insert into activity (activity_id, source, discipline, local_date, duration_seconds) "
                           "values (1, 'api', 'run', %s, 2400)", (TODAY,))
        store.commit()
        view = day(other)
        assert view["balance"]["burned_kcal"] is None
        assert view["day_type"]["type"] == "rest"

    def test_a_bad_date_is_refused(self, owner):
        assert owner.get("/api/food/day", params={"date": "yesterday"}).status_code == 422


class TestPeopleOverHttp:
    def test_one_persons_log_is_invisible_to_another(self, owner, other):
        log(owner, eggs(owner))
        assert day(other)["meals"] == []

    def test_an_entry_sent_with_someone_elses_food_is_refused(self, owner, other):
        [result] = log(other, eggs(owner))
        assert "isn't in your library" in result["error"]

    def test_deleting_someone_elses_entry_does_nothing(self, owner, other):
        entry = eggs(owner)
        log(owner, entry)
        assert send(other, {"type": "entries.delete", "ids": [entry["id"]], "changed_at": at(21)}) == [
            {"result": {entry["id"]: "missing"}}]
        assert len(day(owner)["meals"]) == 1


class TestShaping:
    """day_view itself, worked out by hand."""

    def test_rings_carry_eaten_target_remaining_and_gaps(self):
        nutrients = [{"id": "kcal", "name": "Calories", "unit": "kcal"}, {"id": "magnesium", "name": "Magnesium",
                                                                           "unit": "mg"}]
        totals = Totals(values={"kcal": 1800.0, "magnesium": 120.0}, incomplete={"magnesium"})
        rings = food_day.rings(nutrients, totals, TargetSet("rest", TODAY, {"kcal": 2400, "magnesium": 400}))
        assert rings[0] == {"id": "kcal", "name": "Calories", "unit": "kcal", "eaten": 1800.0, "target": 2400,
                            "remaining": 600.0, "fraction": 0.75, "incomplete": False}
        assert rings[1]["incomplete"] is True

    def test_an_empty_day(self):
        view = food_day.day_view(day=TODAY, today=TODAY, entries=[], nutrients=[{"id": "kcal", "name": "Calories",
                                                                                 "unit": "kcal"}],
                                 day_type=DayType("rest", targets.NO_WORKOUT_YET), threshold_minutes=20,
                                 target_set=None, burned_kcal=None)
        assert view["totals"] == {"kcal": 0.0}
        assert view["meals"] == []
        assert view["balance"]["net_kcal"] is None
