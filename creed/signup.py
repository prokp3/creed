"""Answers from the public Try Creed page, passed on to the creator's "Try Creed" Google Form, which emails them."""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass

from creed import forms
from creed.feedback import EMAIL

# The "Try Creed" form. emailAddress is the address the form collects from every respondent.
FORM_RESPONSE_URL = (
    "https://docs.google.com/forms/d/e/1FAIpQLScQdtXWNZKVxbccSg4t7PZMwELSsg5bummqvamgjwyImps4aA/formResponse"
)
FIELDS = {
    "email": "emailAddress",
    "name": "entry.185597667",
    "watch": "entry.1162151608",
    "training": "entry.1450926009",
    "tried": "entry.489319538",
    "review": "entry.1573778358",
    "wishes": "entry.1390534331",
    "contact": "entry.84103958",
}
TRIED = {"yes": "Yes", "not-yet": "Not yet"}
CONTACT = {"yes": "Yes, you can email me about Creed", "no": "It's alright just passing through"}
LIMITS = {"email": 200, "name": 120, "watch": 120, "training": 300, "review": 4000, "wishes": 4000}


class InvalidSignup(ValueError):
    pass


@dataclass(frozen=True)
class Signup:
    email: str
    name: str
    contact: str
    watch: str = ""
    training: str = ""
    tried: str = ""
    review: str = ""
    wishes: str = ""


def clean(data: dict) -> Signup:
    """Trims and checks what the page sent. The form needs a name, an email and an answer about contact."""
    def text(name: str) -> str:
        value = data.get(name, "")
        return value.strip() if isinstance(value, str) else ""

    fields = {name: text(name) for name in LIMITS}
    if not fields["name"]:
        raise InvalidSignup("Tell me your name.")
    if not EMAIL.match(fields["email"]):
        raise InvalidSignup("Add your email address so I can reply.")
    for name, limit in LIMITS.items():
        if len(fields[name]) > limit:
            raise InvalidSignup(f"The {name} answer is too long. Keep it under {limit} characters.")
    tried = text("tried")
    if tried and tried not in TRIED:
        raise InvalidSignup("Choose whether you've tried Creed.")
    contact = text("contact")
    if contact not in CONTACT:
        raise InvalidSignup("Let me know whether I can email you.")
    return Signup(tried=tried, contact=contact, **fields)


def send(signup: Signup, opener=urllib.request.urlopen) -> None:
    forms.post(FORM_RESPONSE_URL, [
        (FIELDS["email"], signup.email),
        (FIELDS["name"], signup.name),
        (FIELDS["watch"], signup.watch),
        (FIELDS["training"], signup.training),
        (FIELDS["tried"], TRIED.get(signup.tried, "")),
        (FIELDS["review"], signup.review),
        (FIELDS["wishes"], signup.wishes),
        (FIELDS["contact"], CONTACT[signup.contact]),
    ], opener=opener)
