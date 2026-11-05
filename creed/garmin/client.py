"""HTTP client for the Garmin Personal API: pacing, backoff and token renewal.

The token flow comes from Garmin's FAQ and github.com/garmin/connect-personal-api-python.
The key is exchanged for a bearer token that lasts 24 hours, or until the key expires.
There are no refresh tokens, so renewing means exchanging the key again. The response
body is a raw JWT rather than JSON.

Rate limits are undocumented, so the client paces gently and backs off on any push-back.
"""
from __future__ import annotations

import base64
import http.client
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

DEFAULT_BASE_URL = "https://personal.connectapi.garmin.com"
GARMIN_HOSTS = {"personal.connectapi.garmin.com", "personal.connectapi.garmin.cn"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
BASE_URL_ENV_VAR = "GARMIN_PERSONAL_API_BASE_URL"
USER_AGENT = "creed/0.1 (personal dashboard; own data only)"

MAX_BODY_BYTES = 128 * 1024 * 1024
# Same margin as Garmin's official client: renew once less than an hour is left.
TOKEN_RENEW_MARGIN_SECONDS = 3600


class AuthFailed(Exception):
    """The API key could not be exchanged for a token."""


class ApiStopped(Exception):
    """Stop calling the API but keep what was gathered. `reason` is budget, time or rate_limited."""

    def __init__(self, message: str, reason: str = "budget") -> None:
        super().__init__(message)
        self.reason = reason


def check_base_url(url: str) -> str:
    """Refuse to send the key anywhere but Garmin (or a local test server)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.hostname in GARMIN_HOSTS:
        return url.rstrip("/")
    if parsed.hostname in LOCAL_HOSTS:
        return url.rstrip("/")
    raise AuthFailed(f"Refusing to send the API key to {parsed.hostname!r}: not a Garmin API host.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass
class Resp:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body)


class Client:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        delay: float = 1.2,
        max_requests: int = 1000,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        backoff: float = 5.0,
        deadline: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        token: str | None = None,
        on_token: Callable[[str, float | None], None] | None = None,
        on_request: Callable[[int], None] | None = None,
    ) -> None:
        self.base_url = check_base_url(base_url)
        self._api_key = api_key
        self._token = token
        self.delay = delay
        self.max_requests = max_requests
        self.timeout = timeout
        self.sleep = sleep
        self.backoff = backoff
        self.deadline = deadline
        self._clock = clock
        self._on_token = on_token
        self._on_request = on_request
        self.requests = 0
        self.token_info: dict[str, Any] = {"minted": 0}
        self.rate_limit_events: list[dict[str, Any]] = []
        self.rate_limit_headers: set[str] = set()
        self._last_request = 0.0
        self._opener = urllib.request.build_opener(_NoRedirect)

    def redact(self, text: str) -> str:
        for secret in (self._api_key, self._token):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return re.sub(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*", "[REDACTED-JWT]", text)

    @property
    def token_expires_at(self) -> float | None:
        return jwt_expiry(self._token) if self._token else None

    def _token_is_usable(self) -> bool:
        if self._token is None:
            return False
        expires = self.token_expires_at
        return expires is None or expires - time.time() > TOKEN_RENEW_MARGIN_SECONDS

    def ensure_token(self) -> None:
        if not self._token_is_usable():
            self.mint_token()

    def _check_deadline(self, needed: float = 0.0) -> None:
        if self.deadline is not None and self._clock() + needed >= self.deadline:
            raise ApiStopped("Time budget used up.", "time")

    def _pace(self) -> None:
        wait = self._last_request + self.delay * (1 + random.random() * 0.25) - time.monotonic()
        if self.delay and wait > 0:
            self.sleep(wait)
        self._last_request = time.monotonic()

    def _send(self, method: str, url: str, headers: dict[str, str]) -> Resp:
        headers = dict(headers)
        for _ in range(4):
            if self.requests >= self.max_requests:
                raise ApiStopped(f"Request budget of {self.max_requests} used up.", "budget")
            self._check_deadline()
            self._pace()
            self.requests += 1
            if self._on_request:
                self._on_request(self.requests)
            req = urllib.request.Request(url, method=method, headers=headers)
            try:
                with self._opener.open(req, timeout=self.timeout) as r:
                    return Resp(r.getcode(), r.read(MAX_BODY_BYTES), dict(r.headers.items()))
            except urllib.error.HTTPError as exc:
                location = exc.headers.get("Location")
                if exc.code in (301, 302, 303, 307, 308) and location:
                    target = urllib.parse.urljoin(url, location)
                    parsed = urllib.parse.urlparse(target)
                    if parsed.scheme != "https" and parsed.hostname not in LOCAL_HOSTS:
                        return Resp(exc.code, error="refused non-https redirect")
                    # A presigned download host must never see the bearer token.
                    if parsed.hostname != urllib.parse.urlparse(url).hostname:
                        headers.pop("Authorization", None)
                    url = target
                    continue
                return Resp(exc.code, exc.read(4096), dict(exc.headers.items()))
            except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
                return Resp(0, error=type(exc).__name__)
        return Resp(0, error="too many redirects")

    def mint_token(self) -> None:
        r = self._send(
            "POST",
            f"{self.base_url}{TOKEN_PATH}",
            {"Authorization": f"ApiKey {self._api_key}", "Accept": "*/*", "User-Agent": USER_AGENT},
        )
        if r.status == 0:
            raise AuthFailed(f"Could not reach Garmin to get a token ({r.error}).")
        if not r.ok:
            hint = " The key is wrong, deleted or expired." if r.status in (401, 403) else ""
            raise AuthFailed(f"Token exchange failed with HTTP {r.status}.{hint}")
        text = r.body.decode("utf-8", "replace").strip()
        response_format = "raw text JWT"
        if text.startswith("{"):
            response_format = "JSON object"
            text = str(json.loads(text).get("access_token", ""))
        if not text:
            raise AuthFailed("Token endpoint returned 200 with no token.")
        self._token = text
        self.token_info = {
            "minted": self.token_info["minted"] + 1,
            "response_format": response_format,
            **jwt_facts(text),
        }
        if self._on_token:
            self._on_token(text, jwt_expiry(text))

    def get(self, path: str, params: dict[str, Any] | None = None, accept: str = "application/json") -> Resp:
        self.ensure_token()
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        attempts = 0
        reminted = False
        while True:
            r = self._send(
                "GET",
                url,
                {"Authorization": f"Bearer {self._token}", "Accept": accept, "User-Agent": USER_AGENT},
            )
            for name in r.headers:
                if "ratelimit" in name.lower() or name.lower() == "retry-after":
                    self.rate_limit_headers.add(name)
            if r.status == 401 and not reminted:
                reminted = True
                self.mint_token()
                continue
            limited = r.status in (429, 503)
            if not (limited or r.status == 0 or r.status in (500, 502, 504)):
                return r
            attempts += 1
            if limited:
                self.rate_limit_events.append(
                    {"status": r.status, "retry_after": r.headers.get("Retry-After"), "after_requests": self.requests}
                )
            if attempts >= (5 if limited else 2):
                if limited:
                    raise ApiStopped(f"Garmin kept answering HTTP {r.status}; stopping to be polite.", "rate_limited")
                return r
            wait = self._retry_wait(r, attempts)
            self._check_deadline(wait)
            self.sleep(wait)

    def _retry_wait(self, r: Resp, attempts: int) -> float:
        retry_after = r.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), 300.0)
        return min(self.backoff * 2 ** (attempts - 1) * (1 + random.random() * 0.25), 300.0)


def _jwt_claims(token: str) -> dict[str, Any] | None:
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (IndexError, ValueError):
        return None
    return claims if isinstance(claims, dict) else None


def jwt_expiry(token: str) -> float | None:
    """The token's exp claim in seconds since the epoch, without verifying its signature."""
    exp = (_jwt_claims(token) or {}).get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None


def jwt_facts(token: str) -> dict[str, Any]:
    """Claim names, scopes and lifetime only: no subject, IDs or the token itself."""
    claims = _jwt_claims(token)
    if claims is None:
        return {"is_jwt": False}
    facts: dict[str, Any] = {"is_jwt": True, "claim_names": sorted(claims)}
    for name in ("scope", "scopes", "authorities"):
        if name in claims:
            facts[name] = claims[name]
    if isinstance(claims.get("exp"), (int, float)):
        facts["expires_in_hours"] = round((claims["exp"] - time.time()) / 3600, 2)
    if isinstance(claims.get("exp"), (int, float)) and isinstance(claims.get("iat"), (int, float)):
        facts["lifetime_hours"] = round((claims["exp"] - claims["iat"]) / 3600, 2)
    return facts
