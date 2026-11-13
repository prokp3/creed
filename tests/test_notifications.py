"""Training notifications: Recovery, workout recaps, load spikes, the weekly summary, the Garmin key and failed syncs.
The rules on their own first, then the whole path against a real Postgres with a fake phone."""
# The people fixtures come from test_food_api, which pytest sees as tests naming them again.
# ruff: noqa: F811
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_food_api import IST, at, eggs, log, other, owner, people  # noqa: F401
from test_food_more import _phone, vapid  # noqa: F401

from creed import alerts, notify, push
from creed import settings as app_settings
from creed.api import app as api_module
from creed.db import push as db_push

KOLKATA = ZoneInfo("Asia/Kolkata")
# A Sunday.
SUNDAY = date(2026, 11, 15)


def local(hour: int, minute: int = 0, day: date = SUNDAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


# ---------------------------------------------------------------- the rules

class TestRecoveryRule:
    def test_due_for_three_hours_from_your_time(self):
        assert alerts.recovery(local(7, 29), "07:30", 70, "high") is None
        assert alerts.recovery(local(7, 30), "07:30", 70, "high") is not None
        assert alerts.recovery(local(10, 29), "07:30", 70, "high") is not None
        assert alerts.recovery(local(10, 30), "07:30", 70, "high") is None

    def test_no_score_means_nothing_rather_than_a_guess(self):
        assert alerts.recovery(local(8), "07:30", None, "none") is None

    def test_wording_compares_with_your_normal(self):
        def body(score, confidence="high"):
            return alerts.recovery(local(8), "07:30", score, confidence).message["body"]
        assert body(72).startswith("Above your normal")
        assert body(50).startswith("Around your normal")
        assert body(38).startswith("Below your normal")
        assert body(20).startswith("Well below your normal")
        assert "Low confidence" in body(50, "low")

    def test_one_per_day(self):
        note = alerts.recovery(local(8), "07:30", 64.6, "medium")
        assert note.ref == "2026-11-15"
        assert note.message["title"] == "Recovery 65 of 100"
        assert note.message["url"] == "/#/in-depth"


class TestWorkoutRule:
    def test_one_workout(self):
        message = alerts.workout([{"activity_id": 7, "discipline": "run", "duration_seconds": 3120,
                                   "distance_m": 8420, "load": 63.6}])
        assert message["title"] == "Run synced"
        assert message["body"] == "52 min · 8.4 km · load 64. Remember your recovery meal."
        assert message["url"] == "/#/activities/7"

    def test_a_short_swim_without_a_load(self):
        message = alerts.workout([{"activity_id": 8, "discipline": "swim", "duration_seconds": 1500,
                                   "distance_m": 1500, "load": None}])
        assert message["body"] == "25 min · 1,500 m."

    def test_several_at_once_make_one_notification(self):
        message = alerts.workout([
            {"activity_id": 1, "discipline": "swim", "duration_seconds": 1800, "distance_m": 1500, "load": 30},
            {"activity_id": 2, "discipline": "bike", "duration_seconds": 5400, "distance_m": 40000, "load": 90},
            {"activity_id": 3, "discipline": "other", "duration_seconds": 600, "distance_m": None, "load": None},
        ])
        assert message["title"] == "3 workouts synced"
        assert message["body"] == "Swim 30 min · Bike 1 h 30 min · Workout 10 min. Load 120. Remember your recovery meal."
        assert message["url"] == "/#/activities"

    def test_nothing_new_means_nothing(self):
        assert alerts.workout([]) is None


class TestLoadSpikeRule:
    def test_a_jump_of_one_and_a_half_times_or_more(self):
        now = local(12)
        assert alerts.load_spike(SUNDAY, 40, 59, 60, None, now) is None
        note = alerts.load_spike(SUNDAY, 40, 64, 60, None, now)
        assert note.kind == "load_spike" and "1.6×" in note.message["body"]
        assert "linked with" in note.message["body"]

    def test_not_again_for_a_week(self):
        now = local(12)
        assert alerts.load_spike(SUNDAY, 40, 70, 60, now - timedelta(days=6), now) is None
        assert alerts.load_spike(SUNDAY, 40, 70, 60, now - timedelta(days=7), now) is not None

    def test_needs_six_weeks_and_a_real_base(self):
        now = local(12)
        assert alerts.load_spike(SUNDAY, 40, 70, 41, None, now) is None
        assert alerts.load_spike(SUNDAY, 5, 20, 60, None, now) is None
        assert alerts.load_spike(SUNDAY, None, None, 0, None, now) is None


class TestWeeklyRule:
    def test_sundays_from_your_time(self):
        assert alerts.weekly_due(local(18, 59), "19:00") is None
        assert alerts.weekly_due(local(19, 0), "19:00") == date(2026, 11, 9)
        assert alerts.weekly_due(local(19, 0, SUNDAY - timedelta(days=1)), "19:00") is None

    def test_the_summary(self):
        note = alerts.weekly(date(2026, 11, 9), {"seconds": {"run": 11400, "bike": 14700, "swim": 0},
                                                 "total_load": 412}, 368, 351,
                             {"logged_days": 5, "kcal": 2349.6, "protein": 141.7})
        assert note.ref == "2026-11-09"
        assert note.message["body"] == ("Run 3 h 10 min · Bike 4 h 5 min. Load 412, up 12% on last week. "
                                        "Food: 2,350 kcal and 142 g protein a day over 5 logged days. "
                                        "351 days to race day.")

    def test_a_quiet_week_says_so_and_leaves_out_what_it_doesnt_know(self):
        note = alerts.weekly(date(2026, 11, 9), {"seconds": {}, "total_load": 0}, None, -3,
                             {"logged_days": 0, "kcal": None, "protein": None})
        assert note.message["body"] == "No run, bike or swim this week."


class TestKeyRule:
    def test_steps_as_the_date_gets_close(self):
        expires = date(2026, 12, 1)
        assert alerts.key_expiring(expires, expires - timedelta(days=15)) is None
        refs = {alerts.key_expiring(expires, expires - timedelta(days=d)).ref for d in range(15)}
        assert refs == {f"2026-12-01:{s}" for s in (14, 7, 3, 1, 0)}
        assert "in 5 days (1 Dec)" in alerts.key_expiring(expires, expires - timedelta(days=5)).message["body"]
        assert "tomorrow" in alerts.key_expiring(expires, expires - timedelta(days=1)).message["body"]
        assert "today" in alerts.key_expiring(expires, expires).message["body"]

    def test_after_it_runs_out(self):
        note = alerts.key_expiring(date(2026, 12, 1), date(2026, 12, 3))
        assert note.ref == "2026-12-01:expired" and "expired on 1 Dec" in note.message["body"]

    def test_no_date_no_warning(self):
        assert alerts.key_expiring(None, SUNDAY) is None


class TestSyncFailedRule:
    def runs(self, *statuses):
        return [{"id": 100 - i, "status": s} for i, s in enumerate(statuses)]

    def test_one_failure_is_left_alone_two_are_not(self):
        assert alerts.sync_failed(self.runs("failed", "ok"), None, KOLKATA) is None
        note = alerts.sync_failed(self.runs("failed", "failed", "ok"), None, KOLKATA)
        assert note.ref == "99" and note.message["body"] == "The last 2 syncs failed."

    def test_a_refused_key_counts_straight_away(self):
        note = alerts.sync_failed(self.runs("auth_failed", "ok"), None, KOLKATA)
        assert "refused the key" in note.message["body"]

    def test_one_notification_per_run_of_failures(self):
        first = alerts.sync_failed(self.runs("failed", "failed", "ok"), None, KOLKATA)
        later = alerts.sync_failed([{"id": 101, "status": "failed"}, *self.runs("failed", "failed", "ok")], None,
                                   KOLKATA)
        assert first.ref == later.ref

    def test_says_when_it_last_worked_without_the_error(self):
        good = datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc)
        note = alerts.sync_failed(self.runs("failed", "failed"), good, KOLKATA)
        assert note.message["body"].endswith("Last good sync: 15 Nov, 8:30 AM.")


def test_quiet_hours():
    assert not alerts.daytime(local(6, 59))
    assert alerts.daytime(local(7))
    assert alerts.daytime(local(21, 59))
    assert not alerts.daytime(local(22))


# ---------------------------------------------------------------- the whole path

@pytest.fixture
def phone(owner, store):
    """The owner with one phone, every notification on, and the key date and race date in the future."""
    _, subscription, _ = _phone()
    db_push.save_subscription(store.conn, owner.user_id, subscription["endpoint"], subscription["p256dh"],
                              subscription["auth"])
    store.commit()
    return owner


def add_hrv(store, today: date, last_night: bool = True) -> None:
    """28 nights of HRV that vary a little, so Recovery has a baseline."""
    for back in range(0 if last_night else 1, 29):
        store.conn.execute(
            "insert into daily_metric (calendar_date, metric, source, value_num) values (%s, %s, 'api', %s)",
            (today - timedelta(days=back), "hrv_last_night_avg", 50 + back % 5))
    store.commit()


def add_activity(store, activity_id: int, start: datetime, discipline: str = "run", seconds: float = 3000,
                 metres: float | None = 8000) -> None:
    store.conn.execute(
        "insert into activity (activity_id, source, discipline, start_time, local_date, duration_seconds, distance_m) "
        "values (%s, 'api', %s, %s, %s, %s, %s)",
        (activity_id, discipline, start, start.astimezone(KOLKATA).date(), seconds, metres))
    store.commit()


def add_run(store, status: str) -> None:
    store.conn.execute("insert into sync_run (trigger, status, finished_at) values ('cron', %s, now())", (status,))
    store.commit()


def run(store, keys, now, outcome=push.SENT, trigger="cron"):
    sent = []

    def sender(subscription, message, _keys):
        sent.append(message)
        return outcome
    counts = notify.send_training_notifications(store.conn, now=now, keys=keys, sender=sender, trigger=trigger)
    return counts, sent


def only(store, *keep):
    """Turn every training notification off except these."""
    flags = ("notify_recovery", "notify_workout", "notify_load_spike", "notify_weekly", "notify_key_expiring",
             "notify_sync_failed")
    app_settings.save(store.conn, {flag: flag in keep for flag in flags})
    store.commit()


class TestSending:
    def test_recovery_once_a_morning(self, phone, store, vapid):
        only(store, "notify_recovery")
        add_hrv(store, SUNDAY)
        assert run(store, vapid, local(7, 15))[1] == []
        counts, sent = run(store, vapid, local(7, 40))
        assert counts == {"status": "ok", "sent": 1, "seen": 0, "failed": 0}
        assert sent[0]["title"].startswith("Recovery ")
        assert run(store, vapid, local(8, 10))[1] == []

    def test_recovery_waits_for_last_nights_hrv(self, phone, store, vapid):
        only(store, "notify_recovery")
        add_hrv(store, SUNDAY, last_night=False)
        assert run(store, vapid, local(7, 40))[1] == []

    def test_a_workout_recap_once(self, phone, store, vapid):
        only(store, "notify_workout")
        add_activity(store, 501, local(6, 0))
        counts, sent = run(store, vapid, local(8, 0))
        assert counts["sent"] == 1 and sent[0]["url"] == "/#/activities/501"
        assert sent[0]["body"].startswith("50 min · 8.0 km")
        assert run(store, vapid, local(8, 30))[1] == []

    def test_old_workouts_never_get_a_recap(self, phone, store, vapid):
        only(store, "notify_workout")
        add_activity(store, 502, local(6, 0) - timedelta(days=2))
        assert run(store, vapid, local(8, 0))[1] == []

    def test_a_workout_seen_after_sync_now_isnt_sent_later(self, phone, store, vapid):
        only(store, "notify_workout")
        add_activity(store, 503, local(6, 0))
        counts, sent = run(store, None, local(7, 50), trigger="manual")
        assert counts["seen"] == 1 and sent == []
        assert run(store, vapid, local(8, 10))[1] == []

    def test_a_late_workout_waits_for_the_morning(self, phone, store, vapid):
        only(store, "notify_workout")
        add_activity(store, 504, local(21, 0, SUNDAY - timedelta(days=1)))
        assert run(store, vapid, local(23, 0, SUNDAY - timedelta(days=1)))[1] == []
        assert run(store, vapid, local(7, 10))[1][0]["url"] == "/#/activities/504"

    def test_the_weekly_summary_with_food(self, phone, store, vapid):
        only(store, "notify_weekly")
        app_settings.save(store.conn, {"race_date": "2027-11-01"})
        store.commit()
        add_activity(store, 505, local(7, 0, SUNDAY - timedelta(days=3)))
        log(phone, eggs(phone, when=at(9, day=SUNDAY - timedelta(days=2))), when=at(9, day=SUNDAY - timedelta(days=2)))
        assert run(store, vapid, local(18, 0))[1] == []
        counts, sent = run(store, vapid, local(19, 15))
        assert counts["sent"] == 1
        body = sent[0]["body"]
        assert body.startswith("Run 50 min.")
        assert "over 1 logged day." in body
        assert body.endswith("351 days to race day.")
        assert run(store, vapid, local(20, 0))[1] == []

    def test_sync_failures(self, phone, store, vapid):
        only(store, "notify_sync_failed")
        add_run(store, "ok")
        add_run(store, "failed")
        assert run(store, vapid, local(12))[1] == []
        add_run(store, "failed")
        assert run(store, vapid, local(12, 30))[1][0]["title"] == "Sync failed"
        add_run(store, "failed")
        assert run(store, vapid, local(13))[1] == []
        add_run(store, "ok")
        add_run(store, "failed")
        add_run(store, "failed")
        assert len(run(store, vapid, local(13, 30))[1]) == 1

    def test_nothing_but_your_chosen_times_at_night(self, phone, store, vapid):
        only(store, "notify_sync_failed")
        add_run(store, "auth_failed")
        assert run(store, vapid, local(23))[1] == []
        assert len(run(store, vapid, local(7, 5))[1]) == 1

    def test_the_garmin_key(self, phone, store, vapid):
        only(store, "notify_key_expiring")
        app_settings.save(store.conn, {"garmin_key_expires": (SUNDAY + timedelta(days=5)).isoformat()})
        store.commit()
        assert "in 5 days" in run(store, vapid, local(9))[1][0]["body"]
        assert run(store, vapid, local(9, 30))[1] == []

    def test_switched_off_means_none(self, phone, store, vapid):
        only(store)
        add_hrv(store, SUNDAY)
        add_activity(store, 506, local(6, 0))
        add_run(store, "auth_failed")
        assert run(store, vapid, local(8))[1] == []

    def test_a_phone_that_didnt_take_it_is_recorded(self, phone, store, vapid):
        only(store, "notify_workout")
        add_activity(store, 507, local(6, 0))
        counts, _ = run(store, vapid, local(8), outcome=push.FAILED)
        assert counts["failed"] == 1
        row = store.conn.execute("select outcome from notification_sent where ref = '507'").fetchone()
        assert row["outcome"] == "failed"

    def test_without_keys_or_a_phone_nothing_happens(self, owner, store, vapid, monkeypatch):
        assert run(store, vapid, local(8))[0] == {"status": "no_phone"}
        monkeypatch.delenv(push.PRIVATE_KEY_ENV)
        monkeypatch.delenv(push.PUBLIC_KEY_ENV)
        assert notify.send_training_notifications(store.conn, now=local(8)) == {"status": "not_configured"}

    def test_only_the_owners_phones(self, phone, other, store, vapid):
        _, subscription, _ = _phone()
        db_push.save_subscription(store.conn, other.user_id, subscription["endpoint"] + "-other",
                                  subscription["p256dh"], subscription["auth"])
        store.commit()
        only(store, "notify_workout")
        add_activity(store, 508, local(6, 0))
        endpoints = []

        def sender(sub, message, _keys):
            endpoints.append(sub["endpoint"])
            return push.SENT
        notify.send_training_notifications(store.conn, now=local(8), keys=vapid, sender=sender)
        assert endpoints == ["https://web.push.apple.com/abc"]


class TestRoutes:
    def test_the_schedule_sends_after_syncing_and_a_failure_never_stops_it(self, owner, monkeypatch):
        order = []
        monkeypatch.setattr(notify, "send_food_reminders", lambda conn: order.append("food") or {"status": "ok"})
        monkeypatch.setattr(api_module, "_sync", lambda conn, trigger: order.append("sync") or {"status": "ok"})

        def broken(conn, trigger):
            order.append(trigger)
            raise RuntimeError("push service down")
        monkeypatch.setattr(notify, "send_training_notifications", broken)
        monkeypatch.setenv("CRON_SECRET", "s3cret")
        response = TestClient(api_module.app).post("/api/cron/sync", headers={"Authorization": "Bearer s3cret"})
        assert response.json() == {"status": "ok", "reminders": {"status": "ok"},
                                   "notifications": {"status": "failed"}}
        assert order == ["food", "sync", "cron"]

    def test_sync_now_marks_rather_than_sends(self, owner, monkeypatch):
        triggers = []
        monkeypatch.setattr(api_module, "_sync", lambda conn, trigger: {"status": "ok"})
        monkeypatch.setattr(notify, "send_training_notifications",
                            lambda conn, trigger: triggers.append(trigger) or {"status": "ok"})
        assert owner.post("/api/sync").status_code == 200
        assert triggers == ["manual"]

    def test_settings_say_whether_notifications_are_set_up(self, phone, vapid):
        body = phone.get("/api/settings").json()
        assert body["push"] == {"public_key": vapid.public_b64, "phones": 1}
        assert body["notify_workout"] and body["notify_load_spike"] and body["notify_weekly"]
        assert body["weekly_notify_time"] == "19:00"

    def test_new_settings_are_checked(self, owner):
        assert owner.put("/api/settings", json={"weekly_notify_time": "7pm"}).status_code == 422
        assert owner.put("/api/settings", json={"notify_weekly": "yes"}).status_code == 422
        saved = owner.put("/api/settings", json={"weekly_notify_time": "18:30", "notify_weekly": False}).json()
        assert saved["weekly_notify_time"] == "18:30" and saved["notify_weekly"] is False

    def test_the_test_button_opens_settings_when_sent_from_there(self, phone, vapid, monkeypatch):
        sent = []
        monkeypatch.setattr(notify, "deliver", lambda conn, user, message, keys: sent.append(message) or 1)
        assert phone.post("/api/push/test?screen=settings").status_code == 200
        assert sent[0]["url"] == "/#/settings"

    def test_the_settings_need_the_owner(self, other):
        assert other.get("/api/settings").status_code == 403
