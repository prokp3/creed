"""The public feedback page's route: checks what visitors send and passes it on, storing nothing."""
from __future__ import annotations

import urllib.error
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from creed import auth, feedback
from creed.api import app as api_module

GOOD = {"kind": "bug", "title": "Sync time stays red", "details": "After a sync it still shows red.",
        "device": "iPhone 16, iOS 26", "email": "runner@example.com"}


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(feedback, "send", lambda report: calls.append(report))
    return calls


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(auth.ORIGIN_ENV_VAR, "https://creed.example")
    return TestClient(api_module.app)


def test_a_report_is_passed_on_without_a_session(client, sent):
    response = client.post("/api/public/feedback", json=GOOD)
    assert response.status_code == 200
    assert response.json() == {"sent": True}
    assert sent == [feedback.Feedback(**GOOD)]


def test_only_bugs_and_ideas_are_accepted(client, sent):
    response = client.post("/api/public/feedback", json={**GOOD, "kind": "spam"})
    assert response.status_code == 422
    assert sent == []


@pytest.mark.parametrize("missing", ["title", "details"])
def test_a_title_and_details_are_required(client, sent, missing):
    response = client.post("/api/public/feedback", json={**GOOD, missing: "   "})
    assert response.status_code == 422
    assert sent == []


def test_email_and_device_are_optional(client, sent):
    response = client.post("/api/public/feedback", json={"kind": "idea", "title": "Dark map", "details": "Please."})
    assert response.status_code == 200
    assert sent[0].email == "" and sent[0].device == ""


def test_a_bad_email_is_refused(client, sent):
    assert client.post("/api/public/feedback", json={**GOOD, "email": "not an email"}).status_code == 422
    assert sent == []


def test_overlong_details_are_refused(client, sent):
    response = client.post("/api/public/feedback", json={**GOOD, "details": "x" * 4001})
    assert response.status_code == 422
    assert sent == []


def test_a_filled_honeypot_is_dropped_quietly(client, sent):
    response = client.post("/api/public/feedback", json={**GOOD, "website": "http://spam.example"})
    assert response.status_code == 200
    assert sent == []


def test_another_site_cannot_post_feedback(client, sent):
    response = client.post("/api/public/feedback", json=GOOD, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert sent == []


def test_a_failed_delivery_asks_the_visitor_to_retry(client, monkeypatch):
    def fail(_report):
        raise feedback.NotDelivered("down")

    monkeypatch.setattr(feedback, "send", fail)
    response = client.post("/api/public/feedback", json=GOOD)
    assert response.status_code == 502
    assert "try again" in response.json()["detail"]


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_send_posts_every_answer_to_the_form():
    seen = {}

    def opener(request, timeout):
        seen["url"], seen["body"], seen["timeout"] = request.full_url, request.data, timeout
        return FakeResponse()

    feedback.send(feedback.Feedback(**GOOD), opener=opener)
    assert seen["url"] == feedback.FORM_RESPONSE_URL
    body = dict(urllib.parse.parse_qsl(seen["body"].decode()))
    assert body == {feedback.FIELDS["kind"]: "Bug", feedback.FIELDS["title"]: GOOD["title"],
                    feedback.FIELDS["details"]: GOOD["details"], feedback.FIELDS["device"]: GOOD["device"],
                    feedback.FIELDS["email"]: GOOD["email"]}
    assert seen["timeout"] == feedback.TIMEOUT_SECONDS


def test_send_reports_a_refusal_from_the_form():
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, None)

    with pytest.raises(feedback.NotDelivered):
        feedback.send(feedback.Feedback(**GOOD), opener=opener)
