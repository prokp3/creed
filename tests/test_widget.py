"""The home screen widget: its key, and the one read it makes with it."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
from test_food_api import at, eggs, log, other, owner, people, send  # noqa: F401

from creed import auth
from creed.api import app as api_module


def widget_read(key: str | None):
    headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
    return TestClient(api_module.app).get("/api/widget/food", headers=headers)


def turn_on(client) -> str:
    response = client.post("/api/widget/key")
    assert response.status_code == 200, response.text
    return response.json()["key"]


class TestKey:
    def test_off_until_turned_on(self, owner):
        assert owner.get("/api/widget/key").json() == {"on": False, "created_at": None, "last_used_at": None}

    def test_turning_on_shows_the_key_once(self, owner):
        key = turn_on(owner)
        assert key.startswith("creed_w_") and len(key) > 40
        status = owner.get("/api/widget/key").json()
        assert status["on"] and status["last_used_at"] is None
        assert "key" not in status

    def test_only_the_hash_is_stored(self, owner, store):
        key = turn_on(owner)
        stored = store.conn.execute("select key_hash from widget_key").fetchone()["key_hash"]
        assert key.encode() not in bytes(stored)
        store.commit()

    def test_needs_a_session(self, people):
        client = TestClient(api_module.app)
        assert client.get("/api/widget/key").status_code == 401
        assert client.post("/api/widget/key").status_code == 401
        assert client.delete("/api/widget/key").status_code == 401

    def test_another_site_cannot_make_one(self, owner, monkeypatch):
        monkeypatch.setenv(auth.ORIGIN_ENV_VAR, "https://creed.example")
        assert owner.post("/api/widget/key", headers={"Origin": "https://evil.example"}).status_code == 403

    def test_a_new_key_stops_the_old_one(self, owner):
        old = turn_on(owner)
        new = turn_on(owner)
        assert widget_read(old).status_code == 401
        assert widget_read(new).status_code == 200

    def test_turning_off_stops_it(self, owner):
        key = turn_on(owner)
        assert owner.delete("/api/widget/key").json()["on"] is False
        assert widget_read(key).status_code == 401


class TestRead:
    def test_refuses_without_a_good_key(self, people):
        assert widget_read(None).status_code == 401
        assert widget_read("creed_w_made-up").status_code == 401
        assert widget_read("").status_code == 401

    def test_the_session_cookie_is_not_enough(self, owner):
        turn_on(owner)
        assert owner.get("/api/widget/food").status_code == 401

    def test_today_against_targets(self, owner):
        send(owner, {"type": "targets.save", "day_type": "training", "effective_from": "2026-01-01",
                     "targets": {"kcal": 3000, "protein": 160}, "changed_at": at(9)},
             {"type": "targets.save", "day_type": "rest", "effective_from": "2026-01-01",
              "targets": {"kcal": 2400, "protein": 140}, "changed_at": at(9)})
        log(owner, eggs(owner, quantity=2, when=at(8)))
        key = turn_on(owner)
        body = widget_read(key).json()
        assert body["day_type"] in ("training", "rest")
        assert body["logged"] == 1
        assert body["kcal_eaten"] > 0
        assert [r["id"] for r in body["rings"]] == ["kcal", "protein"]
        kcal = body["rings"][0]
        assert kcal["target"] in (3000, 2400) and kcal["eaten"] == body["kcal_eaten"]
        assert owner.get("/api/widget/key").json()["last_used_at"] is not None

    def test_shows_nothing_but_totals(self, owner):
        log(owner, eggs(owner, label="Secret breakfast"))
        body = widget_read(turn_on(owner)).json()
        assert set(body) == {"date", "day_type", "kcal_eaten", "rings", "logged"}
        assert "Secret breakfast" not in json.dumps(body) and "Egg" not in json.dumps(body)

    def test_no_targets_still_shows_calories(self, owner):
        log(owner, eggs(owner))
        body = widget_read(turn_on(owner)).json()
        assert body["rings"] == [] and body["kcal_eaten"] > 0

    def test_each_person_sees_only_their_own(self, owner, other):
        log(owner, eggs(owner, quantity=6))
        body = widget_read(turn_on(other)).json()
        assert body["logged"] == 0 and body["kcal_eaten"] == 0
