"""Posting answers to one of the creator's Google Forms, as an anonymous response.

The public pages (feedback, Try Creed) send their answers here instead of to an email service. Each form emails the
creator for every response, and Creed keeps no copy. A form's question ids are public, in the form's own page.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 10


class NotDelivered(RuntimeError):
    pass


def post(url: str, values: list[tuple[str, str]], opener=urllib.request.urlopen) -> None:
    """Sends the answers, leaving out empty ones. A list, so a tick-box question can carry several answers."""
    body = urllib.parse.urlencode([(key, value) for key, value in values if value]).encode()
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Creed"},
    )
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                raise NotDelivered(f"The form answered {response.status}.")
    except urllib.error.HTTPError as exc:
        raise NotDelivered(f"The form answered {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NotDelivered("The form couldn't be reached.") from exc
