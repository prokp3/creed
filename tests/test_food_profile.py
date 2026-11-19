"""Body details for auto food targets, and the typical-workout hint from Garmin."""
# The people fixtures come from test_food_api, which pytest sees as tests naming them again.
# ruff: noqa: F811
from __future__ import annotations

from datetime import date, timedelta

import pytest
from test_food_api import TODAY, at, other, owner, people, send  # noqa: F401

from creed.food.nutrition import InvalidFood
from creed.food.profile import clean_profile

FULL = {"sex": "male", "birth_year": 1995, "height_cm": 178, "weight_kg": 72.5, "activity": "some",
        "workout_minutes": 60, "intensity": "moderate", "goal": "maintain"}


class TestProfile:
    def test_a_full_profile(self):
        assert clean_profile(FULL, date(2026, 11, 13)) == {**FULL, "height_cm": 178.0}

    def test_any_field_can_be_missing(self):
        assert clean_profile({"weight_kg": 70, "sex": None}) == {"weight_kg": 70.0}

    @pytest.mark.parametrize("bad", [
        {"sex": "other"}, {"birth_year": 2020}, {"birth_year": 1900}, {"birth_year": 1990.5}, {"height_cm": 50},
        {"weight_kg": 500}, {"weight_kg": True}, {"activity": "athlete"}, {"intensity": "max"}, {"goal": "bulk"},
        {"workout_minutes": 700}, {"protein_per_kg": 5}, {"shoe_size": 9}, "tall",
    ])
    def test_unbelievable_values_are_refused(self, bad):
        with pytest.raises(InvalidFood):
            clean_profile(bad, date(2026, 11, 13))


class TestProfileOverHttp:
    def test_saved_with_the_food_settings(self, owner):
        [result] = send(owner, {"type": "settings.save", "changed_at": at(9), "record": {"profile": FULL}})
        assert result == {"result": "applied"}
        assert owner.get("/api/food/library").json()["settings"]["profile"]["weight_kg"] == 72.5

    def test_a_bad_value_is_refused_and_the_rest_kept(self, owner):
        send(owner, {"type": "settings.save", "changed_at": at(9), "record": {"profile": FULL}})
        [result] = send(owner, {"type": "settings.save", "changed_at": at(10),
                                "record": {"profile": {**FULL, "height_cm": 20}}})
        assert "Height" in result["error"]
        assert owner.get("/api/food/library").json()["settings"]["profile"]["height_cm"] == 178

    def test_body_details_are_private(self, owner, other):
        send(owner, {"type": "settings.save", "changed_at": at(9), "record": {"profile": FULL}})
        assert other.get("/api/food/library").json()["settings"]["profile"] == {}


class TestTrainingHint:
    def _activity(self, store, number, day, minutes):
        store.conn.execute("insert into activity (activity_id, source, discipline, local_date, duration_seconds) "
                           "values (%s, 'api', 'run', %s, %s)", (number, day, minutes * 60))

    def test_the_median_training_day_over_four_weeks(self, owner, store):
        self._activity(store, 1, TODAY, 40)
        self._activity(store, 2, TODAY, 30)  # Same day: 70 minutes in all.
        self._activity(store, 3, TODAY - timedelta(days=3), 50)
        self._activity(store, 4, TODAY - timedelta(days=6), 90)
        self._activity(store, 5, TODAY - timedelta(days=8), 10)  # Under the 20-minute training threshold.
        self._activity(store, 6, TODAY - timedelta(days=40), 300)  # Too long ago.
        store.commit()
        assert owner.get("/api/food/training-hint").json() == {"minutes": 70, "training_days": 3, "days": 28}

    def test_nothing_to_suggest_without_garmin_data(self, other, store):
        self._activity(store, 1, TODAY, 60)
        store.commit()
        assert other.get("/api/food/training-hint").json() == {"minutes": None, "training_days": 0, "days": 28}
