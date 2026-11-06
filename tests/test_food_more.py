"""The rest of the food logger: settings, trends, CSV, barcodes, notifications and reminders."""
# The people fixtures come from test_food_api, which pytest sees as tests naming them again.
# ruff: noqa: F811
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from test_food_api import IST, TODAY, at, day, eggs, log, new_id, other, owner, people, send  # noqa: F401

from creed import notify, push
from creed.api import app as api_module
from creed.api import food_routes
from creed.db import food
from creed.db import push as db_push
from creed.food import barcode, csvio, reminders
from creed.food import trends as food_trends
from creed.food.nutrition import InvalidFood
from creed.food.targets import DayType, TargetSet

UTC = timezone.utc


# ---------------------------------------------------------------- Web Push

def _decrypt(body: bytes, receiver: ec.EllipticCurvePrivateKey, auth_secret: bytes) -> bytes:
    """What the phone does with a notification (RFC 8291), so encryption can be checked end to end."""
    salt, record_size, id_length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    sender_bytes = body[21:21 + id_length]
    ciphertext = body[21 + id_length:]
    assert record_size == 4096
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_bytes)
    receiver_bytes = push._public_bytes(receiver.public_key())
    shared = receiver.exchange(ec.ECDH(), sender)
    ikm = push._hkdf(auth_secret, shared, b"WebPush: info\x00" + receiver_bytes + sender_bytes, 32)
    key = push._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = push._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(key).decrypt(nonce, ciphertext, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def _phone():
    receiver = ec.generate_private_key(ec.SECP256R1())
    auth_secret = b"0123456789abcdef"
    return receiver, {"endpoint": "https://web.push.apple.com/abc", "p256dh": push.b64url(push._public_bytes(
        receiver.public_key())), "auth": push.b64url(auth_secret)}, auth_secret


@pytest.fixture
def vapid(monkeypatch):
    private, public = push.generate_vapid_keys()
    monkeypatch.setenv(push.PRIVATE_KEY_ENV, private)
    monkeypatch.setenv(push.PUBLIC_KEY_ENV, public)
    return push.load_vapid_keys()


class TestWebPush:
    def test_only_the_phone_can_read_a_notification(self):
        receiver, subscription, auth_secret = _phone()
        body = push.encrypt(b'{"title":"Food"}', subscription["p256dh"], subscription["auth"])
        assert _decrypt(body, receiver, auth_secret) == b'{"title":"Food"}'
        assert b"Food" not in body
        # Each message gets its own salt and key, so the same text never looks the same twice.
        assert push.encrypt(b"x", subscription["p256dh"], subscription["auth"]) != push.encrypt(
            b"x", subscription["p256dh"], subscription["auth"])

    def test_the_signature_proves_which_deployment_sent_it(self, vapid, monkeypatch):
        monkeypatch.setenv("CREED_ORIGIN", "https://creed.example")
        header = push.vapid_authorization("https://web.push.apple.com/abc/def", vapid, push.subject(), now=1_000_000)
        token, key = header.removeprefix("vapid t=").split(", k=")
        assert key == vapid.public_b64
        head, body, signature = token.split(".")
        claims = json.loads(push.unb64url(body))
        assert claims == {"aud": "https://web.push.apple.com", "exp": 1_000_000 + 12 * 3600,
                          "sub": "https://creed.example"}
        raw = push.unb64url(signature)
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64url(key))
        public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                      f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))

    def test_the_contact_is_never_a_personal_address(self, monkeypatch):
        monkeypatch.setenv("CREED_ORIGIN", "http://localhost:5173")
        assert push.subject() == "https://github.com/prokp3/creed"

    def test_keys_are_optional_but_must_match(self, monkeypatch):
        monkeypatch.delenv(push.PRIVATE_KEY_ENV, raising=False)
        monkeypatch.delenv(push.PUBLIC_KEY_ENV, raising=False)
        assert push.load_vapid_keys() is None
        private, _ = push.generate_vapid_keys()
        _, other_public = push.generate_vapid_keys()
        monkeypatch.setenv(push.PRIVATE_KEY_ENV, private)
        monkeypatch.setenv(push.PUBLIC_KEY_ENV, other_public)
        with pytest.raises(push.PushNotConfigured):
            push.load_vapid_keys()

    def test_a_non_https_address_is_never_contacted(self, vapid):
        _, subscription, _ = _phone()
        assert push.send({**subscription, "endpoint": "http://127.0.0.1/steal"}, {"title": "x"}, vapid) == push.GONE


# ---------------------------------------------------------------- reminders

NOW = datetime(2026, 11, 6, 8, 10, tzinfo=UTC)  # 1:40 PM in India.


def _decide(times=("13:30",), last=None, already=(), now=NOW, gap=180):
    return reminders.decide(now, times=list(times), timezone="Asia/Kolkata", gap_minutes=gap, last_logged=last,
                            already=already)


class TestReminderRules:
    def test_due_for_an_hour_after_its_time(self):
        assert [(d.slot, d.outcome) for d in _decide()] == [("13:30", "send")]
        assert _decide(times=["13:45"]) == []  # Not yet.
        assert _decide(times=["12:30"]) == []  # Over an hour ago: missed, not sent late.

    def test_skipped_when_something_was_logged_recently(self):
        assert _decide(last=NOW - timedelta(hours=2))[0].outcome == "skip"
        assert _decide(last=NOW - timedelta(hours=3, minutes=1))[0].outcome == "send"
        assert _decide(last=NOW - timedelta(minutes=40), gap=30)[0].outcome == "send"

    def test_never_twice_for_the_same_time_and_day(self):
        assert _decide(already={(date(2026, 11, 6), "13:30")}) == []

    def test_a_late_night_reminder_belongs_to_its_own_day(self):
        late = datetime(2026, 11, 6, 18, 50, tzinfo=UTC)  # 12:20 AM on the 7th in India.
        [decision] = _decide(times=["23:45"], now=late)
        assert decision.local_date == date(2026, 11, 6)

    def test_times_are_checked(self):
        assert reminders.clean_times(["20:00", "08:30", "08:30"]) == ["08:30", "20:00"]
        for bad in (["8:30pm"], ["24:00"], "08:30", [f"{h:02d}:00" for h in range(9)]):
            with pytest.raises(InvalidFood):
                reminders.clean_times(bad)
        with pytest.raises(InvalidFood):
            reminders.zone("Mars/Base")

    def test_the_message_names_no_food(self):
        message = reminders.message(NOW - timedelta(hours=4), "Asia/Kolkata", NOW)
        assert message["body"] == "Nothing logged for 4 hours. Tap to log what you've eaten."
        assert reminders.message(None, "Asia/Kolkata", NOW)["body"].startswith("Nothing logged yet today")
        assert message["url"] == "/#/food"


@pytest.fixture
def reminder_owner(owner, store):
    """The owner with a 1:30 PM reminder and one phone."""
    send(owner, {"type": "settings.save", "changed_at": at(9), "record": {
        "reminders_on": True, "reminder_times": ["13:30"], "timezone": "Asia/Kolkata"}})
    _, subscription, _ = _phone()
    db_push.save_subscription(store.conn, owner.user_id, subscription["endpoint"], subscription["p256dh"],
                              subscription["auth"])
    store.commit()
    return owner


class TestSendingReminders:
    def _run(self, store, vapid, outcome=push.SENT, now=NOW):
        sent = []
        def sender(subscription, message, keys):
            sent.append(message)
            return outcome
        return notify.send_food_reminders(store.conn, now=now, keys=vapid, sender=sender), sent

    def test_sends_once_however_often_the_schedule_runs(self, reminder_owner, store, vapid):
        counts, sent = self._run(store, vapid)
        assert counts == {"status": "ok", "sent": 1, "skipped": 0, "failed": 0}
        assert sent[0]["body"].startswith("Nothing logged yet today")
        again, sent_again = self._run(store, vapid, now=NOW + timedelta(minutes=30))
        assert again["sent"] == 0 and sent_again == []

    def test_skips_when_you_logged_recently(self, reminder_owner, store, vapid):
        log(reminder_owner, eggs(reminder_owner, when=(NOW - timedelta(hours=1)).astimezone(IST).isoformat()))
        counts, sent = self._run(store, vapid)
        assert counts["skipped"] == 1 and sent == []

    def test_a_phone_that_left_is_forgotten(self, reminder_owner, store, vapid):
        counts, _ = self._run(store, vapid, outcome=push.GONE)
        assert counts["failed"] == 1
        assert db_push.subscriptions(store.conn, reminder_owner.user_id) == []

    def test_nothing_happens_without_keys(self, reminder_owner, store, monkeypatch):
        monkeypatch.delenv(push.PRIVATE_KEY_ENV, raising=False)
        monkeypatch.delenv(push.PUBLIC_KEY_ENV, raising=False)
        assert notify.send_food_reminders(store.conn, now=NOW) == {"status": "not_configured"}

    def test_reminders_off_means_none(self, reminder_owner, store, vapid):
        send(reminder_owner, {"type": "settings.save", "changed_at": at(10), "record": {"reminders_on": False}})
        assert self._run(store, vapid)[1] == []

    def test_a_reminder_failure_never_stops_the_sync(self, owner, monkeypatch):
        def broken(conn):
            raise RuntimeError("push service down")
        monkeypatch.setattr(notify, "send_food_reminders", broken)
        monkeypatch.setattr(api_module, "_sync", lambda conn, trigger: {"status": "ok"})
        monkeypatch.setenv("CRON_SECRET", "s3cret")
        response = TestClient(api_module.app).post("/api/cron/sync", headers={"Authorization": "Bearer s3cret"})
        assert response.json() == {"status": "ok", "reminders": {"status": "failed"}}


class TestNotificationRoutes:
    def test_a_phone_subscribes_and_unsubscribes(self, owner, store):
        _, subscription, _ = _phone()
        body = {"endpoint": subscription["endpoint"], "keys": {"p256dh": subscription["p256dh"],
                                                               "auth": subscription["auth"]}}
        assert owner.post("/api/push/subscribe", json=body).json() == {"subscribed": True}
        assert len(db_push.subscriptions(store.conn, owner.user_id)) == 1
        owner.post("/api/push/unsubscribe", json={"endpoint": subscription["endpoint"]})
        assert db_push.subscriptions(store.conn, owner.user_id) == []

    def test_only_real_push_addresses_are_kept(self, owner):
        response = owner.post("/api/push/subscribe", json={"endpoint": "http://evil.example/",
                                                           "keys": {"p256dh": "x" * 20, "auth": "y" * 20}})
        assert response.status_code == 422

    def test_a_phone_moves_to_whoever_signed_in_last(self, owner, other, store):
        _, subscription, _ = _phone()
        body = {"endpoint": subscription["endpoint"], "keys": {"p256dh": subscription["p256dh"],
                                                               "auth": subscription["auth"]}}
        owner.post("/api/push/subscribe", json=body)
        other.post("/api/push/subscribe", json=body)
        assert db_push.subscriptions(store.conn, owner.user_id) == []
        assert len(db_push.subscriptions(store.conn, other.user_id)) == 1

    def test_the_test_button_says_when_notifications_arent_set_up(self, owner, monkeypatch):
        monkeypatch.delenv(push.PRIVATE_KEY_ENV, raising=False)
        monkeypatch.delenv(push.PUBLIC_KEY_ENV, raising=False)
        assert owner.post("/api/push/test").status_code == 503
        assert owner.get("/api/food/library").json()["push"] == {"public_key": None}

    def test_the_test_button_sends(self, owner, store, vapid, monkeypatch):
        _, subscription, _ = _phone()
        db_push.save_subscription(store.conn, owner.user_id, subscription["endpoint"], subscription["p256dh"],
                                  subscription["auth"])
        store.commit()
        monkeypatch.setattr(push, "send", lambda s, m, k, **kw: push.SENT)
        monkeypatch.setattr(notify.push, "send", lambda s, m, k, **kw: push.SENT)
        monkeypatch.setattr(notify, "deliver", lambda conn, user, message, keys: 1)
        assert owner.post("/api/push/test").json() == {"delivered": 1}
        assert owner.get("/api/food/library").json()["push"]["public_key"] == vapid.public_b64

    def test_routes_need_a_session(self, people):
        assert TestClient(api_module.app).post("/api/push/subscribe", json={}).status_code == 401


# ---------------------------------------------------------------- settings

class TestSettings:
    def test_defaults_until_changed(self, owner):
        assert owner.get("/api/food/library").json()["settings"] == {
            "training_minutes": 20, "reminders_on": False, "reminder_times": [], "reminder_gap_minutes": 180,
            "timezone": "Asia/Kolkata"}

    def test_a_change_keeps_the_rest(self, owner):
        [result] = send(owner, {"type": "settings.save", "changed_at": at(9), "record": {"training_minutes": 45}})
        assert result == {"result": "applied"}
        send(owner, {"type": "settings.save", "changed_at": at(10), "record": {"reminder_times": ["20:00", "13:00"]}})
        settings = owner.get("/api/food/library").json()["settings"]
        assert settings["training_minutes"] == 45
        assert settings["reminder_times"] == ["13:00", "20:00"]

    def test_bad_values_are_refused(self, owner):
        for record in ({"training_minutes": 0}, {"reminder_gap_minutes": 10}, {"reminders_on": "yes"},
                       {"timezone": "Nowhere"}, {"reminder_times": ["25:00"]}):
            [result] = send(owner, {"type": "settings.save", "changed_at": at(9), "record": record})
            assert "error" in result, record

    def test_the_threshold_decides_training_days(self, owner, store):
        store.conn.execute("insert into activity (activity_id, source, discipline, local_date, duration_seconds) "
                           "values (1, 'api', 'run', %s, 1800)", (TODAY,))
        store.commit()
        assert day(owner)["day_type"] == {"type": "training", "how": "garmin", "threshold_minutes": 20}
        send(owner, {"type": "settings.save", "changed_at": at(9), "record": {"training_minutes": 45}})
        assert day(owner)["day_type"] == {"type": "rest", "how": "default", "threshold_minutes": 45}

    def test_settings_are_private(self, owner, other, store):
        send(owner, {"type": "settings.save", "changed_at": at(9), "record": {"training_minutes": 45}})
        assert other.get("/api/food/library").json()["settings"]["training_minutes"] == 20
        with food.as_user(store.conn, other.user_id):
            assert store.conn.execute("select count(*) as n from food_setting").fetchone()["n"] == 0
        store.conn.rollback()

    def test_people_never_see_notification_addresses_as_themselves(self, owner, store):
        with food.as_user(store.conn, owner.user_id), pytest.raises(Exception, match="permission denied"):
            store.conn.execute("select * from push_subscription")
        store.conn.rollback()


# ---------------------------------------------------------------- trends

class TestTrends:
    def test_days_with_nothing_logged_are_gaps_not_zeros(self):
        days = [date(2026, 11, d) for d in range(1, 8)]
        entry = {"local_date": days[0], "base_amount": 300.0, "nutrients_per_100": {"kcal": 100.0, "protein": 10.0}}
        result = food_trends.trends(
            start=days[0], end=days[-1], entries=[entry, {**entry, "local_date": days[2]}],
            nutrients=[{"id": "kcal", "name": "Calories", "unit": "kcal"}, {"id": "protein", "name": "Protein",
                                                                            "unit": "g"}],
            day_types={d: DayType("rest", "default") for d in days},
            target_sets=[TargetSet("rest", days[0], {"kcal": 2000.0, "protein": 25.0})],
            burned={days[0]: 2500.0},
        )
        assert result["logged_days"] == 2
        assert result["days"][1]["totals"] is None
        assert result["averages"]["kcal"] == {"eaten": 300.0, "target": 2000.0}
        assert result["net"] == {"days": 1, "average_kcal": 300.0 - 2500.0, "estimate": True}
        assert result["protein_target_met"] == {"days": 2, "of": 2}

    def test_over_http(self, owner):
        log(owner, eggs(owner), eggs(owner, when=at(9, day=TODAY - timedelta(days=3))))
        result = owner.get("/api/food/trends", params={"days": 7}).json()
        assert len(result["days"]) == 7
        assert result["days"][-1]["date"] == TODAY.isoformat()
        assert result["logged_days"] == 2
        assert result["averages"]["kcal"]["eaten"] == pytest.approx(429)
        assert owner.get("/api/food/trends", params={"days": 9}).status_code == 422
        assert len(owner.get("/api/food/trends", params={"days": 30}).json()["days"]) == 30

    def test_only_the_owner_gets_garmins_burn(self, other, store):
        store.conn.execute("insert into daily_metric (calendar_date, metric, source, value_num) "
                           "values (%s, 'calories_total', 'api', 2600)", (TODAY,))
        store.commit()
        assert other.get("/api/food/trends").json()["days"][-1]["burned_kcal"] is None


# ---------------------------------------------------------------- CSV

def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _import(client, text, replace=False, preview=False):
    path = "/api/food/import/preview" if preview else "/api/food/import"
    response = client.post(path, json={"csv": text, "timezone": "Asia/Kolkata", "replace_conflicts": replace})
    assert response.status_code == 200, response.text
    return response.json()


class TestCsv:
    def test_export_has_each_entrys_own_values(self, owner):
        log(owner, eggs(owner, label="Dinner", kind="quick"))
        response = owner.get("/api/food/export.csv")
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        [row] = _rows(response.text)
        assert row["food"] == "Egg, whole" and row["quantity"] == "6" and row["unit"] == "piece"
        assert row["amount"] == "300" and row["time"] == "20:00:00" and row["utc_offset"] == "+05:30"
        assert float(row["Calories (kcal)"]) == pytest.approx(429)
        assert float(row["Protein (g)"]) == pytest.approx(37.8)

    def test_round_trip_into_another_account(self, owner, other):
        log(owner, eggs(owner), eggs(owner, quantity=2, when=at(8)))
        text = owner.get("/api/food/export.csv").text
        preview = _import(other, text, preview=True)
        assert preview["counts"] == {"new": 2, "duplicate": 0, "conflict": 0, "deleted": 0}
        _import(other, text)
        # Everything comes back the same, except the link to the owner's own library, which the other person
        # doesn't have.
        unlinked = lambda rows: [{**r, "food_id": ""} for r in rows]
        assert _rows(other.get("/api/food/export.csv").text) == unlinked(_rows(text))

    def test_importing_the_same_file_twice_changes_nothing(self, owner):
        log(owner, eggs(owner))
        text = owner.get("/api/food/export.csv").text
        assert _import(owner, text)["counts"]["duplicate"] == 1
        assert len(day(owner)["meals"]) == 1

    def test_a_different_saved_entry_is_never_overwritten_silently(self, owner):
        entry = eggs(owner)
        log(owner, entry)
        text = owner.get("/api/food/export.csv").text
        log(owner, {**entry, "quantity": 3}, when=at(21))
        preview = _import(owner, text, preview=True)
        assert preview["counts"]["conflict"] == 1
        assert _import(owner, text)["counts"]["replaced"] == 0
        assert day(owner)["meals"][0]["entries"][0]["quantity"] == 3
        assert _import(owner, text, replace=True)["counts"]["replaced"] == 1
        assert day(owner)["meals"][0]["entries"][0]["quantity"] == 6

    def test_a_deleted_entry_stays_deleted(self, owner):
        entry = eggs(owner)
        log(owner, entry)
        text = owner.get("/api/food/export.csv").text
        send(owner, {"type": "entries.delete", "ids": [entry["id"]], "changed_at": at(21)})
        assert _import(owner, text, replace=True)["counts"]["deleted"] == 1
        assert day(owner)["meals"] == []

    def test_a_simple_hand_made_file(self, owner):
        text = ("date,time,food,amount,Calories (kcal),protein,Sodium (mg),Mood\n"
                f"{TODAY},8:15,Poha,250,310,6.5,,good\n"
                f"{TODAY},13:00,Restaurant thali,,1450,38,,\n"
                f"{TODAY},,Missing time,100,50,,,\n")
        preview = _import(owner, text, preview=True)
        assert preview["counts"]["new"] == 2
        assert preview["error_count"] == 1 and preview["errors"][0]["row"] == 4
        assert preview["ignored_columns"] == ["Mood"]
        _import(owner, text)
        totals = day(owner)["totals"]
        assert totals["kcal"] == pytest.approx(310 + 1450)
        assert "sodium" in day(owner)["incomplete"]
        assert _import(owner, text)["counts"]["duplicate"] == 2  # Same rows, same ids, nothing doubled.

    def test_files_it_cant_use_say_why(self, owner):
        for text, message in (("food,kcal\nEgg,70\n", "date"), ("date,time,food\n2026-11-06,8:00,Egg\n", "nutrient")):
            response = owner.post("/api/food/import/preview", json={"csv": text})
            assert response.status_code == 422 and message in response.json()["detail"]

    def test_links_to_someone_elses_foods_are_dropped_but_the_entry_kept(self, owner, other):
        log(owner, eggs(owner))
        _import(other, owner.get("/api/food/export.csv").text)
        [entry] = day(other)["meals"][0]["entries"]
        assert entry["food_id"] is None and entry["food_name"] == "Egg, whole"


# ---------------------------------------------------------------- barcodes

PRODUCT = {
    "product_name": "Protein bar", "brands": "Acme, Acme Foods", "serving_quantity": 60,
    "nutriments": {"energy-kj_100g": 1674, "proteins_100g": 33, "carbohydrates_100g": 40, "fat_100g": 12,
                   "salt_100g": 1.0, "potassium_100g": 0.4},
}


class TestBarcodes:
    def test_a_draft_per_100_g_with_its_workings(self):
        draft = barcode.draft("8901234567890", PRODUCT)
        assert draft["name"] == "Protein bar" and draft["brand"] == "Acme"
        assert draft["nutrients"]["kcal"] == pytest.approx(1674 / 4.184)
        assert draft["nutrients"]["sodium"] == pytest.approx(400)  # 1 g salt is 0.4 g sodium.
        assert draft["nutrients"]["potassium"] == pytest.approx(400)
        assert draft["units"] == {"serving": 60} and draft["default_unit"] == "serving"
        assert "kJ" in draft["notes"] and "salt" in draft["notes"]
        assert "magnesium" not in draft["nutrients"]  # Not on the label means unknown.

    def test_drinks_are_per_100_ml(self):
        assert barcode.draft("12345678", {"product_name": "Juice", "product_quantity_unit": "ml",
                                          "nutriments": {}})["base"] == "ml"

    def test_your_own_food_comes_first(self, owner, monkeypatch):
        monkeypatch.setattr(barcode, "fetch", lambda code: pytest.fail("Open Food Facts asked"))
        send(owner, {"type": "food.save", "changed_at": at(9), "record": {
            "id": new_id(), "name": "My bar", "base": "g", "nutrients": {"kcal": 400}, "barcode": "8901234567890"}})
        result = owner.get("/api/food/barcode/8901234567890").json()
        assert result["source"] == "library" and result["food"]["name"] == "My bar"

    def test_open_food_facts_found_missing_and_unreachable(self, owner, monkeypatch):
        monkeypatch.setattr(barcode, "fetch", lambda code: PRODUCT)
        assert owner.get("/api/food/barcode/8901234567891").json()["draft"]["name"] == "Protein bar"
        monkeypatch.setattr(barcode, "fetch", lambda code: None)
        assert owner.get("/api/food/barcode/8901234567891").json() == {"source": "none", "barcode": "8901234567891"}

        def down(code):
            raise barcode.LookupFailed("Couldn't reach Open Food Facts.")
        monkeypatch.setattr(barcode, "fetch", down)
        response = owner.get("/api/food/barcode/8901234567891")
        assert response.status_code == 502 and "barcode is kept" in response.json()["detail"]

    def test_only_digits(self, owner):
        assert owner.get("/api/food/barcode/12ab5678").status_code == 422
        assert owner.get("/api/food/barcode/123").status_code == 422

    def test_a_scanned_draft_saves_as_a_food(self, owner):
        draft = barcode.draft("8901234567890", PRODUCT)
        [result] = send(owner, {"type": "food.save", "changed_at": at(9), "record": {**draft, "id": new_id()}})
        assert result == {"result": "applied"}


def test_limits():
    assert food_routes.TREND_DAYS == (7, 30)
    assert csvio.MAX_ROWS == 20_000
