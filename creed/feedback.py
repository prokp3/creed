"""Bug reports and feature ideas from the public feedback page, passed on to the creator's Google Form.

The form emails the creator for every response, so Creed needs no email service and keeps no copy. The fields map to
the form's question ids, which are public (they're in the form's own page), not secrets.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# The "Creed feedback" form. Its question ids, from the form's page, in the order the page asks them.
FORM_RESPONSE_URL = (
    "https://docs.google.com/forms/d/e/1FAIpQLSd0y4nTeCyQJkVkqpIfbhDVg5KbWD0DG_VO3nYTMRzHTqsKnQ/formResponse"
)
FIELDS = {
    "kind": "entry.1015013840",
    "title": "entry.1695440940",
    "details": "entry.1053149382",
    "device": "entry.512163351",
    "email": "entry.2084013913",
}
KINDS = {"bug": "Bug", "idea": "Feature idea"}
LIMITS = {"title": 120, "details": 4000, "device": 200, "email": 200}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TIMEOUT_SECONDS = 10


class InvalidFeedback(ValueError):
    pass


class NotDelivered(RuntimeError):
    pass


@dataclass(frozen=True)
class Feedback:
    kind: str
    title: str
    details: str
    device: str = ""
    email: str = ""


def clean(data: dict) -> Feedback:
    """Trims and checks what the page sent. Says what's wrong in words a visitor understands."""
    def text(name: str) -> str:
        value = data.get(name, "")
        return value.strip() if isinstance(value, str) else ""

    kind = text("kind")
    if kind not in KINDS:
        raise InvalidFeedback("Choose whether it's a bug or an idea.")
    fields = {name: text(name) for name in LIMITS}
    if not fields["title"]:
        raise InvalidFeedback("Give it a short title.")
    if not fields["details"]:
        raise InvalidFeedback("Add a few details.")
    for name, limit in LIMITS.items():
        if len(fields[name]) > limit:
            raise InvalidFeedback(f"The {name} is too long. Keep it under {limit} characters.")
    if fields["email"] and not EMAIL.match(fields["email"]):
        raise InvalidFeedback("That email address doesn't look right.")
    return Feedback(kind=kind, **fields)


def send(feedback: Feedback, opener=urllib.request.urlopen) -> None:
    """Posts it to the form as an anonymous response."""
    values = {
        FIELDS["kind"]: KINDS[feedback.kind],
        FIELDS["title"]: feedback.title,
        FIELDS["details"]: feedback.details,
        FIELDS["device"]: feedback.device,
        FIELDS["email"]: feedback.email,
    }
    body = urllib.parse.urlencode({k: v for k, v in values.items() if v}).encode()
    request = urllib.request.Request(
        FORM_RESPONSE_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Creed feedback"},
    )
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                raise NotDelivered(f"The form answered {response.status}.")
    except urllib.error.HTTPError as exc:
        raise NotDelivered(f"The form answered {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NotDelivered("The form couldn't be reached.") from exc
