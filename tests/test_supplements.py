"""Supplements you take every day, ticked off by day (not by time), over HTTP against a real Postgres."""
# The people fixtures come from test_food_api, which pytest sees as tests naming them again.
# ruff: noqa: F811
from __future__ import annotations

from datetime import timedelta

import pytest
from test_food_api import TODAY, at, new_id, other, owner, people, send  # noqa: F401

from creed.db import food
from creed.food.nutrition import InvalidFood


def add(client, name, dose=None, supplement_id=None, when=None, schedule=None):
    supplement_id = supplement_id or new_id()
    record = {"id": supplement_id, "name": name, "dose": dose}
    if schedule is not None:
        record["schedule"] = schedule
    [result] = send(client, {"type": "supplement.save", "changed_at": when or at(8), "record": record})
    return supplement_id, result


def tick(client, supplement_id, taken=True, day=TODAY, when=None):
    [result] = send(client, {"type": "supplement.taken", "supplement_id": supplement_id, "date": day.isoformat(),
                             "taken": taken, "changed_at": when or at(9)})
    return result


def taken_on(client, day=TODAY):
    return client.get(f"/api/food/day?date={day.isoformat()}").json()["supplements_taken"]


class TestSupplementList:
    def test_added_in_order_and_kept_in_the_library(self, owner):
        omega, result = add(owner, "Omega-3", "1 capsule")
        assert result == {"result": "applied"}
        vit_d, _ = add(owner, "Vitamin D3", "2000 IU")
        listed = owner.get("/api/food/library").json()["supplements"]
        assert [(s["id"], s["name"], s["dose"]) for s in listed] == [
            (omega, "Omega-3", "1 capsule"), (vit_d, "Vitamin D3", "2000 IU")]

    def test_dose_is_optional_and_blank_means_none(self, owner):
        add(owner, "Creatine", "  ")
        [listed] = owner.get("/api/food/library").json()["supplements"]
        assert listed["dose"] is None

    def test_renamed_keeping_its_place(self, owner):
        first, _ = add(owner, "Omega 3")
        add(owner, "Magnesium")
        add(owner, "Omega-3", "2 capsules", supplement_id=first, when=at(10))
        listed = owner.get("/api/food/library").json()["supplements"]
        assert [s["name"] for s in listed] == ["Omega-3", "Magnesium"]

    def test_the_same_name_twice_is_refused(self, owner):
        add(owner, "Vitamin D3")
        _, result = add(owner, "vitamin d3")
        assert "already have" in result["error"]

    def test_bad_records_are_refused(self, owner):
        for record in ({"id": new_id(), "name": ""}, {"id": "not-an-id", "name": "Iron"},
                       {"id": new_id(), "name": "x" * 41}, {"id": new_id(), "name": "Iron", "dose": "y" * 41}):
            [result] = send(owner, {"type": "supplement.save", "changed_at": at(8), "record": record})
            assert "error" in result

    def test_an_older_edit_loses(self, owner):
        supplement_id, _ = add(owner, "Iron", when=at(10))
        _, result = add(owner, "Iron old", supplement_id=supplement_id, when=at(9))
        assert result == {"result": "stale"}

    def test_deleted_stays_deleted_and_drops_out_of_the_day(self, owner):
        supplement_id, _ = add(owner, "Zinc")
        tick(owner, supplement_id)
        [result] = send(owner, {"type": "supplement.delete", "id": supplement_id, "changed_at": at(11)})
        assert result == {"result": "applied"}
        assert owner.get("/api/food/library").json()["supplements"] == []
        assert taken_on(owner) == []
        _, again = add(owner, "Zinc again", supplement_id=supplement_id, when=at(12))
        assert again == {"result": "deleted"}
        assert tick(owner, supplement_id, when=at(12)) == {"result": "deleted"}

    def test_there_is_a_limit(self, owner, monkeypatch):
        monkeypatch.setattr(food, "MAX_SUPPLEMENTS", 2)
        add(owner, "A")
        add(owner, "B")
        _, result = add(owner, "C")
        assert "up to 2" in result["error"]


class TestSchedule:
    @pytest.mark.parametrize(("given", "kept"), [
        (None, {"kind": "daily"}),
        ({"kind": "daily", "extra": 1}, {"kind": "daily"}),
        ({"kind": "days", "days": [4, 0, 2, 2]}, {"kind": "days", "days": [0, 2, 4]}),
        ({"kind": "days", "days": list(range(7))}, {"kind": "daily"}),
        ({"kind": "weekly", "times": 1}, {"kind": "weekly", "times": 1}),
    ])
    def test_cleaned(self, given, kept):
        assert food.clean_schedule(given) == kept

    @pytest.mark.parametrize("bad", [
        "daily", {"kind": "monthly"}, {"kind": "days", "days": []}, {"kind": "days", "days": [7]},
        {"kind": "days", "days": [True]}, {"kind": "days"}, {"kind": "weekly", "times": 0},
        {"kind": "weekly", "times": 7}, {"kind": "weekly", "times": 2.5},
    ])
    def test_refused(self, bad):
        with pytest.raises(InvalidFood):
            food.clean_schedule(bad)

    def test_saved_and_changed(self, owner):
        iron, _ = add(owner, "Iron", schedule={"kind": "days", "days": [0, 3]})
        add(owner, "Vitamin D3")
        listed = {s["name"]: s["schedule"] for s in owner.get("/api/food/library").json()["supplements"]}
        assert listed == {"Iron": {"kind": "days", "days": [0, 3]}, "Vitamin D3": {"kind": "daily"}}
        add(owner, "Iron", supplement_id=iron, schedule={"kind": "weekly", "times": 2}, when=at(10))
        first = owner.get("/api/food/library").json()["supplements"][0]
        assert first["schedule"] == {"kind": "weekly", "times": 2}

    def test_a_bad_schedule_is_refused_over_http(self, owner):
        _, result = add(owner, "Iron", schedule={"kind": "weekly", "times": 9})
        assert "1 to 6" in result["error"]

    def test_the_day_brings_its_whole_week(self, owner):
        omega, _ = add(owner, "Omega-3", schedule={"kind": "weekly", "times": 2})
        monday = TODAY - timedelta(days=TODAY.weekday())
        sunday = monday + timedelta(days=6)
        tick(owner, omega, day=monday)
        tick(owner, omega, day=sunday)
        tick(owner, omega, day=monday - timedelta(days=1))  # Last week: left out.
        day = owner.get(f"/api/food/day?date={TODAY.isoformat()}").json()
        assert day["supplements_week"] == {monday.isoformat(): [omega], sunday.isoformat(): [omega]}


class TestTakenByDay:
    def test_ticked_for_one_day_only(self, owner):
        omega, _ = add(owner, "Omega-3")
        vit_d, _ = add(owner, "Vitamin D3")
        assert tick(owner, vit_d) == {"result": "applied"}
        assert taken_on(owner) == [vit_d]
        assert taken_on(owner, TODAY - timedelta(days=1)) == []
        tick(owner, omega, when=at(9, 5))
        assert taken_on(owner) == [omega, vit_d]

    def test_a_past_day_can_be_ticked(self, owner):
        omega, _ = add(owner, "Omega-3")
        yesterday = TODAY - timedelta(days=1)
        tick(owner, omega, day=yesterday)
        assert taken_on(owner, yesterday) == [omega]
        assert taken_on(owner) == []

    def test_unticked(self, owner):
        omega, _ = add(owner, "Omega-3")
        tick(owner, omega, when=at(9))
        assert tick(owner, omega, taken=False, when=at(10)) == {"result": "applied"}
        assert taken_on(owner) == []

    def test_a_late_tick_cant_beat_a_newer_untick(self, owner):
        omega, _ = add(owner, "Omega-3")
        tick(owner, omega, taken=False, when=at(10))
        assert tick(owner, omega, taken=True, when=at(9)) == {"result": "stale"}
        assert taken_on(owner) == []

    def test_sending_the_same_tick_twice_is_fine(self, owner):
        omega, _ = add(owner, "Omega-3")
        tick(owner, omega)
        assert tick(owner, omega) == {"result": "applied"}
        assert taken_on(owner) == [omega]

    def test_unknown_or_bad_ticks_are_refused(self, owner):
        assert "isn't in your list" in tick(owner, new_id())["error"]
        omega, _ = add(owner, "Omega-3")
        assert "error" in tick(owner, omega, taken="yes")
        [result] = send(owner, {"type": "supplement.taken", "supplement_id": omega, "date": "today",
                                "taken": True, "changed_at": at(9)})
        assert "error" in result


class TestPrivacy:
    def test_each_person_sees_only_their_own(self, owner, other):
        omega, _ = add(owner, "Omega-3")
        tick(owner, omega)
        assert other.get("/api/food/library").json()["supplements"] == []
        assert taken_on(other) == []
        # Someone else's supplement can't be ticked, renamed or deleted.
        assert "isn't in your list" in tick(other, omega)["error"]
        _, result = add(other, "Mine now", supplement_id=omega)
        assert result == {"result": "applied"}  # A separate record: ids are per person.
        [deleted] = send(other, {"type": "supplement.delete", "id": omega, "changed_at": at(12)})
        assert deleted == {"result": "applied"}
        assert [s["name"] for s in owner.get("/api/food/library").json()["supplements"]] == ["Omega-3"]
        assert taken_on(owner) == [omega]
