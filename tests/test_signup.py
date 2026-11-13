"""The public Try Creed page's route: checks the answers and passes them to the creator's form, storing nothing."""
from __future__ import annotations

import urllib.parse

import pytest
from fastapi.testclient import TestClient

from creed import auth, forms, signup
from creed.api import app as api_module

GOOD = {"email": "runner@example.com", "name": "Asha", "watch": "Forerunner 265", "training": "Half, March 2027",
        "tried": "not-yet", "review": "", "wishes": "A swim pace chart", "contact": "yes"}


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(signup, "send", lambda answers: calls.append(answers))
    return calls


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(auth.ORIGIN_ENV_VAR, "https://creed.example")
    return TestClient(api_module.app)


def test_answers_are_passed_on_without_a_session(client, sent):
    response = client.post("/api/public/try-form", json=GOOD)
    assert response.status_code == 200
    assert response.json() == {"sent": True}
    assert sent == [signup.Signup(**GOOD)]


@pytest.mark.parametrize("change", [{"name": " "}, {"email": ""}, {"email": "nope"}, {"contact": ""},
                                    {"contact": "maybe"}, {"tried": "sometimes"}, {"wishes": "x" * 4001}])
def test_what_the_form_requires_is_checked_first(client, sent, change):
    assert client.post("/api/public/try-form", json={**GOOD, **change}).status_code == 422
    assert sent == []


def test_only_name_email_and_contact_are_needed(client, sent):
    response = client.post("/api/public/try-form", json={"name": "Asha", "email": "a@b.co", "contact": "no"})
    assert response.status_code == 200
    assert sent[0].watch == "" and sent[0].tried == ""


def test_a_filled_honeypot_is_dropped_quietly(client, sent):
    assert client.post("/api/public/try-form", json={**GOOD, "website": "spam"}).status_code == 200
    assert sent == []


def test_another_site_cannot_post(client, sent):
    response = client.post("/api/public/try-form", json=GOOD, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert sent == []


def test_a_failed_delivery_asks_to_retry(client, monkeypatch):
    def fail(_answers):
        raise forms.NotDelivered("down")

    monkeypatch.setattr(signup, "send", fail)
    assert client.post("/api/public/try-form", json=GOOD).status_code == 502


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_send_maps_every_answer_to_the_form():
    seen = {}

    def opener(request, timeout):
        seen["url"], seen["body"] = request.full_url, request.data
        return FakeResponse()

    signup.send(signup.Signup(**{**GOOD, "review": "Love the bib"}), opener=opener)
    assert seen["url"] == signup.FORM_RESPONSE_URL
    body = dict(urllib.parse.parse_qsl(seen["body"].decode()))
    assert body == {
        "emailAddress": "runner@example.com",
        signup.FIELDS["name"]: "Asha",
        signup.FIELDS["watch"]: "Forerunner 265",
        signup.FIELDS["training"]: "Half, March 2027",
        signup.FIELDS["tried"]: "Not yet",
        signup.FIELDS["review"]: "Love the bib",
        signup.FIELDS["wishes"]: "A swim pace chart",
        signup.FIELDS["contact"]: "Yes, you can email me about Creed",
    }
