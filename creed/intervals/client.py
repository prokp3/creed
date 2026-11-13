"""HTTP client for the intervals.icu API: your personal API key, pacing and backoff.

intervals.icu takes a personal API key as HTTP Basic auth, with the literal username API_KEY, and "0" as the athlete ID
means "the athlete this key belongs to". Keys don't expire and there's no token to renew. Published limits are 10
requests a second and 2,500 per 15 minutes; past them it answers 429 with Retry-After, which this client honours.

The key is only ever sent to intervals.icu itself (or a local test server).
"""
from __future__ import annotations

import base64
import gzip
import http.client
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from creed.garmin.client import ApiStopped, AuthFailed, Resp

DEFAULT_BASE_URL = "https://intervals.icu"
INTERVALS_HOSTS = {"intervals.icu"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
BASE_URL_ENV_VAR = "INTERVALS_BASE_URL"
# intervals.icu sits behind Cloudflare, which may challenge Python's default user agent. This one says who's asking.
USER_AGENT = "Mozilla/5.0 (compatible; creed/0.1; personal dashboard; +https://github.com/prokp3/creed)"
MAX_BODY_BYTES = 128 * 1024 * 1024
GZIP_MAGIC = b"\x1f\x8b"

__all__ = ["ApiStopped", "AuthFailed", "Client", "Resp", "check_base_url"]


def check_base_url(url: str) -> str:
    """Refuse to send the key anywhere but intervals.icu (or a local test server)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.hostname in INTERVALS_HOSTS:
        return url.rstrip("/")
    if parsed.hostname in LOCAL_HOSTS:
        return url.rstrip("/")
    raise AuthFailed(f"Refusing to send the API key to {parsed.hostname!r}: not intervals.icu.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def gunzipped(body: bytes) -> bytes:
    """Activity files come gzipped. Anything that isn't gzip passes through unchanged."""
    if not body.startswith(GZIP_MAGIC):
        return body
    try:
        return gzip.decompress(body)
    except (OSError, EOFError):
        return body


class Client:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        delay: float = 0.25,
        max_requests: int = 1000,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        backoff: float = 5.0,
        deadline: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = check_base_url(base_url)
        if not api_key.strip():
            raise AuthFailed("The intervals.icu API key is empty.")
        self._api_key = api_key.strip()
        self._auth = "Basic " + base64.b64encode(f"API_KEY:{self._api_key}".encode()).decode()
        self.delay = delay
        self.max_requests = max_requests
        self.timeout = timeout
        self.sleep = sleep
        self.backoff = backoff
        self.deadline = deadline
        self._clock = clock
        self.requests = 0
        self.rate_limit_events: list[dict[str, Any]] = []
        self._last_request = 0.0
        self._opener = urllib.request.build_opener(_NoRedirect)

    def redact(self, text: str) -> str:
        for secret in (self._api_key, self._auth.removeprefix("Basic ")):
            text = text.replace(secret, "[REDACTED]")
        return text

    def ensure_token(self) -> None:
        """Nothing to renew: kept so the sync can treat both sources alike."""

    def _check_deadline(self, needed: float = 0.0) -> None:
        if self.deadline is not None and self._clock() + needed >= self.deadline:
            raise ApiStopped("Time budget used up.", "time")

    def _pace(self) -> None:
        wait = self._last_request + self.delay * (1 + random.random() * 0.25) - time.monotonic()
        if self.delay and wait > 0:
            self.sleep(wait)
        self._last_request = time.monotonic()

    def _send(self, url: str, accept: str) -> Resp:
        if self.requests >= self.max_requests:
            raise ApiStopped(f"Request budget of {self.max_requests} used up.", "budget")
        self._check_deadline()
        self._pace()
        self.requests += 1
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": self._auth, "Accept": accept, "User-Agent": USER_AGENT,
        })
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                return Resp(r.getcode(), r.read(MAX_BODY_BYTES), dict(r.headers.items()))
        except urllib.error.HTTPError as exc:
            # A redirect would carry the key somewhere else, so it's treated as an answer, not followed.
            return Resp(exc.code, exc.read(4096), dict(exc.headers.items()))
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            return Resp(0, error=type(exc).__name__)

    def get(self, path: str, params: dict[str, Any] | None = None, accept: str = "application/json") -> Resp:
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        attempts = 0
        while True:
            r = self._send(url, accept)
            if r.status == 401:
                raise AuthFailed("intervals.icu answered HTTP 401. The API key is wrong or was regenerated.")
            limited = r.status == 429
            if not (limited or r.status == 0 or r.status in (500, 502, 503, 504)):
                return r
            attempts += 1
            if limited:
                self.rate_limit_events.append(
                    {"status": r.status, "retry_after": r.headers.get("Retry-After"), "after_requests": self.requests}
                )
            if attempts >= (5 if limited else 2):
                if limited:
                    raise ApiStopped("intervals.icu kept answering HTTP 429; stopping to be polite.", "rate_limited")
                return r
            wait = self._retry_wait(r, attempts)
            self._check_deadline(wait)
            self.sleep(wait)

    def _retry_wait(self, r: Resp, attempts: int) -> float:
        retry_after = r.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), 300.0)
        return min(self.backoff * 2 ** (attempts - 1) * (1 + random.random() * 0.25), 300.0)
