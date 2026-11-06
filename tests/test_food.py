"""The food logger: its arithmetic worked out by hand, and its storage and sync rules against a real Postgres."""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest

from creed import auth
from creed.db import food as db
from creed.food import nutrition, targets
from creed.food.nutrition import InvalidFood
from creed.food.targets import REST, TRAINING, TargetSet

IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 11, 6, 8, 0, tzinfo=IST)
EGG = {"kcal": 143.0, "protein": 12.6, "carbs": 0.7, "fat": 9.5, "sodium": 142.0, "potassium": 138.0,
       "magnesium": 12.0}


def new_id() -> str:
    return str(uuid.uuid4())


def later(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


# ---------------------------------------------------------------- arithmetic

class TestUnits:
    def test_pieces_become_grams(self):
        # 6 eggs at 50 g each.
        assert nutrition.base_amount(6, "piece", "g", {"piece": 50}) == 300

    def test_the_base_is_always_a_unit(self):
        assert nutrition.base_amount(300, "g", "g", {"piece": 50}) == 300

    def test_a_liquid_in_glasses(self):
        assert nutrition.base_amount(1.5, "glass", "ml", {"glass": 250}) == 375

    def test_an_unknown_unit_is_refused(self):
        with pytest.raises(InvalidFood, match="can't be measured in cup"):
            nutrition.base_amount(1, "cup", "g", {"piece": 50})

    def test_grams_of_a_liquid_needs_a_unit(self):
        with pytest.raises(InvalidFood):
            nutrition.base_amount(100, "g", "ml", {})

    @pytest.mark.parametrize("quantity", [0, -1, float("nan"), float("inf"), True, "6"])
    def test_a_quantity_must_be_a_positive_number(self, quantity):
        with pytest.raises(InvalidFood):
            nutrition.base_amount(quantity, "g", "g", {})

    def test_built_in_units_cant_be_redefined(self):
        with pytest.raises(InvalidFood, match="built in"):
            nutrition.clean_units({"g": 1}, "g")


class TestScaling:
    def test_six_eggs(self):
        # 300 g at 143 kcal and 12.6 g protein per 100 g: 3 x 143 = 429 kcal, 3 x 12.6 = 37.8 g.
        values = nutrition.scale(EGG, 300)
        assert values["kcal"] == pytest.approx(429)
        assert values["protein"] == pytest.approx(37.8)

    def test_values_per_unit_become_values_per_100(self):
        # A 30 g scoop with 24 g protein and 120 kcal is 80 g and 400 kcal per 100 g.
        per_100 = nutrition.per_100_from_unit({"protein": 24, "kcal": 120}, 30)
        assert per_100 == pytest.approx({"protein": 80, "kcal": 400})

    def test_converting_and_scaling_back_returns_the_original(self):
        per_100 = nutrition.per_100_from_unit({"protein": 24}, 30)
        assert nutrition.scale(per_100, 30)["protein"] == pytest.approx(24)

    def test_a_value_above_what_food_can_hold_is_refused(self):
        with pytest.raises(InvalidFood, match="between 0 and 150 g"):
            nutrition.clean_nutrients({"protein": 151}, {"protein": "g"})

    def test_a_missing_value_stays_missing(self):
        assert nutrition.clean_nutrients({"protein": 10, "sodium": None}, {"protein": "g", "sodium": "mg"}) == {
            "protein": 10}


class TestTotals:
    def test_entries_add_up(self):
        # Six eggs (300 g, 429 kcal) and a 118 g banana at 89 kcal per 100 g (105.02 kcal).
        entries = [{"nutrients_per_100": EGG, "base_amount": 300},
                   {"nutrients_per_100": {"kcal": 89, "protein": 1.1}, "base_amount": 118}]
        result = nutrition.totals(entries, ["kcal", "protein"])
        assert result.values["kcal"] == pytest.approx(429 + 105.02)
        assert result.values["protein"] == pytest.approx(37.8 + 1.298)
        assert result.incomplete == set()
        assert result.entries == 2

    def test_a_food_without_a_value_marks_that_total_incomplete(self):
        entries = [{"nutrients_per_100": EGG, "base_amount": 100},
                   {"nutrients_per_100": {"kcal": 89}, "base_amount": 100}]
        result = nutrition.totals(entries, ["kcal", "magnesium"])
        assert result.values["magnesium"] == pytest.approx(12)
        assert result.incomplete == {"magnesium"}

    def test_an_empty_day_is_zero_not_missing(self):
        result = nutrition.totals([], ["kcal"])
        assert result.values == {"kcal": 0}
        assert result.entries == 0

    def test_net_calories(self):
        assert nutrition.net_calories(2500, 2800) == -300
        assert nutrition.net_calories(2500, None) is None


class TestDayType:
    def test_a_long_enough_workout_makes_a_training_day(self):
        assert targets.day_type(None, [25 * 60], 20) == targets.DayType(TRAINING, targets.FROM_GARMIN)

    def test_exactly_the_threshold_counts(self):
        assert targets.day_type(None, [20 * 60], 20).day_type == TRAINING

    def test_a_short_one_doesnt(self):
        assert targets.day_type(None, [15 * 60, 10 * 60], 20) == targets.DayType(REST, targets.NO_WORKOUT_YET)

    def test_the_threshold_can_change(self):
        assert targets.day_type(None, [15 * 60], 15).day_type == TRAINING

    def test_no_workout_synced_yet_is_a_rest_day(self):
        assert targets.day_type(None, [], 20).day_type == REST

    def test_an_activity_without_a_duration_doesnt_count(self):
        assert targets.day_type(None, [None], 20).day_type == REST

    def test_your_choice_wins_both_ways(self):
        assert targets.day_type(REST, [90 * 60], 20) == targets.DayType(REST, targets.SET_BY_HAND)
        assert targets.day_type(TRAINING, [], 20) == targets.DayType(TRAINING, targets.SET_BY_HAND)


SETS = (
    TargetSet(TRAINING, date(2026, 10, 1), {"kcal": 3000, "protein": 150}),
    TargetSet(TRAINING, date(2026, 11, 1), {"kcal": 3200, "protein": 160}),
    TargetSet(REST, date(2026, 10, 1), {"kcal": 2400, "protein": 140}),
)


class TestTargetSelection:

    def test_the_newest_set_in_force_on_the_day(self):
        assert targets.targets_for(date(2026, 11, 6), TRAINING, SETS).targets["kcal"] == 3200

    def test_a_past_day_keeps_its_targets(self):
        assert targets.targets_for(date(2026, 10, 31), TRAINING, SETS).targets["kcal"] == 3000

    def test_the_day_type_picks_the_set(self):
        assert targets.targets_for(date(2026, 11, 6), REST, SETS).targets["kcal"] == 2400

    def test_before_any_targets_there_are_none(self):
        assert targets.targets_for(date(2026, 9, 30), TRAINING, SETS) is None

    def test_remaining_goes_negative_when_over(self):
        assert targets.remaining({"kcal": 2400, "protein": 140}, {"kcal": 2500}) == {"kcal": -100, "protein": 140}


# ---------------------------------------------------------------- storage

@pytest.fixture
def conn(store):
    return store.conn


@pytest.fixture
def user(conn):
    """The owner, whose Garmin data the deployment holds."""
    return auth.create_user(conn, is_owner=True)


@pytest.fixture
def other(conn):
    """Someone else with an account on the same deployment."""
    return auth.create_user(conn)


def seed_id(user: str, key: str) -> str:
    """Seeded foods get an id made from their person and their name, as in 0006_food_seed.sql."""
    return str(uuid.UUID(hex=hashlib.md5(f"{user}:{key}".encode()).hexdigest()))


def egg_id(user: str) -> str:
    return seed_id(user, "egg")


def make_food(conn, user, **overrides) -> str:
    record = {"id": new_id(), "name": "Test oats", "base": "g", "nutrients": {"kcal": 380, "protein": 13},
              "units": {"cup": 80}, "default_unit": "cup", **overrides}
    assert db.save_food(conn, user, record, later(0)) == db.APPLIED
    return record["id"]


def egg_entry(conn, user, quantity=6, unit="piece", at=T0, **overrides) -> dict:
    food = db.get_food(conn, user, egg_id(user))
    return {**db.entry_from_food(food, entry_id=new_id(), group_id=new_id(), kind="quick", logged_at=at,
                                 quantity=quantity, unit=unit), **overrides}


class TestSchema:
    def test_every_food_table_is_closed_to_supabases_public_roles(self, conn, user):
        rows = conn.execute(
            "select relname, relrowsecurity from pg_class where relname like 'food%%' and relkind = 'r'"
        ).fetchall()
        # The 8 food tables, the seed template, settings and the reminder record.
        assert len(rows) == 11
        assert all(r["relrowsecurity"] for r in rows)

    def test_the_library_starts_with_staples(self, conn, user):
        foods = db.list_foods(conn, user)
        assert len(foods) == 30
        egg = db.get_food(conn, user, egg_id(user))
        assert egg["units"] == {"piece": 50}
        assert egg["source"] == "seed"
        assert set(egg["nutrients"]) == set(nutrition.BUILT_IN)

    def test_every_seeded_default_unit_exists(self, conn, user):
        for food in db.list_foods(conn, user):
            nutrition.unit_amount(food["default_unit"], food["base"], food["units"])

    def test_seeded_calories_roughly_match_their_macros(self, conn, user):
        # 4 kcal per g of protein and carbs, 9 per g of fat. Fibre and rounding make real foods differ a little.
        for food in db.list_foods(conn, user):
            n = food["nutrients"]
            estimate = 4 * n["protein"] + 4 * n["carbs"] + 9 * n["fat"]
            assert abs(estimate - n["kcal"]) <= max(25, 0.12 * n["kcal"]), food["name"]


class TestFoods:
    def test_values_typed_per_unit_are_stored_per_100(self, conn, user):
        food_id = make_food(conn, user, name="Whey", units={"scoop": 30}, default_unit="scoop", values_per="scoop",
                            nutrients={"protein": 24, "kcal": 120})
        assert db.get_food(conn, user, food_id)["nutrients"] == pytest.approx({"protein": 80, "kcal": 400})

    def test_a_big_serving_isnt_refused_before_converting(self, conn, user):
        # 1,500 kcal for a 400 g serving is 375 per 100 g, which is fine.
        food_id = make_food(conn, user, units={"plate": 400}, default_unit="plate", values_per="plate",
                            nutrients={"kcal": 1500})
        assert db.get_food(conn, user, food_id)["nutrients"]["kcal"] == pytest.approx(375)

    def test_the_default_unit_must_be_one_of_its_units(self, conn, user):
        with pytest.raises(InvalidFood):
            make_food(conn, user, default_unit="scoop")

    def test_one_live_food_per_barcode(self, conn, user):
        make_food(conn, user, barcode="8901234567890")
        with pytest.raises(InvalidFood, match="already has this barcode"):
            make_food(conn, user, barcode="8901234567890")
        assert db.find_by_barcode(conn, user, "8901234567890")["name"] == "Test oats"

    def test_a_deleted_foods_barcode_can_be_reused(self, conn, user):
        first = make_food(conn, user, barcode="8901234567890")
        db.delete_food(conn, user, first, later(1))
        make_food(conn, user, barcode="8901234567890")

    def test_editing_replaces_its_units(self, conn, user):
        food_id = make_food(conn, user)
        db.save_food(conn, user, {"id": food_id, "name": "Test oats", "base": "g", "nutrients": {"kcal": 380},
                            "units": {"bowl": 60}, "default_unit": "bowl"}, later(5))
        assert db.get_food(conn, user, food_id)["units"] == {"bowl": 60}

    def test_search_finds_part_of_a_name(self, conn, user):
        assert [f["name"] for f in db.list_foods(conn, user, "chick")] == ["Chicken breast, cooked", "Chicken breast, raw",
                                                                      "Chickpeas (chana), cooked"]

    def test_favourites_come_first(self, conn, user):
        food = db.get_food(conn, user, egg_id(user))
        assert db.save_food(conn, user, {**food, "favourite": True}, later(1)) == db.APPLIED
        assert db.list_foods(conn, user)[0]["name"] == "Egg, whole"

    def test_a_seeded_food_takes_any_edit_whatever_the_clock_says(self, conn, user):
        food = db.get_food(conn, user, egg_id(user))
        assert db.save_food(conn, user, {**food, "name": "Egg"}, datetime(2020, 1, 1, tzinfo=timezone.utc)) == db.APPLIED


class TestSyncRules:
    def test_an_older_change_doesnt_overwrite_a_newer_one(self, conn, user):
        food_id = make_food(conn, user)
        newer = {"id": food_id, "name": "Newer", "base": "g", "nutrients": {}, "units": {}}
        older = {**newer, "name": "Older"}
        assert db.save_food(conn, user, newer, later(10)) == db.APPLIED
        assert db.save_food(conn, user, older, later(5)) == db.STALE
        assert db.get_food(conn, user, food_id)["name"] == "Newer"

    def test_a_deletion_beats_a_newer_edit(self, conn, user):
        food_id = make_food(conn, user)
        db.delete_food(conn, user, food_id, later(1))
        edit = {"id": food_id, "name": "Edited later", "base": "g", "nutrients": {}, "units": {}}
        assert db.save_food(conn, user, edit, later(60)) == db.DELETED
        assert db.get_food(conn, user, food_id)["name"] == "Test oats"

    def test_sending_an_entry_twice_makes_one(self, conn, user):
        entry = egg_entry(conn, user)
        assert db.save_entries(conn, user, [entry], later(0)) == {entry["id"]: db.APPLIED}
        db.save_entries(conn, user, [entry], later(0))
        assert len(db.entries_between(conn, user, T0.date(), T0.date())) == 1

    def test_deleting_twice_or_something_unknown_is_harmless(self, conn, user):
        entry = egg_entry(conn, user)
        db.save_entries(conn, user, [entry], later(0))
        assert db.delete_entries(conn, user, [entry["id"]], later(1)) == {entry["id"]: db.APPLIED}
        assert db.delete_entries(conn, user, [entry["id"]], later(2)) == {entry["id"]: db.APPLIED}
        unknown = new_id()
        assert db.delete_entries(conn, user, [unknown], later(2)) == {unknown: db.MISSING}

    def test_a_retried_create_doesnt_bring_back_a_deleted_entry(self, conn, user):
        entry = egg_entry(conn, user)
        db.save_entries(conn, user, [entry], later(0))
        db.delete_entries(conn, user, [entry["id"]], later(1))
        assert db.save_entries(conn, user, [entry], later(0)) == {entry["id"]: db.DELETED}
        assert db.entries_between(conn, user, T0.date(), T0.date()) == []

    def test_a_bad_entry_saves_none_of_the_request(self, conn, user):
        good, bad = egg_entry(conn, user), egg_entry(conn, user, unit="cup")
        with pytest.raises(InvalidFood):
            db.save_entries(conn, user, [good, bad], later(0))
        assert db.entries_between(conn, user, T0.date(), T0.date()) == []

    def test_an_entry_for_an_unknown_food_is_refused_and_the_transaction_still_works(self, conn, user):
        entry = egg_entry(conn, user, food_id=new_id())
        with pytest.raises(InvalidFood, match="isn't in your library"):
            db.save_entries(conn, user, [entry], later(0))
        assert db.save_entries(conn, user, [egg_entry(conn, user)], later(1))


class TestEntries:
    def test_six_eggs_logged(self, conn, user):
        entry = egg_entry(conn, user)
        db.save_entries(conn, user, [entry], later(0))
        [saved] = db.entries_between(conn, user, T0.date(), T0.date())
        assert saved["base_amount"] == 300
        assert saved["meal_label"] == "Quick add"
        assert nutrition.entry_nutrients(saved)["kcal"] == pytest.approx(429)

    def test_editing_the_food_later_doesnt_change_the_day(self, conn, user):
        db.save_entries(conn, user, [egg_entry(conn, user)], later(0))
        egg = db.get_food(conn, user, egg_id(user))
        db.save_food(conn, user, {**egg, "nutrients": {**egg["nutrients"], "kcal": 200}, "units": {"piece": 60}}, later(5))
        [saved] = db.entries_between(conn, user, T0.date(), T0.date())
        assert saved["nutrients_per_100"]["kcal"] == 143
        assert saved["base_amount"] == 300

    def test_editing_the_quantity_uses_the_entrys_own_units(self, conn, user):
        entry = egg_entry(conn, user)
        db.save_entries(conn, user, [entry], later(0))
        egg = db.get_food(conn, user, egg_id(user))
        db.save_food(conn, user, {**egg, "units": {"piece": 60}}, later(1))
        db.save_entries(conn, user, [{**entry, "quantity": 4}], later(2))
        [saved] = db.entries_between(conn, user, T0.date(), T0.date())
        assert saved["base_amount"] == 200  # 4 x 50 g, the egg as it was when logged.

    def test_switching_to_grams(self, conn, user):
        entry = egg_entry(conn, user)
        db.save_entries(conn, user, [entry], later(0))
        db.save_entries(conn, user, [{**entry, "quantity": 120, "unit": "g"}], later(1))
        assert db.entries_between(conn, user, T0.date(), T0.date())[0]["base_amount"] == 120

    def test_moving_an_entry_to_another_day(self, conn, user):
        entry = egg_entry(conn, user)
        db.save_entries(conn, user, [entry], later(0))
        db.save_entries(conn, user, [{**entry, "logged_at": T0 - timedelta(days=1)}], later(1))
        assert db.entries_between(conn, user, T0.date(), T0.date()) == []
        assert len(db.entries_between(conn, user, T0.date() - timedelta(days=1), T0.date() - timedelta(days=1))) == 1

    def test_the_day_is_the_one_where_you_were(self):
        # 00:30 in India is still the previous evening in UTC. It belongs to the Indian day.
        late = datetime(2026, 11, 7, 0, 30, tzinfo=IST)
        record = {"id": new_id(), "kind": "quick", "logged_at": late.isoformat(), "quantity": 1, "unit": "g",
                  "food_name": "Dates", "base": "g", "nutrients_per_100": {"kcal": 277}}
        cleaned = db.clean_entry(record)
        assert cleaned["local_date"] == date(2026, 11, 7)
        assert cleaned["utc_offset_minutes"] == 330

    def test_a_time_without_a_zone_is_refused(self):
        with pytest.raises(InvalidFood, match="time zone"):
            db.moment("2026-11-06T08:00:00")

    def test_undo_removes_a_whole_preset_tap(self, conn, user):
        group = new_id()
        entries = [egg_entry(conn, user, group_id=group, kind="preset", meal_label="Dinner"),
                   egg_entry(conn, user, quantity=2, group_id=group, kind="preset", meal_label="Dinner")]
        db.save_entries(conn, user, entries, later(0))
        assert db.delete_group(conn, user, group, later(1)) == 2
        assert db.entries_between(conn, user, T0.date(), T0.date()) == []

    def test_recent_foods(self, conn, user):
        oats = make_food(conn, user)
        db.save_entries(conn, user, [egg_entry(conn, user)], later(0))
        oats_food = db.get_food(conn, user, oats)
        db.save_entries(conn, user, [db.entry_from_food(oats_food, entry_id=new_id(), group_id=new_id(), kind="quick",
                                                  logged_at=later(30), quantity=1)], later(30))
        assert db.recent_food_ids(conn, user) == [oats, egg_id(user)]

    def test_a_deleted_food_drops_out_of_recents_but_its_entries_stay(self, conn, user):
        db.save_entries(conn, user, [egg_entry(conn, user)], later(0))
        db.delete_food(conn, user, egg_id(user), later(1))
        assert db.recent_food_ids(conn, user) == []
        assert len(db.entries_between(conn, user, T0.date(), T0.date())) == 1


class TestPresets:
    def dinner(self, user, **overrides) -> dict:
        return {"id": new_id(), "name": "Dinner", "items": [{"food_id": egg_id(user), "quantity": 6, "unit": "piece"}],
                **overrides}

    def test_save_and_list(self, conn, user):
        preset = self.dinner(user)
        db.save_preset(conn, user, preset, later(0))
        [saved] = db.list_presets(conn, user)
        assert saved["name"] == "Dinner"
        assert saved["items"] == [{"food_id": egg_id(user), "quantity": 6, "unit": "piece", "food_name": "Egg, whole",
                                   "food_deleted": False}]

    def test_a_unit_the_food_doesnt_have_is_refused(self, conn, user):
        with pytest.raises(InvalidFood):
            items = [{"food_id": egg_id(user), "quantity": 1, "unit": "cup"}]
            db.save_preset(conn, user, self.dinner(user, items=items), later(0))

    def test_an_empty_preset_is_refused(self, conn, user):
        with pytest.raises(InvalidFood):
            db.save_preset(conn, user, self.dinner(user, items=[]), later(0))

    def test_reorder(self, conn, user):
        a, b, c = self.dinner(user, name="A"), self.dinner(user, name="B"), self.dinner(user, name="C")
        for p in (a, b, c):
            db.save_preset(conn, user, p, later(0))
        db.reorder_presets(conn, user, [c["id"], a["id"], b["id"]], later(1))
        assert [p["name"] for p in db.list_presets(conn, user)] == ["C", "A", "B"]

    def test_a_preset_says_when_one_of_its_foods_was_deleted(self, conn, user):
        db.save_preset(conn, user, self.dinner(user), later(0))
        db.delete_food(conn, user, egg_id(user), later(1))
        assert db.list_presets(conn, user)[0]["items"][0]["food_deleted"] is True

    def test_deleted_presets_disappear(self, conn, user):
        preset = self.dinner(user)
        db.save_preset(conn, user, preset, later(0))
        db.delete_preset(conn, user, preset["id"], later(1))
        assert db.list_presets(conn, user) == []


class TestNutrientsAndTargets:
    def test_custom_nutrients_behave_like_built_in_ones(self, conn, user):
        caffeine = new_id()
        db.save_nutrient(conn, user, {"id": caffeine, "name": "Caffeine", "unit": "mg"}, later(0))
        food_id = make_food(conn, user, name="Coffee", nutrients={"kcal": 2, caffeine: 40})
        assert db.get_food(conn, user, food_id)["nutrients"][caffeine] == 40
        db.save_targets(conn, user, REST, T0.date(), {"kcal": 2400, caffeine: 300}, later(0))
        assert db.target_sets(conn, user)[0].targets[caffeine] == 300

    def test_rename_keeps_the_unit(self, conn, user):
        caffeine = new_id()
        db.save_nutrient(conn, user, {"id": caffeine, "name": "Caffeine", "unit": "mg"}, later(0))
        db.save_nutrient(conn, user, {"id": caffeine, "name": "Caffeine (coffee)", "unit": "g"}, later(1))
        [row] = [n for n in db.list_nutrients(conn, user) if n["id"] == caffeine]
        assert (row["name"], row["unit"]) == ("Caffeine (coffee)", "mg")

    def test_built_in_ones_can_be_renamed_but_not_deleted(self, conn, user):
        db.save_nutrient(conn, user, {"id": "kcal", "name": "Energy", "unit": "kcal"}, later(0))
        assert db.list_nutrients(conn, user)[0]["name"] == "Energy"
        with pytest.raises(InvalidFood, match="can't|not deleted"):
            db.delete_nutrient(conn, user, "kcal", later(1))

    def test_two_nutrients_cant_share_a_name(self, conn, user):
        with pytest.raises(InvalidFood, match="already have"):
            db.save_nutrient(conn, user, {"id": new_id(), "name": "protein", "unit": "g"}, later(0))

    def test_a_deleted_nutrient_is_no_longer_accepted(self, conn, user):
        creatine = new_id()
        db.save_nutrient(conn, user, {"id": creatine, "name": "Creatine", "unit": "g"}, later(0))
        db.delete_nutrient(conn, user, creatine, later(1))
        assert creatine not in db.nutrient_units(conn, user)
        with pytest.raises(InvalidFood, match="Unknown nutrient"):
            make_food(conn, user, nutrients={creatine: 5})

    def test_new_targets_dont_change_past_days(self, conn, user):
        db.save_targets(conn, user, TRAINING, date(2026, 10, 1), {"kcal": 3000}, later(0))
        db.save_targets(conn, user, TRAINING, date(2026, 11, 1), {"kcal": 3200}, later(1))
        sets = db.target_sets(conn, user)
        assert targets.targets_for(date(2026, 10, 15), TRAINING, sets).targets == {"kcal": 3000}
        assert targets.targets_for(date(2026, 11, 6), TRAINING, sets).targets == {"kcal": 3200}

    def test_a_target_must_be_positive(self, conn, user):
        with pytest.raises(InvalidFood):
            db.save_targets(conn, user, REST, T0.date(), {"kcal": 0}, later(0))

    def test_day_types_from_synced_activities_and_overrides(self, conn, user):
        day = T0.date()
        conn.execute(
            "insert into activity (activity_id, source, discipline, local_date, duration_seconds) values "
            "(1, 'api', 'run', %s, 1500), (2, 'api', 'swim', %s, 600)",
            (day - timedelta(days=2), day - timedelta(days=1)),
        )
        db.set_day_type(conn, user, day, TRAINING, later(0))
        days = db.day_types(conn, user, day - timedelta(days=3), day, 20)
        assert [d.day_type for d in days.values()] == [REST, TRAINING, REST, TRAINING]
        assert days[day].how == targets.SET_BY_HAND

    def test_going_back_to_automatic(self, conn, user):
        db.set_day_type(conn, user, T0.date(), REST, later(0))
        db.set_day_type(conn, user, T0.date(), None, later(1))
        assert db.day_types(conn, user, T0.date(), T0.date(), 20)[T0.date()].how == targets.NO_WORKOUT_YET


class TestPeopleAreKeptApart:
    """Two people on one deployment. Each check is made twice: through the code, and by the database itself."""

    def test_each_person_gets_their_own_starter_library(self, conn, user, other):
        assert len(db.list_foods(conn, user)) == len(db.list_foods(conn, other)) == 30
        assert egg_id(user) != egg_id(other)

    def test_someone_elses_food_cant_be_seen(self, conn, user, other):
        food_id = make_food(conn, user, name="Mine")
        assert db.get_food(conn, other, food_id) is None
        assert "Mine" not in [f["name"] for f in db.list_foods(conn, other)]

    def test_someone_elses_food_cant_be_edited_or_deleted(self, conn, user, other):
        food_id = make_food(conn, user, name="Mine")
        # The same id sent by someone else makes their own food. It never touches the first one.
        db.save_food(conn, other, {"id": food_id, "name": "Theirs", "base": "g", "nutrients": {}}, later(5))
        assert db.delete_food(conn, other, food_id, later(6)) == db.APPLIED  # Their copy, not mine.
        mine = db.get_food(conn, user, food_id)
        assert mine["name"] == "Mine"
        assert mine["deleted_at"] is None

    def test_entries_cant_point_at_someone_elses_food(self, conn, user, other):
        entry = egg_entry(conn, user)
        with pytest.raises(InvalidFood, match="isn't in your library"):
            db.save_entries(conn, other, [entry], later(0))

    def test_presets_cant_use_someone_elses_food(self, conn, user, other):
        preset = {"id": new_id(), "name": "Borrowed", "items": [{"food_id": egg_id(user), "quantity": 1}]}
        with pytest.raises(InvalidFood, match="isn't in your library"):
            db.save_preset(conn, other, preset, later(0))

    def test_days_targets_and_nutrients_are_separate(self, conn, user, other):
        db.save_entries(conn, user, [egg_entry(conn, user)], later(0))
        db.save_targets(conn, user, REST, T0.date(), {"kcal": 2400}, later(0))
        db.set_day_type(conn, user, T0.date(), TRAINING, later(0))
        db.save_nutrient(conn, user, {"id": new_id(), "name": "Caffeine", "unit": "mg"}, later(0))
        assert db.entries_between(conn, other, T0.date(), T0.date()) == []
        assert db.target_sets(conn, other) == []
        assert db.day_type_overrides(conn, other, T0.date(), T0.date()) == {}
        assert "Caffeine" not in [n["name"] for n in db.list_nutrients(conn, other)]
        assert db.last_logged_at(conn, other) is None

    def test_undo_cant_reach_someone_elses_entries(self, conn, user, other):
        entry = egg_entry(conn, user)
        db.save_entries(conn, user, [entry], later(0))
        assert db.delete_group(conn, other, entry["group_id"], later(1)) == 0
        assert db.delete_entries(conn, other, [entry["id"]], later(1)) == {entry["id"]: db.MISSING}
        assert len(db.entries_between(conn, user, T0.date(), T0.date())) == 1

    def test_the_database_hides_other_peoples_rows_even_from_a_careless_query(self, conn, user, other):
        make_food(conn, user, name="Mine")
        with db.as_user(conn, other):
            names = {r["name"] for r in conn.execute("select name from food").fetchall()}
            assert "Mine" not in names
            assert conn.execute("select count(distinct user_id) as n from food").fetchone()["n"] == 1

    def test_the_database_refuses_a_row_written_for_someone_else(self, conn, user, other):
        with db.as_user(conn, other):
            conn.execute("savepoint attempt")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("insert into food (user_id, id, name, base, default_unit, source) "
                             "values (%s, %s, 'Planted', 'g', 'g', 'manual')", (user, new_id()))
            conn.execute("rollback to savepoint attempt")

    def test_garmin_tables_are_closed_to_the_food_role(self, conn, user):
        conn.execute("insert into activity (activity_id, source, discipline, local_date, duration_seconds) "
                     "values (1, 'api', 'run', %s, 1500)", (T0.date(),))
        with db.as_user(conn, user):
            conn.execute("savepoint attempt")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("select * from activity")
            conn.execute("rollback to savepoint attempt")

    def test_acting_ends_with_the_block(self, conn, user):
        with db.as_user(conn, user):
            assert conn.execute("select current_user as u").fetchone()["u"] == db.MEMBER_ROLE
        assert conn.execute("select current_user as u").fetchone()["u"] != db.MEMBER_ROLE
        assert conn.execute("select current_setting('creed.user_id', true) as v").fetchone()["v"] == ""

    def test_one_connection_cant_act_for_two_people_at_once(self, conn, user, other):
        with db.as_user(conn, user), pytest.raises(RuntimeError):
            db.list_foods(conn, other)

    def test_garmin_data_cant_be_read_while_acting_for_someone(self, conn, user):
        with db.as_user(conn, user), pytest.raises(RuntimeError):
            db.day_types(conn, user, T0.date(), T0.date(), 20)

    def test_only_the_owners_workouts_decide_training_days(self, conn, user, other):
        conn.execute("insert into activity (activity_id, source, discipline, local_date, duration_seconds) "
                     "values (1, 'api', 'run', %s, 3600)", (T0.date(),))
        assert db.day_types(conn, user, T0.date(), T0.date(), 20)[T0.date()].day_type == TRAINING
        assert db.day_types(conn, other, T0.date(), T0.date(), 20)[T0.date()].day_type == REST

    def test_deleting_a_person_deletes_their_food_data(self, conn, user, other):
        db.save_entries(conn, other, [egg_entry(conn, other)], later(0))
        conn.execute("delete from app_user where id = %s", (other,))
        assert conn.execute("select count(*) as n from food where user_id = %s", (other,)).fetchone()["n"] == 0
        assert len(db.list_foods(conn, user)) == 30
