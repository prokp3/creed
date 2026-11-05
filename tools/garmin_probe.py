#!/usr/bin/env python3
"""Garmin Connect Personal API data-availability probe.

Reports, per documented endpoint, whether your account returns data and how far
back it goes, so the metrics plan can be built on what is really there.

Standard library only: no install step.

    python tools/garmin_probe.py --save-key     # paste the key once (input hidden)
    python tools/garmin_probe.py                # run it; takes about 5-15 minutes

Endpoints, window limits and the token flow come from Garmin's own Swagger page
(OpenAPI 3.0.1, version 1.0.0) and github.com/garmin/connect-personal-api-python,
both read on 2026-11-05. Nothing undocumented is ever called. Things the API does
not document as available are looked for as field names in the live responses.

Privacy by construction:
  * the report holds field names, counts, date ranges and aggregates for an
    explicit allowlist of fields; names, IDs, GPS and free text never reach it
  * the key and the bearer token are never printed or written to the report
  * FIT files are read in memory and dropped; only message and field counts are kept
"""
from __future__ import annotations

import argparse
import base64
import getpass
import http.client
import io
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://personal.connectapi.garmin.com"
GARMIN_HOSTS = {"personal.connectapi.garmin.com", "personal.connectapi.garmin.cn"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
KEY_ENV_VAR = "GARMIN_PERSONAL_API_KEY"
BASE_URL_ENV_VAR = "GARMIN_PERSONAL_API_BASE_URL"
# Same location Garmin's official client reads, so the key is only stored once.
DEFAULT_KEY_FILE = Path("~/.config/garmin/connect-personal-api-key")
USER_AGENT = "triathlon-dashboard-probe/0.1 (personal data-availability check)"

MAX_BODY_BYTES = 128 * 1024 * 1024
MAX_FIT_BYTES = 64 * 1024 * 1024
WINDOW_LADDER = (365, 180, 90, 31, 28, 14, 7, 1)
DAY_OFFSETS = (0, 1, 2, 7, 30, 90, 180, 365, 730, 1095, 1460, 1825)
EMPTY_STOP_DAYS = 180
EXIT_OK, EXIT_AUTH, EXIT_PARTIAL = 0, 2, 3


class ProbeStopped(Exception):
    """Stop probing but still write a report from what was gathered."""


class AuthFailed(Exception):
    """The API key could not be exchanged for a token."""


# ---------------------------------------------------------------------------
# Key handling
# ---------------------------------------------------------------------------


def resolve_api_key(key_file: str | None = None) -> str:
    """Explicit file, then environment variable, then the default file."""
    if key_file:
        return _read_key_file(Path(key_file).expanduser())
    env = os.environ.get(KEY_ENV_VAR)
    if env is not None:
        if not env.strip():
            raise AuthFailed(f"{KEY_ENV_VAR} is set but empty.")
        return env.strip()
    default = DEFAULT_KEY_FILE.expanduser()
    if default.exists():
        return _read_key_file(default)
    raise AuthFailed(
        "No API key found. Create one at https://connect.garmin.com/app/settings/personalApiToken "
        "then run: python tools/garmin_probe.py --save-key"
    )


def _read_key_file(path: Path) -> str:
    try:
        key = path.read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        raise AuthFailed(f"Could not read key file {path}: {type(exc).__name__}") from exc
    if not key:
        raise AuthFailed(f"Key file {path} is empty.")
    return key


def save_api_key(key: str, path: Path | None = None) -> Path:
    key = key.strip()
    if not key:
        raise AuthFailed("No key entered; nothing saved.")
    target = (path or DEFAULT_KEY_FILE).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key)
    return target


def check_base_url(url: str) -> str:
    """Refuse to send the key anywhere but Garmin (or a local test server)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.hostname in GARMIN_HOSTS:
        return url.rstrip("/")
    if parsed.hostname in LOCAL_HOSTS:
        return url.rstrip("/")
    raise AuthFailed(f"Refusing to send the API key to {parsed.hostname!r}: not a Garmin API host.")


# ---------------------------------------------------------------------------
# HTTP client: pacing, backoff, token renewal
# ---------------------------------------------------------------------------


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
    """Rate limits are undocumented, so pace gently and back off on any push-back."""

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
    ) -> None:
        self.base_url = check_base_url(base_url)
        self._api_key = api_key
        self._token: str | None = None
        self.delay = delay
        self.max_requests = max_requests
        self.timeout = timeout
        self.sleep = sleep
        self.backoff = backoff
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

    def _pace(self) -> None:
        wait = self._last_request + self.delay * (1 + random.random() * 0.25) - time.monotonic()
        if self.delay and wait > 0:
            self.sleep(wait)
        self._last_request = time.monotonic()

    def _send(self, method: str, url: str, headers: dict[str, str]) -> Resp:
        headers = dict(headers)
        for _ in range(4):
            if self.requests >= self.max_requests:
                raise ProbeStopped(f"Request budget of {self.max_requests} used up.")
            self._pace()
            self.requests += 1
            if self.requests % 25 == 0:
                print(f"    ...{self.requests} requests so far", flush=True)
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
            **_jwt_facts(text),
        }

    def get(self, path: str, params: dict[str, Any] | None = None, accept: str = "application/json") -> Resp:
        if self._token is None:
            self.mint_token()
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
                    raise ProbeStopped(f"Garmin kept answering HTTP {r.status}; stopping to be polite.")
                return r
            self.sleep(self._retry_wait(r, attempts))

    def _retry_wait(self, r: Resp, attempts: int) -> float:
        retry_after = r.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), 300.0)
        return min(self.backoff * 2 ** (attempts - 1) * (1 + random.random() * 0.25), 300.0)


def _jwt_facts(token: str) -> dict[str, Any]:
    """Claim names, scopes and lifetime only: no subject, IDs or the token itself."""
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (IndexError, ValueError):
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


# ---------------------------------------------------------------------------
# Response shape tracking: names and counts, values only for an allowlist
# ---------------------------------------------------------------------------

NUMERIC_STAT_FIELDS = {
    "lastNightAvg", "lastNight5MinHigh", "weeklyAvg", "balancedLow", "balancedUpper", "lowUpper",
    "markerValue", "hrvValue", "restingValue", "restingHeartRate", "lastSevenDaysAvgRestingHeartRate",
    "minHeartRate", "maxHeartRate", "minValue", "maxValue", "avgValue", "value", "actual", "baseline",
    "maxHeartRateUsed", "restingHeartRateUsed", "lactateThresholdHeartRateUsed",
    "zone1Floor", "zone2Floor", "zone3Floor", "zone4Floor", "zone5Floor",
    "sleepTimeSeconds", "deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds", "awakeSleepSeconds",
    "unmeasurableSleepSeconds", "napTimeSeconds", "averageRespirationValue", "lowestRespirationValue",
    "highestRespirationValue", "avgWakingRespirationValue", "averageSpO2Value", "averageSpO2", "averageSpo2",
    "overallStressLevel", "averageStressLevel", "avgSleepStress", "charged", "drained",
    "vO2MaxValue", "activityTrainingLoad", "aerobicTrainingEffect", "anaerobicTrainingEffect",
    "trainingStressScore", "maxHR", "averageHR", "moderate", "vigorous", "moderateIntensityMinutes",
    "vigorousIntensityMinutes", "totalSteps", "fitnessAge",
}
ENUM_STAT_FIELDS = {
    "status", "typeKey", "sleepWindowConfirmationType", "sleepQualityTypePK", "sleepResultTypePK",
    "trainingMethod", "sport", "deviceRemCapable", "sleepFromDevice", "sleepWindowConfirmed",
    "qualifierKey", "includesWellnessData", "includesActivityData", "source", "timeZone",
    "measurementSystem", "breathingDisruptionSeverity", "stressQualifier", "trainingEffectLabel",
    "isParent", "restingHrAutoUpdateUsed", "summaryType", "wellnessActivityType",
}
TIMESTAMP_FIELD = re.compile(r"(timestamp|time(gmt|local)$|^(start|end)time|^calendarDate$|^date$)", re.I)
VOLATILE_KEY = re.compile(r"^\d|^.{61,}$")
NOT_MEASURED = {"NONE", "INVALID", "UNDEFINED", "UNKNOWN"}


@dataclass
class FieldStat:
    present: int = 0
    nonnull: int = 0
    measured: int = 0  # Non-null and not a placeholder: above zero, or a real label rather than NONE.
    types: Counter = field(default_factory=Counter)
    dates: set[date] = field(default_factory=set)
    positive_dates: set[date] = field(default_factory=set)
    numbers: list[float] = field(default_factory=list)
    values: Counter = field(default_factory=Counter)
    patterns: Counter = field(default_factory=Counter)


class Shape:
    def __init__(self) -> None:
        self.paths: dict[str, FieldStat] = {}

    def observe(self, obj: Any, day: date | None = None, prefix: str = "", depth: int = 0) -> None:
        if isinstance(obj, dict) and depth < 12:
            for key, value in obj.items():
                name = "<key>" if VOLATILE_KEY.match(str(key)) else str(key)
                path = f"{prefix}.{name}" if prefix else name
                self._leaf(path, name, value, day)
                if isinstance(value, dict):
                    self.observe(value, day, path, depth + 1)
                elif isinstance(value, list) and value and isinstance(value[0], dict):
                    for item in value:
                        self.observe(item, day, f"{path}[]", depth + 1)

    def _leaf(self, path: str, name: str, value: Any, day: date | None) -> None:
        if path not in self.paths:
            if len(self.paths) >= 2000:
                return
            self.paths[path] = FieldStat()
        stat = self.paths[path]
        stat.present += 1
        stat.types[_type_name(value)] += 1
        if value in (None, "", [], {}):
            return
        stat.nonnull += 1
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        # Garmin uses sentinels such as -1 or "NONE" for "not measured".
        measured = value > 0 if is_number else str(value) not in NOT_MEASURED
        stat.measured += 1 if measured else 0
        if day is not None:
            stat.dates.add(day)
            if measured:
                stat.positive_dates.add(day)
        if is_number and name in NUMERIC_STAT_FIELDS:
            stat.numbers.append(float(value))
        elif name in ENUM_STAT_FIELDS and isinstance(value, (str, bool)) and len(str(value)) <= 40:
            if len(stat.values) < 30 or str(value) in stat.values:
                stat.values[str(value)] += 1
        if TIMESTAMP_FIELD.search(name):
            stat.patterns[re.sub(r"\d", "9", str(value)) if isinstance(value, str) else _type_name(value)] += 1

    def match(self, regex: str) -> list[FieldStat]:
        rx = re.compile(regex)
        return [stat for path, stat in self.paths.items() if rx.search(path)]

    def search_names(self, regex: str) -> list[str]:
        rx = re.compile(regex, re.I)
        return [path for path in self.paths if rx.search(path)]


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array" if not value or not isinstance(value[0], list) else "array-of-rows"
    return type(value).__name__


def _deep(obj: Any, key: str, depth: int = 0) -> Any:
    """First non-null value for key anywhere in obj; tolerates wrappers the spec omits."""
    if depth > 8:
        return None
    if isinstance(obj, dict):
        if obj.get(key) is not None:
            return obj[key]
        for value in obj.values():
            if isinstance(value, dict):
                found = _deep(value, key, depth + 1)
                if found is not None:
                    return found
    return None


def _pos(obj: Any, key: str) -> bool:
    value = _deep(obj, key)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def date_of(value: Any) -> date | None:
    """Calendar date as written. Epoch-ms 'Local' fields are shifted, so read them as-is."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):  # The spec's ConnectDate and ConnectTimestamp are objects.
        return date_of(value.get("date"))
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def timestamp_of(value: Any) -> datetime | None:
    """Parse a timestamp without assuming a zone; the spec says strings carry no offset."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):
        return timestamp_of(value.get("date"))
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip().replace("Z", "")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# FIT reader: structure and field coverage only, values are not kept
# ---------------------------------------------------------------------------

FIT_BASE_SIZE = {0: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 1, 8: 4, 9: 8, 10: 1, 11: 2, 12: 4, 13: 1, 14: 8, 15: 8, 16: 8}
FIT_INVALID = {
    0: 0xFF, 1: 0x7F, 2: 0xFF, 3: 0x7FFF, 4: 0xFFFF, 5: 0x7FFFFFFF, 6: 0xFFFFFFFF, 7: 0x00,
    8: 0xFFFFFFFF, 9: 0xFFFFFFFFFFFFFFFF, 10: 0x00, 11: 0x0000, 12: 0x00000000, 13: 0xFF,
    14: 0x7FFFFFFFFFFFFFFF, 15: 0xFFFFFFFFFFFFFFFF, 16: 0x0000000000000000,
}
FIT_MESSAGES = {
    0: "file_id", 2: "device_settings", 3: "user_profile", 7: "zones_target", 8: "hr_zone", 9: "power_zone",
    12: "sport", 18: "session", 19: "lap", 20: "record", 21: "event", 23: "device_info", 34: "activity",
    35: "software", 49: "file_creator", 78: "hrv", 101: "length", 132: "hr", 160: "gps_metadata",
    206: "field_description", 207: "developer_data_id", 216: "time_in_zone", 290: "beat_intervals",
    297: "respiration_rate", 312: "split", 313: "split_summary",
}
FIT_RECORD_FIELDS = {
    0: "position_lat", 1: "position_long", 2: "altitude", 3: "heart_rate", 4: "cadence", 5: "distance",
    6: "speed", 7: "power", 13: "temperature", 53: "fractional_cadence", 73: "enhanced_speed",
    78: "enhanced_altitude", 253: "timestamp",
}
FIT_SESSION_FIELDS = {
    5: "sport", 6: "sub_sport", 7: "total_elapsed_time", 8: "total_timer_time", 9: "total_distance",
    16: "avg_heart_rate", 17: "max_heart_rate", 20: "avg_power", 21: "max_power", 24: "total_training_effect",
    34: "normalized_power", 35: "training_stress_score", 36: "intensity_factor", 44: "pool_length",
    137: "total_anaerobic_training_effect",
}
FIT_MSG_RECORD, FIT_MSG_SESSION, FIT_MSG_PHYSIO = 20, 18, 140


def read_fit(data: bytes) -> dict[str, Any]:
    """Count messages and valid fields in a FIT file. Bad input yields parse_error, never a crash."""
    messages: Counter = Counter()
    valid_fields: dict[int, Counter] = defaultdict(Counter)
    record_times: list[int] = []
    result: dict[str, Any] = {"parse_error": None, "truncated": False, "fit_files": 0}
    pos = 0
    try:
        while pos + 12 <= len(data):
            header_size = data[pos]
            if header_size not in (12, 14) or data[pos + 8 : pos + 12] != b".FIT":
                if result["fit_files"] == 0:
                    raise ValueError("no .FIT signature")
                break
            data_size = int.from_bytes(data[pos + 4 : pos + 8], "little")
            start = pos + header_size
            end = start + data_size
            if end > len(data):
                result["truncated"] = True
                end = len(data)
            _read_fit_records(data, start, end, messages, valid_fields, record_times)
            result["fit_files"] += 1
            pos = end + 2
        if result["fit_files"] == 0:
            raise ValueError("file too short")
    except (IndexError, ValueError, KeyError) as exc:
        result["parse_error"] = f"{type(exc).__name__}: {exc}"

    record_count = messages.get(FIT_MSG_RECORD, 0)
    deltas = [b - a for a, b in zip(record_times, record_times[1:]) if b >= a]
    result.update(
        messages={FIT_MESSAGES.get(num, f"unknown_{num}"): n for num, n in sorted(messages.items())},
        undocumented_messages=sorted(num for num in messages if num not in FIT_MESSAGES),
        record_count=record_count,
        record_median_interval_s=statistics.median(deltas) if deltas else None,
        record_field_pct={
            FIT_RECORD_FIELDS.get(num, f"field_{num}"): round(100 * n / record_count, 1)
            for num, n in sorted(valid_fields[FIT_MSG_RECORD].items())
        }
        if record_count
        else {},
        session_fields=sorted(
            FIT_SESSION_FIELDS.get(num, f"field_{num}") for num in valid_fields[FIT_MSG_SESSION]
        ),
        message_140_field_numbers=sorted(valid_fields[FIT_MSG_PHYSIO]),
    )
    return result


def _read_fit_records(
    data: bytes,
    start: int,
    end: int,
    messages: Counter,
    valid_fields: dict[int, Counter],
    record_times: list[int],
) -> None:
    definitions: dict[int, tuple[int, str, list[tuple[int, int, int]], int]] = {}
    last_ts: int | None = None
    p = start
    while p < end:
        header = data[p]
        p += 1
        compressed_offset: int | None = None
        if header & 0x80:
            local = (header >> 5) & 0x03
            compressed_offset = header & 0x1F
        elif header & 0x40:
            local = header & 0x0F
            has_dev = bool(header & 0x20)
            byteorder = "big" if data[p + 1] else "little"
            global_num = int.from_bytes(data[p + 2 : p + 4], byteorder)
            count = data[p + 4]
            p += 5
            fields = [(data[p + 3 * i], data[p + 3 * i + 1], data[p + 3 * i + 2]) for i in range(count)]
            p += 3 * count
            dev_size = 0
            if has_dev:
                dev_count = data[p]
                p += 1
                dev_size = sum(data[p + 3 * i + 1] for i in range(dev_count))
                p += 3 * dev_count
            definitions[local] = (global_num, byteorder, fields, dev_size)
            continue
        else:
            local = header & 0x0F
        if local not in definitions:
            raise ValueError("data message before its definition")
        global_num, byteorder, fields, dev_size = definitions[local]
        if p + sum(f[1] for f in fields) + dev_size > end:
            return  # Trailing partial message in a truncated file.
        messages[global_num] += 1
        ts: int | None = None
        for num, size, base in fields:
            raw = data[p : p + size]
            p += size
            if _fit_field_valid(raw, base, byteorder):
                valid_fields[global_num][num] += 1
                if num == 253 and size == 4:
                    ts = int.from_bytes(raw, byteorder)
        p += dev_size
        if ts is None and compressed_offset is not None and last_ts is not None:
            ts = (last_ts & ~0x1F) | compressed_offset
            if compressed_offset < (last_ts & 0x1F):
                ts += 0x20
        if ts is not None:
            last_ts = ts
            if global_num == FIT_MSG_RECORD:
                record_times.append(ts)


def _fit_field_valid(raw: bytes, base: int, byteorder: str) -> bool:
    number = base & 0x1F
    element = FIT_BASE_SIZE.get(number)
    if element is None or not raw:
        return bool(raw)
    invalid = FIT_INVALID[number]
    if number == 7:
        return any(raw)
    for i in range(0, len(raw) - element + 1, element):
        if int.from_bytes(raw[i : i + element], byteorder) != invalid:
            return True
    return False


def read_activity_zip(content: bytes) -> dict[str, Any]:
    """The download endpoint returns a ZIP. Read it in memory and never extract to disk."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        # Some originals may not be zipped: look at the bytes directly.
        return {"zip": False, "bytes": len(content), **read_fit(content)}
    with archive:
        names = archive.infolist()
        fits = [i for i in names if i.filename.lower().endswith(".fit") and i.file_size <= MAX_FIT_BYTES]
        extensions = sorted({Path(i.filename).suffix.lower() for i in names})
        if not fits:
            return {"zip": True, "bytes": len(content), "entries": len(names), "extensions": extensions,
                    "parse_error": "no .fit entry in the archive"}
        fit = max(fits, key=lambda i: i.file_size)
        return {"zip": True, "bytes": len(content), "entries": len(names), "extensions": extensions,
                **read_fit(archive.read(fit))}


# ---------------------------------------------------------------------------
# What gets probed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RangeEndpoint:
    """A date-range endpoint. doc_max_days is the limit stated in Garmin's Swagger, if any."""

    id: str
    path: str
    params: tuple[str, str] | None
    doc_max_days: int | None
    first_window: int
    rows_key: str | None
    date_key: str
    has_data: Callable[[dict], bool]


@dataclass(frozen=True)
class DayEndpoint:
    id: str
    path: str
    param: str | None
    has_data: Callable[[Any], bool]


def _v2_has_data(row: dict) -> bool:
    heart = row.get("heartRate") or {}
    steps = (row.get("movement") or {}).get("steps") or {}
    return _pos(heart, "restingValue") or _pos(steps, "value")


def _stress_has_data(row: dict) -> bool:
    value = _deep(row, "overallStressLevel")
    return isinstance(value, (int, float)) and value >= 0


def _weight_has_data(row: dict) -> bool:
    return _pos(row, "weight")


RANGE_ENDPOINTS = (
    RangeEndpoint("daily_summaries_v2", "/usersummary-service/v2/dailysummaries", ("startDate", "endDate"),
                  365, 365, "data", "calendarDate", _v2_has_data),
    RangeEndpoint("hrv_daily", "/hrv-service/hrv/daily/{start}/{end}", None,
                  None, 365, "hrvSummaries", "calendarDate", lambda r: _pos(r, "lastNightAvg")),
    RangeEndpoint("sleep_summaries", "/sleep-service/sleep/dailySleepSummariesByDate", ("startDate", "endDate"),
                  31, 31, None, "calendarDate", lambda r: _pos(r, "sleepTimeSeconds")),
    RangeEndpoint("body_battery_daily", "/wellness-service/wellness/bodyBattery/reports/daily", ("startDate", "endDate"),
                  31, 31, None, "date",
                  lambda r: _pos(r, "charged") or _pos(r, "drained") or bool(r.get("bodyBatteryValuesArray"))),
    RangeEndpoint("stress_daily", "/usersummary-service/stats/stress/daily/{start}/{end}", None,
                  28, 28, None, "calendarDate", _stress_has_data),
    RangeEndpoint("steps_daily", "/usersummary-service/stats/steps/daily/{start}/{end}", None,
                  28, 28, None, "calendarDate", lambda r: _pos(r, "totalSteps")),
    RangeEndpoint("hydration_daily", "/usersummary-service/stats/hydration/daily/{start}/{end}", None,
                  31, 31, None, "calendarDate", lambda r: _pos(r, "valueInML")),
    RangeEndpoint("weight_all", "/weight-service/weight/all/{start}/{end}", None,
                  None, 365, None, "calendarDate", _weight_has_data),
)

DAY_ENDPOINTS = (
    DayEndpoint("daily_sleep", "/sleep-service/sleep/dailySleep", "date", lambda o: _pos(o, "sleepTimeSeconds")),
    DayEndpoint("hrv_chart", "/hrv-service/hrv/{date}", None, lambda o: _pos(o, "lastNightAvg")),
    DayEndpoint("daily_heart_rate", "/wellness-service/wellness/dailyHeartRate", "date",
                lambda o: _pos(o, "restingHeartRate") or bool(isinstance(o, dict) and o.get("heartRateValues"))),
    DayEndpoint("spo2", "/wellness-service/wellness/daily/spo2acclimation/{date}", None,
                lambda o: _pos(o, "averageSpO2") or bool(isinstance(o, dict) and o.get("spO2HourlyAverages"))),
    DayEndpoint("user_summary_daily", "/usersummary-service/usersummary/daily", "calendarDate",
                lambda o: _pos(o, "restingHeartRate") or _pos(o, "totalSteps")),
    DayEndpoint("fitness_age", "/fitnessage-service/fitnessage/v2/{date}", None, lambda o: _fitness_age_has(o)),
)


def _fitness_age_has(obj: Any) -> bool:
    items = obj if isinstance(obj, list) else [obj]
    return any(_pos(item, "fitnessAge") for item in items)


NOT_PROBED = {
    "/periodichealth-service/menstrualcycle/summary/{calendarDate}": "Sensitive and out of scope for this app.",
    "/periodichealth-service/menstrualcycle/dayview/{calendarDate}": "Sensitive and out of scope for this app.",
}

ACTIVITY_FIELDS = (
    "startTimeGMT", "startTimeLocal", "duration", "movingDuration", "elapsedDuration", "distance", "averageSpeed",
    "averageHR", "maxHR", "hrTimeInZone_1", "hrTimeInZone_3", "hrTimeInZone_5", "activityTrainingLoad",
    "aerobicTrainingEffect", "anaerobicTrainingEffect", "vO2MaxValue", "moderateIntensityMinutes",
    "vigorousIntensityMinutes", "avgPower", "normPower", "trainingStressScore", "intensityFactor", "averageSwolf",
    "activeLengths", "strokes", "poolLength", "lapCount", "avgRespirationRate", "differenceBodyBattery",
    "lactateThresholdBpm", "maxFtp", "hasSeedFirstbeatProfile", "manufacturer",
)


def discipline_of(type_key: str | None) -> str:
    key = (type_key or "").lower()
    if key in ("multi_sport", "transition", "transition_v2") or "transition" in key:
        return "multisport"
    if "swim" in key:
        return "swim"
    if "cycl" in key or "biking" in key or "bike" in key or "virtual_ride" in key:
        return "bike"
    if "run" in key:
        return "run"
    return "other"


class EndpointResult:
    def __init__(self, id: str, path: str, kind: str, doc_max_days: int | None = None) -> None:
        self.id, self.path, self.kind, self.doc_max_days = id, path, kind, doc_max_days
        self.statuses: Counter = Counter()
        self.requests = 0
        self.rows = 0
        self.days: set[date] = set()
        self.queried_days = 0
        self.accepted_window: int | None = None
        self.rejected_windows: dict[int, int] = {}
        self.stop_reason: str | None = None
        self.notes: list[str] = []
        self.shape = Shape()

    def record(self, r: Resp) -> None:
        self.requests += 1
        self.statuses[r.status if r.status else f"network:{r.error}"] += 1

    @property
    def any_ok(self) -> bool:
        return any(isinstance(code, int) and 200 <= code < 300 for code in self.statuses)


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------


class Probe:
    def __init__(self, client: Client, *, years: float = 6.0, today: date | None = None,
                 raw_dir: Path | None = None) -> None:
        self.client = client
        self.years = years
        self.today = today or date.today()
        self.floor = self.today - timedelta(days=int(years * 365.25))
        # Daily data can predate the first recorded activity, so this only guards against
        # stopping too soon inside a wear gap. It never limits how far back the walk can go.
        self.activity_floor = self.today
        self.raw_dir = raw_dir
        self.results: dict[str, EndpointResult] = {}
        self.activities: list[dict[str, Any]] = []
        self.by_type: Counter = Counter()
        self.discipline_fields: dict[str, dict[str, list[int]]] = {}
        self.discipline_counts: Counter = Counter()
        self.max_hr_values: list[int] = []
        self.fit_samples: list[dict[str, Any]] = []
        self.sleep_checks = _new_sleep_checks()
        self.hrv_checks = {"nights": 0, "calendar_is_wake_date": 0, "calendar_is_bed_date": 0,
                           "readings_per_night": [], "reading_interval_min": []}
        self.rhr_v2: dict[date, float] = {}
        self.rhr_compare = {"compared": 0, "equal": 0, "max_abs_difference": 0.0}
        self.hrv_by_day: dict[date, float] = {}
        self.hrv_measure = {"days_with_rmssd": 0, "days_with_sdrr": 0, "compared_to_last_night_avg": 0,
                            "median_abs_difference_ms": None}
        self.freshness: dict[str, Any] = {}
        self.stopped: str | None = None
        self.started = datetime.now(timezone.utc)

    # -- helpers ---------------------------------------------------------

    def _result(self, id: str, path: str, kind: str, doc_max_days: int | None = None) -> EndpointResult:
        if id not in self.results:
            self.results[id] = EndpointResult(id, path, kind, doc_max_days)
        return self.results[id]

    def _save_raw(self, name: str, r: Resp) -> None:
        if self.raw_dir is None or not r.body:
            return
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        target = self.raw_dir / f"{name}.json"
        if not target.exists():
            target.write_bytes(r.body)

    def _once(self, id: str, path: str, params: dict[str, Any] | None = None) -> Any:
        res = self._result(id, path, "single")
        r = self.client.get(path, params)
        res.record(r)
        if not r.ok:
            return None
        try:
            body = r.json()
        except ValueError:
            res.notes.append("Response was not JSON.")
            return None
        self._save_raw(id, r)
        if isinstance(body, list):
            res.rows += len(body)
            for item in body:
                res.shape.observe(item)
        else:
            res.rows += 1 if body else 0
            res.shape.observe(body)
        return body

    # -- steps -----------------------------------------------------------

    def probe_profile_and_zones(self) -> None:
        self._once("profile_settings", "/userprofile-service/userprofile/settings")
        self._once("heart_rate_zones", "/biometric-service/heartRateZones/v2")

    def probe_activities(self) -> None:
        path = "/activitylist-service/activities/search/activities"
        res = self._result("activities", path, "paged")
        start, limit = 0, 99
        previous_first: Any = object()
        while True:
            r = self.client.get(path, {"start": start, "limit": limit, "excludeChildren": "false"})
            res.record(r)
            if not r.ok:
                if r.status == 400 and limit > 20 and not self.activities:
                    res.notes.append(f"limit={limit} rejected with HTTP 400; retrying smaller.")
                    limit = limit // 2
                    continue
                res.stop_reason = f"HTTP {r.status or r.error} at offset {start}"
                break
            rows = r.json() or []
            if not rows:
                break
            self._save_raw("activities", r)
            first = rows[0].get("activityId")
            if first == previous_first:
                res.notes.append("Paging ignored the start offset; stopped.")
                break
            previous_first = first
            for row in rows:
                self._take_activity(res, row)
            # The server may cap the page below the limit asked for, so only an empty page ends this.
            start += len(rows)
        res.notes.append(f"Asked for {limit} per page. Swagger gives 99 as the default and states no maximum.")
        if self.activities:
            oldest = min(a["day"] for a in self.activities if a["day"])
            self.activity_floor = oldest - timedelta(days=30)
            print(f"    {len(self.activities)} activities back to {oldest}; "
                  f"looking for daily data back as far as {self.floor}", flush=True)

    def _take_activity(self, res: EndpointResult, row: dict) -> None:
        day = date_of(row.get("startTimeLocal"))
        activity_type = row.get("activityType")
        type_key = activity_type.get("typeKey") if isinstance(activity_type, dict) else None
        discipline = discipline_of(type_key)
        res.rows += 1
        if day:
            res.days.add(day)
        res.shape.observe(row, day)
        self.by_type[type_key or "unknown"] += 1
        self.discipline_counts[discipline] += 1
        fields = self.discipline_fields.setdefault(discipline, {})
        for name in ACTIVITY_FIELDS:
            counts = fields.setdefault(name, [0, 0])
            value = row.get(name)
            if value not in (None, ""):
                counts[0] += 1
                if not isinstance(value, (int, float)) or value > 0:
                    counts[1] += 1
        if isinstance(row.get("maxHR"), (int, float)) and discipline != "swim":
            self.max_hr_values.append(int(row["maxHR"]))
        self.activities.append({"id": row.get("activityId"), "type": type_key, "discipline": discipline,
                                "day": day, "is_parent": bool(row.get("isParent") or row.get("parent"))})

    def probe_fit_samples(self) -> None:
        dated = sorted((a for a in self.activities if a["day"] and a["id"]), key=lambda a: a["day"], reverse=True)
        picks: list[tuple[str, dict]] = []

        def pick(label: str, candidates: list[dict]) -> None:
            if candidates and all(candidates[0]["id"] != chosen["id"] for _, chosen in picks):
                picks.append((label, candidates[0]))

        for discipline in ("run", "bike", "swim"):
            pick(f"latest {discipline}", [a for a in dated if a["discipline"] == discipline])
        pick("latest open-water swim", [a for a in dated if "open_water" in (a["type"] or "")])
        pick("latest pool swim", [a for a in dated if "lap_swim" in (a["type"] or "")])
        pick("latest multisport", [a for a in dated if a["type"] == "multi_sport"])
        pick("oldest activity", list(reversed(dated)))

        fit_res = self._result("activity_fit_download", "/download-service/files/activity/{activityId}", "sample")
        for label, activity in picks:
            detail = f"/activity-service/activity/{activity['id']}"
            detail_res = self._result("activity_detail", "/activity-service/activity/{activityId}", "sample")
            r = self.client.get(detail)
            detail_res.record(r)
            if r.ok:
                self._save_raw("activity_detail", r)
                detail_res.rows += 1
                detail_res.shape.observe(r.json())
            workouts_res = self._result("activity_workouts", "/activity-service/activity/{activityId}/workouts", "sample")
            r = self.client.get(detail + "/workouts")
            workouts_res.record(r)
            if r.ok:
                body = r.json() or []
                workouts_res.rows += len(body) if isinstance(body, list) else 1
                for item in body if isinstance(body, list) else [body]:
                    workouts_res.shape.observe(item)

            r = self.client.get(
                f"/download-service/files/activity/{activity['id']}",
                accept="application/zip, application/x-zip-compressed, application/octet-stream",
            )
            fit_res.record(r)
            sample: dict[str, Any] = {
                "sample": label, "discipline": activity["discipline"], "type": activity["type"],
                "age_days": (self.today - activity["day"]).days, "http": r.status or r.error,
            }
            if r.ok:
                fit_res.rows += 1
                fit_res.days.add(activity["day"])
                sample.update(read_activity_zip(r.body))
            self.fit_samples.append(sample)

    def walk_range(self, ep: RangeEndpoint) -> None:
        res = self._result(ep.id, ep.path, "range", ep.doc_max_days)
        windows = [ep.first_window] + [w for w in WINDOW_LADDER if w < ep.first_window]
        index = 0
        end = self.today
        consecutive_failures = 0
        empty_days = 0
        while end >= self.floor:
            window = windows[index]
            start = max(self.floor, end - timedelta(days=window - 1))
            span = (end - start).days + 1  # What was really asked: the floor can clip the window.
            if ep.params:
                r = self.client.get(ep.path, {ep.params[0]: start.isoformat(), ep.params[1]: end.isoformat()})
            else:
                r = self.client.get(ep.path.format(start=start.isoformat(), end=end.isoformat()))
            res.record(r)
            if r.ok:
                consecutive_failures = 0
                res.accepted_window = max(res.accepted_window or 0, span)
                days_before = len(res.days)
                self._take_range_rows(ep, res, r)
                empty_days = 0 if len(res.days) > days_before else empty_days + span
                end = start - timedelta(days=1)
                if end < self.activity_floor and empty_days >= EMPTY_STOP_DAYS:
                    res.notes.append(f"Stopped looking after {empty_days} days in a row with no data.")
                    return
                continue
            if res.accepted_window is None and r.status in (400, 413, 422, 500) and index + 1 < len(windows):
                res.rejected_windows[span] = r.status
                while index + 1 < len(windows) and windows[index] >= span:
                    index += 1
                continue
            if res.accepted_window is None:
                res.stop_reason = f"Every window failed; last was HTTP {r.status or r.error}."
                break
            if r.status == 400:
                # A worked window now failing further back reads as a depth limit: say so, don't guess past it.
                res.stop_reason = f"HTTP 400 for a window ending {end}: possible history limit."
                break
            consecutive_failures += 1
            if consecutive_failures >= 3:
                res.stop_reason = f"Three windows in a row failed; last was HTTP {r.status or r.error}."
                break
            res.notes.append(f"A window ending {end} failed with HTTP {r.status or r.error} and was skipped.")
            end = start - timedelta(days=1)
        if end < self.floor and res.days and (min(res.days) - self.floor).days <= 31:
            res.notes.append("Data reaches the --years limit, so history may go back further.")

    def _take_range_rows(self, ep: RangeEndpoint, res: EndpointResult, r: Resp) -> None:
        try:
            body = r.json()
        except ValueError:
            res.notes.append("A response was not JSON.")
            return
        if body in (None, "", [], {}):
            return
        rows = body.get(ep.rows_key) if ep.rows_key and isinstance(body, dict) else body
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            res.notes.append("Response shape differs from the spec: no row list found.")
            res.shape.observe(body)
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            res.rows += 1
            day = date_of(row.get(ep.date_key)) or date_of(_deep(row, ep.date_key))
            res.shape.observe(row, day)
            if day and ep.has_data(row):
                res.days.add(day)
                self._after_range_row(ep.id, row, day)
                self._save_raw(ep.id, r)

    def _after_range_row(self, id: str, row: dict, day: date) -> None:
        if id == "sleep_summaries":
            _update_sleep_checks(self.sleep_checks, row, day)
            end = timestamp_of(row.get("sleepEndTimestampGMT"))
            if end and (self.freshness.get("latest_sleep_end") is None or end > self.freshness["latest_sleep_end"]):
                self.freshness["latest_sleep_end"] = end
        elif id == "daily_summaries_v2":
            value = _deep(row.get("heartRate") or {}, "restingValue")
            if isinstance(value, (int, float)):
                self.rhr_v2[day] = float(value)
        elif id == "hrv_daily":
            value = row.get("lastNightAvg")
            if isinstance(value, (int, float)):
                self.hrv_by_day[day] = float(value)

    def check_hrv_measure(self, rows: Any) -> None:
        """Which HRV measure is lastNightAvg? The spec does not say, but wellness summaries label theirs.

        If a night's RMSSD_HRV average tracks lastNightAvg, that is evidence for RMSSD in ms.
        It is evidence, not proof, and the report words it that way.
        """
        differences: list[float] = []
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = date_of(row.get("calendarDate"))
            items = {i.get("summaryType"): i for i in row.get("summaryTypeDataList") or [] if isinstance(i, dict)}
            if items.get("SDRR_HRV", {}).get("avgValue") is not None:
                self.hrv_measure["days_with_sdrr"] += 1
            rmssd = items.get("RMSSD_HRV", {}).get("avgValue")
            if rmssd is None:
                continue
            self.hrv_measure["days_with_rmssd"] += 1
            if day in self.hrv_by_day:
                differences.append(abs(self.hrv_by_day[day] - float(rmssd)))
        if differences:
            self.hrv_measure["compared_to_last_night_avg"] = len(differences)
            self.hrv_measure["median_abs_difference_ms"] = round(statistics.median(differences), 1)

    def probe_days(self, ep: DayEndpoint) -> None:
        res = self._result(ep.id, ep.path, "by-date")

        def query(day: date) -> bool:
            iso = day.isoformat()
            if ep.param:
                r = self.client.get(ep.path, {ep.param: iso})
            else:
                r = self.client.get(ep.path.format(date=iso))
            res.record(r)
            res.queried_days += 1
            if not r.ok or not r.body:
                return False
            try:
                body = r.json()
            except ValueError:
                return False
            if isinstance(body, list):
                for item in body:
                    res.shape.observe(item, day)
            else:
                res.shape.observe(body, day)
            has_data = ep.has_data(body)
            if has_data:
                res.rows += 1
                res.days.add(day)
                self._save_raw(ep.id, r)
                self._after_day(ep.id, body, day)
            return has_data

        hits: list[date] = []
        misses: list[date] = []
        for offset in DAY_OFFSETS:
            day = self.today - timedelta(days=offset)
            if day < self.floor:
                break
            (hits if query(day) else misses).append(day)
        if hits:
            # Refine the oldest hit. A gap in wear can mislead this, so the result is labelled approximate.
            oldest = min(hits)
            older = [m for m in misses if m < oldest]
            miss = max(older) if older else None
            for _ in range(5):
                if miss is None or (oldest - miss).days <= 7:
                    break
                middle = miss + (oldest - miss) // 2
                if query(middle):
                    oldest = middle
                else:
                    miss = middle
            res.notes.append(f"Sampled {res.queried_days} dates, not every day: earliest date is approximate.")

    def _after_day(self, id: str, body: Any, day: date) -> None:
        if id == "user_summary_daily":
            value = _deep(body, "restingHeartRate")
            if isinstance(value, (int, float)) and day in self.rhr_v2:
                self.rhr_compare["compared"] += 1
                diff = abs(self.rhr_v2[day] - value)
                self.rhr_compare["equal"] += 1 if diff == 0 else 0
                self.rhr_compare["max_abs_difference"] = max(self.rhr_compare["max_abs_difference"], diff)
            sync = timestamp_of(_deep(body, "lastSyncTimestampGMT"))
            if sync and (self.freshness.get("last_sync") is None or sync > self.freshness["last_sync"]):
                self.freshness["last_sync"] = sync
        elif id == "hrv_chart":
            checks = self.hrv_checks
            summary = _deep(body, "hrvSummary") or {}
            calendar = date_of(summary.get("calendarDate")) or day
            checks["nights"] += 1
            if date_of(_deep(body, "sleepEndTimestampLocal")) == calendar:
                checks["calendar_is_wake_date"] += 1
            if date_of(_deep(body, "sleepStartTimestampLocal")) == calendar:
                checks["calendar_is_bed_date"] += 1
            readings = body.get("hrvReadings") if isinstance(body, dict) else None
            if isinstance(readings, list) and readings:
                checks["readings_per_night"].append(len(readings))
                times = [timestamp_of(item.get("readingTimeGMT")) for item in readings if isinstance(item, dict)]
                times = sorted(t for t in times if t)
                gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
                if gaps:
                    checks["reading_interval_min"].append(statistics.median(gaps))

    def probe_samples(self) -> None:
        recent_start = (self.today - timedelta(days=30)).isoformat()
        end = self.today.isoformat()
        self.check_hrv_measure(self._once(
            "wellness_activity_summary", f"/wellnessactivity-service/activity/summary/range/{recent_start}/{end}"))
        self.results["wellness_activity_summary"].path = (
            "/wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}")
        self._once("weight_range", f"/weight-service/weight/range/{recent_start}/{end}", {"includeAll": "true"})
        self.results["weight_range"].path = "/weight-service/weight/range/{startDate}/{endDate}"
        self._once("weight_goal", f"/goal-service/goal/user/effective/weightgoal/{recent_start}/{end}")
        self.results["weight_goal"].path = "/goal-service/goal/user/effective/weightgoal/{startDate}/{endDate}"
        self._once("food_logs", f"/nutrition-service/food/logs/{end}")
        self.results["food_logs"].path = "/nutrition-service/food/logs/{date}"

    def run(self) -> None:
        steps: list[tuple[str, Callable[[], None]]] = [
            ("profile and heart rate zones", self.probe_profile_and_zones),
            ("activity list", self.probe_activities),
            ("activity detail and FIT samples", self.probe_fit_samples),
        ]
        steps += [(ep.id, lambda ep=ep: self.walk_range(ep)) for ep in RANGE_ENDPOINTS]
        steps += [(ep.id, lambda ep=ep: self.probe_days(ep)) for ep in DAY_ENDPOINTS]
        steps.append(("one-off samples", self.probe_samples))
        try:
            self.client.mint_token()
            for name, step in steps:
                print(f"  {name}", flush=True)
                step()
        except ProbeStopped as exc:
            self.stopped = str(exc)
        except KeyboardInterrupt:
            self.stopped = "Interrupted with Ctrl-C."


def _new_sleep_checks() -> dict[str, Any]:
    return {
        "nights": 0, "calendar_is_wake_date": 0, "calendar_is_bed_date": 0, "calendar_is_neither": 0,
        "local_minus_gmt_hours": Counter(), "timestamp_types": Counter(), "under_3_hours": 0, "over_14_hours": 0,
        "with_unmeasurable_seconds": 0, "stage_sum_mismatch": 0, "confirmation_types": Counter(),
    }


def _update_sleep_checks(checks: dict[str, Any], row: dict, day: date) -> None:
    checks["nights"] += 1
    start_local, end_local = row.get("sleepStartTimestampLocal"), row.get("sleepEndTimestampLocal")
    start_gmt, end_gmt = row.get("sleepStartTimestampGMT"), row.get("sleepEndTimestampGMT")
    checks["timestamp_types"][_type_name(end_gmt)] += 1
    wake, bed = date_of(end_local), date_of(start_local)
    if wake == day:
        checks["calendar_is_wake_date"] += 1
    if bed == day:
        checks["calendar_is_bed_date"] += 1
    if wake != day and bed != day:
        checks["calendar_is_neither"] += 1
    local, gmt = timestamp_of(end_local), timestamp_of(end_gmt)
    if local and gmt:
        checks["local_minus_gmt_hours"][round((local - gmt).total_seconds() / 3600, 2)] += 1
    seconds = row.get("sleepTimeSeconds") or 0
    if seconds < 3 * 3600:
        checks["under_3_hours"] += 1
    if seconds > 14 * 3600:
        checks["over_14_hours"] += 1
    if (row.get("unmeasurableSleepSeconds") or 0) > 0:
        checks["with_unmeasurable_seconds"] += 1
    stages = [row.get(k) for k in ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds")]
    if all(isinstance(s, (int, float)) for s in stages) and abs(sum(stages) - seconds) > 300:
        checks["stage_sum_mismatch"] += 1
    checks["confirmation_types"][str(row.get("sleepWindowConfirmationType"))] += 1


# ---------------------------------------------------------------------------
# Verdicts: each item you asked about, judged on what the account returned
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    endpoint: str
    pattern: str
    positive: bool = True  # False when zero is a real value, such as zero intensity minutes.


@dataclass(frozen=True)
class Capability:
    name: str
    tag: str  # "Garmin" derived score, or "Raw" measurement/summary.
    sources: tuple[Source, ...] = ()
    absent_needle: str | None = None  # Item has no documented path: look for it in live field names.
    note: str = ""


CAPABILITIES = (
    Capability("Activities: list", "Raw", (Source("activities", r"^activityId$"),)),
    Capability("Activities: duration and distance", "Raw", (Source("activities", r"^distance$"),)),
    Capability("Activities: FIT download", "Raw", (Source("activity_fit_download", r"^$"),),
               note="Days here means sample files downloaded, not all activities. Section 4 shows what they contain."),
    Capability("Daily summaries", "Raw", (Source("daily_summaries_v2", r"^$"), Source("user_summary_daily", r"^$")),
               note="Counts days with a resting HR or steps. Garmin may return an empty row for an unworn day."),
    Capability("Sleep: duration", "Raw", (Source("sleep_summaries", r"(^|\.)sleepTimeSeconds$"), Source("daily_sleep", r"(^|\.)sleepTimeSeconds$"))),
    Capability("Sleep: stages", "Raw", (Source("sleep_summaries", r"(^|\.)(deep|light|rem)SleepSeconds$"), Source("daily_sleep", r"(^|\.)(deep|light|rem)SleepSeconds$")),
               note="Wrist-based stages are approximate."),
    Capability("Sleep: score", "Garmin", (Source("sleep_summaries", r"sleepScores.*\.value$"), Source("daily_sleep", r"sleepScores.*\.value$")),
               note="The spec defines sleepScores as a map of 0-100 items but does not name the keys; section 7 lists yours."),
    Capability("Sleep: Garmin's sleep need", "Garmin", (Source("sleep_summaries", r"sleepNeed\.(actual|baseline)$"), Source("daily_sleep", r"sleepNeed\.(actual|baseline)$"))),
    Capability("HRV: nightly average", "Garmin", (Source("hrv_daily", r"(^|\.)lastNightAvg$"), Source("hrv_chart", r"(^|\.)lastNightAvg$")),
               note="The spec only calls this the 'average overnight HRV value'; section 5 tests whether it is RMSSD."),
    Capability("HRV: status", "Garmin", (Source("hrv_daily", r"(^|\.)status$"), Source("hrv_chart", r"hrvSummary\.status$"))),
    Capability("HRV: overnight readings", "Raw", (Source("hrv_chart", r"hrvReadings\[\]\.hrvValue$"),)),
    Capability("Resting HR", "Garmin", (Source("user_summary_daily", r"(^|\.)restingHeartRate$"), Source("daily_heart_rate", r"(^|\.)restingHeartRate$"), Source("daily_summaries_v2", r"heartRate\.restingValue$")),
               note="Swagger: the v2 field falls back to the day's absolute minimum when no resting value exists."),
    Capability("Stress", "Garmin", (Source("stress_daily", r"overallStressLevel$"), Source("daily_summaries_v2", r"^stress\."))),
    Capability("Body Battery", "Garmin", (Source("body_battery_daily", r"^(charged|drained)$"), Source("daily_summaries_v2", r"^bodyBattery\.(max|min)Value$"))),
    Capability("Respiration: during sleep", "Raw", (Source("sleep_summaries", r"(^|\.)averageRespirationValue$"), Source("daily_sleep", r"(^|\.)averageRespirationValue$"))),
    Capability("Respiration: daily", "Raw", (Source("daily_summaries_v2", r"^respiration\.avgValue$"), Source("user_summary_daily", r"(^|\.)avgWakingRespirationValue$"))),
    Capability("SpO2", "Raw", (Source("daily_summaries_v2", r"^pulseOx\.avgValue$"), Source("spo2", r"(^|\.)averageSpO2$"), Source("sleep_summaries", r"(^|\.)averageSpO2Value$")),
               note="Needs Pulse Ox switched on in the watch settings, so empty may just mean off."),
    Capability("Steps", "Raw", (Source("steps_daily", r"(^|\.)totalSteps$"), Source("daily_summaries_v2", r"^movement\.steps\.value$"))),
    Capability("Intensity minutes", "Garmin", (Source("daily_summaries_v2", r"^intensityMinutes\.(moderate|vigorous)$", False), Source("user_summary_daily", r"(moderate|vigorous)IntensityMinutes$", False))),
    Capability("VO2 max", "Garmin", (Source("activities", r"^vO2MaxValue$"),),
               note="Documented only as a per-activity field: no VO2 max endpoint exists."),
    Capability("Training Status", "Garmin", absent_needle=r"trainingStatus", note="No path or field in the spec."),
    Capability("Training Readiness", "Garmin", absent_needle=r"readiness", note="No path or field in the spec."),
    Capability("Training Load: per activity", "Garmin", (Source("activities", r"^activityTrainingLoad$"),),
               note="Per-activity value only."),
    Capability("Training Load: acute, chronic, balance", "Garmin", absent_needle=r"acuteLoad|chronicLoad|loadBalance|acwr",
               note="No path or field in the spec."),
    Capability("Recovery Time", "Garmin", absent_needle=r"recoveryTime",
               note="No path or field in the spec. recoveryHeartRate is a different measure."),
    Capability("Heart rate zones", "Garmin", (Source("heart_rate_zones", r"zone1Floor$"),)),
    Capability("Max and resting HR behind the zones", "Garmin", (Source("heart_rate_zones", r"maxHeartRateUsed$"),)),
    Capability("Hydration (later)", "Raw", (Source("hydration_daily", r"(^|\.)valueInML$"),)),
    Capability("Weight (later)", "Raw", (Source("weight_all", r"(^|\.)weight$"), Source("weight_range", r"(^|\.)weight$"))),
)


def evaluate(cap: Capability, probe: Probe) -> dict[str, Any]:
    row: dict[str, Any] = {"item": cap.name, "tag": cap.tag, "note": cap.note, "source": "", "earliest": None,
                           "latest": None, "days_with_data": 0, "last_30_days": None, "last_90_days": None}
    if cap.absent_needle:
        seen = [
            f"{res.id}: {path}" for res in probe.results.values() for path in res.shape.search_names(cap.absent_needle)
        ]
        row["verdict"] = "CHECK: FIELD SEEN" if seen else "NOT IN API"
        row["source"] = "; ".join(seen[:5]) if seen else "none"
        return row

    reached = [probe.results[s.endpoint] for s in cap.sources if s.endpoint in probe.results and probe.results[s.endpoint].requests]
    if not reached:
        row["verdict"] = "NOT RUN"
        return row

    best: tuple[int, int, Source, set[date]] | None = None
    for source in cap.sources:
        res = probe.results.get(source.endpoint)
        if res is None:
            continue
        if source.pattern == "^$":  # No single field to judge: use the endpoint's own has-data test.
            dates = set(res.days)
            count = len(dates)
        else:
            stats = res.shape.match(source.pattern)
            dates = set().union(*[s.positive_dates if source.positive else s.dates for s in stats]) if stats else set()
            count = sum(s.measured if source.positive else s.nonnull for s in stats)
        if count and (best is None or (len(dates), count) > (best[0], best[1])):
            best = (len(dates), count, source, dates)

    if best is None:
        row["verdict"] = "EMPTY" if any(res.any_ok for res in reached) else "ERROR"
        row["source"] = ", ".join(sorted({s.endpoint for s in cap.sources}))
        codes = {str(code) for res in reached for code in res.statuses}
        row["http"] = sorted(codes)
        return row

    _, _, source, dates = best
    row["verdict"] = "DATA"
    row["source"] = source.endpoint
    row["kind"] = probe.results[source.endpoint].kind
    if dates:
        row["earliest"] = min(dates).isoformat()
        row["latest"] = max(dates).isoformat()
        row["days_with_data"] = len(dates)
        if probe.results[source.endpoint].kind in ("range", "paged"):
            row["last_30_days"] = sum(1 for d in dates if (probe.today - d).days < 30)
            row["last_90_days"] = sum(1 for d in dates if (probe.today - d).days < 90)
    else:
        row["days_with_data"] = None
    if probe.results[source.endpoint].kind == "by-date":
        row["note"] = (row["note"] + " Earliest is approximate (sampled dates).").strip()
    distribution = _value_distribution(probe.results[source.endpoint], source.pattern)
    if distribution:
        row["values"] = distribution
    return row


def _value_distribution(res: EndpointResult, pattern: str) -> dict[str, int] | None:
    if pattern == "^$":
        return None
    merged: Counter = Counter()
    for stat in res.shape.match(pattern):
        merged.update(stat.values)
    return dict(merged.most_common(10)) or None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _stat_summary(numbers: list[float]) -> str:
    if not numbers:
        return ""
    return f"min {min(numbers):g} / median {statistics.median(numbers):g} / max {max(numbers):g}"


def build_summary(probe: Probe) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    verdicts = [evaluate(cap, probe) for cap in CAPABILITIES]
    endpoints = []
    for res in probe.results.values():
        endpoints.append({
            "id": res.id, "path": res.path, "kind": res.kind, "requests": res.requests,
            "http": {str(code): n for code, n in res.statuses.items()}, "rows": res.rows,
            "earliest": min(res.days).isoformat() if res.days else None,
            "latest": max(res.days).isoformat() if res.days else None,
            "days_with_data": len(res.days), "doc_max_days": res.doc_max_days,
            "accepted_window": res.accepted_window,
            "rejected_windows": {str(k): v for k, v in res.rejected_windows.items()},
            "stop_reason": res.stop_reason, "notes": res.notes,
            "fields": {
                path: {
                    "present": s.present, "non_null": s.nonnull, "types": dict(s.types),
                    **({"stats": _stat_summary(s.numbers)} if s.numbers else {}),
                    **({"values": dict(s.values.most_common(12))} if s.values else {}),
                    **({"formats": dict(s.patterns.most_common(4))} if s.patterns else {}),
                }
                for path, s in sorted(res.shape.paths.items())
            },
        })

    freshness = {}
    for name, value in probe.freshness.items():
        if isinstance(value, datetime):
            freshness[f"{name}_hours_ago"] = round((now.replace(tzinfo=None) - value).total_seconds() / 3600, 1)

    checks = dict(probe.sleep_checks)
    checks["local_minus_gmt_hours"] = {str(k): v for k, v in checks["local_minus_gmt_hours"].items()}
    checks["timestamp_types"] = dict(checks["timestamp_types"])
    checks["confirmation_types"] = dict(checks["confirmation_types"])
    hrv = dict(probe.hrv_checks)
    hrv["readings_per_night"] = _stat_summary(hrv["readings_per_night"])
    hrv["reading_interval_min"] = _stat_summary(hrv["reading_interval_min"])

    return {
        "generated_utc": now.strftime("%Y-%m-%d %H:%M UTC"),
        "duration_min": round((now - probe.started).total_seconds() / 60, 1),
        "base_url": probe.client.base_url,
        "requests": probe.client.requests,
        "budget": probe.client.max_requests,
        "stopped_early": probe.stopped,
        "walk_floor": probe.floor.isoformat(),
        "token": probe.client.token_info,
        "rate_limit": {
            "events": probe.client.rate_limit_events,
            "headers_seen": sorted(probe.client.rate_limit_headers),
        },
        "verdicts": verdicts,
        "endpoints": endpoints,
        "not_probed": NOT_PROBED,
        "activity_types": dict(probe.by_type.most_common()),
        "discipline_counts": dict(probe.discipline_counts),
        "discipline_field_coverage": {
            discipline: {
                name: {"non_null": c[0], "positive": c[1]} for name, c in fields.items() if c[0]
            }
            for discipline, fields in probe.discipline_fields.items()
        },
        "highest_max_hr_seen": sorted(probe.max_hr_values, reverse=True)[:5],
        "fit_samples": probe.fit_samples,
        "sleep_checks": checks,
        "hrv_checks": hrv,
        "resting_hr_v2_vs_daily": probe.rhr_compare,
        "hrv_measure_check": probe.hrv_measure,
        "freshness": freshness,
    }


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|")


def render_markdown(s: dict[str, Any]) -> str:
    out: list[str] = []
    add = out.append
    add("# Garmin Personal API: data-availability report\n")
    add(f"- Generated: {s['generated_utc']}, took {s['duration_min']} min, {s['requests']} requests "
        f"(budget {s['budget']})")
    add(f"- Host: {s['base_url']}")
    add(f"- Furthest back the probe was allowed to look: {s['walk_floor']}")
    if s["stopped_early"]:
        add(f"- **STOPPED EARLY: {s['stopped_early']} Everything below is partial.**")
    add("- Holds aggregates of your health data but no names, IDs, GPS or tokens. Keep it out of the repo.\n")

    add("## 1. What you asked about\n")
    add("| Item | Type | Verdict | Source | Earliest | Latest | Days | Last 30 d | Last 90 d | Notes |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for v in s["verdicts"]:
        notes = v["note"]
        if v.get("values"):
            notes = (notes + " Values: " + ", ".join(f"{k} x{n}" for k, n in v["values"].items())).strip()
        add("| " + " | ".join(_cell(x) for x in (
            v["item"], v["tag"], v["verdict"], v["source"], v["earliest"], v["latest"],
            v["days_with_data"], v["last_30_days"], v["last_90_days"], notes)) + " |")
    add("\nDATA = real values came back. EMPTY = endpoint answered but this field never had a value. "
        "NOT IN API = absent from Garmin's spec and from every live response. "
        "NOT RUN = the probe stopped before it got there.\n")

    add("## 2. Per endpoint\n")
    add("| Endpoint | HTTP | Rows | Earliest | Latest | Days with data | Swagger max days | Window accepted | Windows rejected | Notes |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for e in s["endpoints"]:
        notes = "; ".join(filter(None, [e["stop_reason"], *e["notes"]]))
        http_codes = ", ".join(f"{k} x{v}" for k, v in e["http"].items())
        rejected = ", ".join(f"{k}d: {v}" for k, v in e["rejected_windows"].items())
        add("| " + " | ".join(_cell(x) for x in (
            f"`{e['path']}`", http_codes, e["rows"], e["earliest"], e["latest"], e["days_with_data"],
            e["doc_max_days"], e["accepted_window"], rejected, notes)) + " |")
    add("\nNot probed on purpose:")
    for path, why in s["not_probed"].items():
        add(f"- `{path}`: {why}")
    add("- Undocumented paths: none called. The Swagger page is the contract.\n")

    add("## 3. Activities\n")
    add("By type: " + (", ".join(f"{k} x{v}" for k, v in s["activity_types"].items()) or "none") + "\n")
    add(f"By discipline: {s['discipline_counts']}\n")
    add(f"Highest activity max HR seen (not swims): {s['highest_max_hr_seen']}\n")
    disciplines = list(s["discipline_field_coverage"])
    if disciplines:
        add("Share of activities with a value, by discipline:\n")
        add("| Field | " + " | ".join(disciplines) + " |")
        add("|---|" + "---|" * len(disciplines))
        names = [n for n in ACTIVITY_FIELDS if any(n in s["discipline_field_coverage"][d] for d in disciplines)]
        for name in names:
            cells = []
            for d in disciplines:
                count = s["discipline_counts"].get(d) or 1
                covered = s["discipline_field_coverage"][d].get(name, {}).get("non_null", 0)
                cells.append(f"{100 * covered / count:.0f}%")
            add(f"| {name} | " + " | ".join(cells) + " |")
        add("")

    add("## 4. FIT samples\n")
    if not s["fit_samples"]:
        add("No samples taken.\n")
    for f in s["fit_samples"]:
        add(f"### {f['sample']} ({f.get('type')}, {f['age_days']} days old): HTTP {f['http']}\n")
        if f.get("parse_error"):
            add(f"- Could not read: {f['parse_error']}")
        if "bytes" in f:
            add(f"- Size {f['bytes']} bytes, zip: {f.get('zip')}, truncated: {f.get('truncated', False)}")
        if f.get("messages"):
            add(f"- Messages: {f['messages']}")
            add(f"- Records: {f['record_count']}, median interval {f['record_median_interval_s']} s")
            add(f"- Record field coverage %: {f['record_field_pct']}")
            add(f"- Session fields: {f['session_fields']}")
            add(f"- Undocumented message numbers: {f['undocumented_messages']}")
            add(f"- Fields in undocumented message 140: {f['message_140_field_numbers'] or 'message absent'}")
        add("")

    add("## 5. Day boundaries, units and data quality\n")
    c = s["sleep_checks"]
    add(f"Sleep nights with data: {c['nights']}")
    if c["nights"]:
        add(f"- calendarDate is the wake date: {c['calendar_is_wake_date']}, the bed date: "
            f"{c['calendar_is_bed_date']}, neither: {c['calendar_is_neither']}")
        add(f"- Local minus GMT, hours: {c['local_minus_gmt_hours']}")
        add(f"- Timestamp JSON type: {c['timestamp_types']}")
        add(f"- Under 3 h: {c['under_3_hours']}. Over 14 h: {c['over_14_hours']}. "
            f"With unmeasurable seconds: {c['with_unmeasurable_seconds']}. "
            f"Stages disagree with total by over 5 min: {c['stage_sum_mismatch']}")
        add(f"- Sleep window confirmation: {c['confirmation_types']}")
    h = s["hrv_checks"]
    add(f"\nHRV nights sampled in detail: {h['nights']}")
    if h["nights"]:
        add(f"- calendarDate is the wake date: {h['calendar_is_wake_date']}, the bed date: {h['calendar_is_bed_date']}")
        add(f"- Readings per night: {h['readings_per_night'] or 'none'}")
        add(f"- Median minutes between readings: {h['reading_interval_min'] or 'n/a'}")
    m = s["hrv_measure_check"]
    add(f"\nWhich HRV measure is lastNightAvg? Last 30 days of wellness summaries: RMSSD_HRV on {m['days_with_rmssd']} "
        f"days, SDRR_HRV on {m['days_with_sdrr']} days. Compared with lastNightAvg on "
        f"{m['compared_to_last_night_avg']} days, median difference {m['median_abs_difference_ms']} ms. "
        "A small difference is evidence for RMSSD, not proof.")
    r = s["resting_hr_v2_vs_daily"]
    add(f"\nResting HR, v2 summary vs daily summary: {r['equal']} of {r['compared']} sampled days equal, "
        f"largest difference {r['max_abs_difference']:g} bpm")
    add(f"\nFreshness: {s['freshness'] or 'unknown'}\n")

    add("## 6. Token and limits\n")
    add(f"- Token: {s['token']}")
    add(f"- Rate-limit responses: {len(s['rate_limit']['events'])}. Details: {s['rate_limit']['events'][:5]}")
    add(f"- Rate-limit headers seen: {s['rate_limit']['headers_seen'] or 'none'}\n")

    add("## 7. Fields seen, by endpoint\n")
    add("Non-null fields only; `[]` marks a list. Full detail, including null fields, is in probe-report.json.\n")
    for e in s["endpoints"]:
        fields = {p: f for p, f in e["fields"].items() if f["non_null"]}
        add(f"### {e['id']}: {len(fields)} of {len(e['fields'])} fields have values\n")
        if not fields:
            continue
        add("| Field | Non-null / present | Types | Stats, values, formats |")
        add("|---|---|---|---|")
        for path, f in fields.items():
            detail = f.get("stats") or ""
            if f.get("values"):
                detail = ", ".join(f"{k} x{n}" for k, n in f["values"].items())
            if f.get("formats"):
                detail = (detail + " " + ", ".join(f["formats"])).strip()
            types = ",".join(t for t in f["types"] if t != "null")
            add(f"| {_cell(path)} | {f['non_null']} / {f['present']} | {_cell(types)} | {_cell(detail)} |")
        add("")
    return "\n".join(out) + "\n"


def render_console(s: dict[str, Any]) -> str:
    lines = ["", "Item                                     Verdict            Earliest    Latest      Days"]
    for v in s["verdicts"]:
        days = "" if v["days_with_data"] is None else v["days_with_data"]
        lines.append(f"{v['item']:<40} {v['verdict']:<18} {v['earliest'] or '-':<11} {v['latest'] or '-':<11} {days}")
    if s["stopped_early"]:
        lines.append(f"\nSTOPPED EARLY: {s['stopped_early']}")
    return "\n".join(lines)


def write_reports(probe: Probe, out_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    summary = build_summary(probe)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path, json_path = out_dir / "probe-report.md", out_dir / "probe-report.json"
    md_path.write_text(probe.client.redact(render_markdown(summary)), encoding="utf-8")
    json_path.write_text(probe.client.redact(json.dumps(summary, indent=1, default=str)), encoding="utf-8")
    return md_path, json_path, summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report what your Garmin Personal API key can really see.")
    parser.add_argument("--save-key", action="store_true", help="prompt for the key (hidden) and store it, then exit")
    parser.add_argument("--api-key-file", help=f"read the key from this file instead of {KEY_ENV_VAR} or {DEFAULT_KEY_FILE}")
    parser.add_argument("--years", type=float, default=6.0, help="how far back to look at most (default 6)")
    parser.add_argument("--max-requests", type=int, default=1000, help="stop after this many requests (default 1000)")
    parser.add_argument("--delay", type=float, default=1.2, help="seconds between requests (default 1.2)")
    parser.add_argument("--out", default="probe-output", help="report folder (default probe-output)")
    parser.add_argument("--save-raw", action="store_true",
                        help="also keep one raw JSON sample per endpoint in <out>/raw (personal data: never commit)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.save_key:
        try:
            key = getpass.getpass("Paste your Garmin Personal API key (input stays hidden), then press Enter: ")
            path = save_api_key(key)
        except AuthFailed as exc:
            print(exc, file=sys.stderr)
            return EXIT_AUTH
        print(f"Saved to {path}")
        return EXIT_OK

    out_dir = Path(args.out)
    try:
        api_key = resolve_api_key(args.api_key_file)
        client = Client(os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL), api_key,
                        delay=args.delay, max_requests=args.max_requests)
        probe = Probe(client, years=args.years, raw_dir=out_dir / "raw" if args.save_raw else None)
        print(f"Probing {client.base_url}. Requests are spaced {args.delay}s apart, so expect several minutes.")
        probe.run()
    except AuthFailed as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return EXIT_AUTH

    md_path, json_path, summary = write_reports(probe, out_dir)
    print(client.redact(render_console(summary)))
    print(f"\nReport: {md_path}\nDetail: {json_path}")
    return EXIT_PARTIAL if probe.stopped else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
