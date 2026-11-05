"""A local stand-in for the Garmin Personal API, shaped after its Swagger document.

All data is synthetic. Values starting SECRET_, plus PLANTED_LATITUDE and
PLANTED_PROFILE_ID, are planted so tests can prove they never reach a report.
"""
from __future__ import annotations

import base64
import io
import json
import re
import struct
import threading
import time
import urllib.parse
import zipfile
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

GOOD_KEY = "SECRET_API_KEY_abc123"
PLANTED_LATITUDE = 15.498912345
PLANTED_PROFILE_ID = 987654321


def fake_jwt(lifetime: int = 86400) -> str:
    def encode(obj: Any) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    now = int(time.time())
    payload = {"scope": ["CONNECT_READ", "PERSONAL_API_WELLNESS_READ"], "iat": now, "exp": now + lifetime,
               "sub": "SECRET_SUBJECT", "jti": "SECRET_JTI"}
    return f"{encode({'alg': 'none'})}.{encode(payload)}.c2lnbmF0dXJlLWZvci10ZXN0"


def fit_definition(local: int, global_num: int, fields: list[tuple[int, int, int]], big: bool = False) -> bytes:
    order = ">" if big else "<"
    out = bytes([0x40 | local, 0, 1 if big else 0]) + struct.pack(order + "H", global_num) + bytes([len(fields)])
    for field in fields:
        out += bytes(field)
    return out


def build_fit() -> bytes:
    """A small but valid FIT file: 4 records (one with HR dropped out), a session, a length, and message 140."""
    body = b""
    body += fit_definition(0, 0, [(0, 1, 0x00), (3, 4, 0x8C)])  # file_id: type, serial_number
    body += bytes([0x00, 4]) + struct.pack("<I", 1234567)
    # record: timestamp, heart_rate, enhanced_speed, position_lat
    body += fit_definition(1, 20, [(253, 4, 0x86), (3, 1, 0x02), (73, 4, 0x86), (0, 4, 0x85)])
    base_ts = 1_000_000_000
    for i, hr in enumerate((140, 142, 0xFF, 144)):
        body += bytes([0x01]) + struct.pack("<IBIi", base_ts + i * 2, hr, 3000, 123456789)
    # session: sport, total_timer_time, avg_heart_rate, unknown field 200
    body += fit_definition(2, 18, [(5, 1, 0x00), (8, 4, 0x86), (16, 1, 0x02), (200, 2, 0x84)])
    body += bytes([0x02, 1]) + struct.pack("<IBH", 3600000, 150, 7)
    body += fit_definition(3, 101, [(254, 2, 0x84)])
    body += bytes([0x03]) + struct.pack("<H", 0)
    # Undocumented message 140: one valid field, one invalid.
    body += fit_definition(4, 140, [(7, 2, 0x84), (9, 2, 0x84)])
    body += bytes([0x04]) + struct.pack("<HH", 5000, 0xFFFF)
    header = bytes([14, 0x20]) + struct.pack("<H", 2132) + struct.pack("<I", len(body)) + b".FIT" + b"\x00\x00"
    return header + body + b"\x00\x00"


def build_activity_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("12345_ACTIVITY.fit", build_fit())
    return buffer.getvalue()


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class MockGarmin:
    def __init__(
        self,
        today: date,
        history_days: int = 300,
        hrv_days: int = 120,
        window_limits: dict[str, int] | None = None,
        rate_limit_hits: dict[str, int] | None = None,
        retry_after: str = "1",
        expire_token_after: int | None = None,
        redirect_fit: bool = False,
        extra_summary_fields: dict[str, Any] | None = None,
        always_429: bool = False,
        hrv_renamed: bool = False,
        file_status: int | None = None,
    ) -> None:
        self.today = today
        self.history_days = history_days
        self.hrv_days = hrv_days
        # Swagger limits, overridable to simulate the smaller third-party reports.
        self.window_limits = {"steps": 28, "stress": 28, "hydration": 31, "dailySleepSummaries": 31,
                              "bodyBattery": 31, "dailysummaries": 365, **(window_limits or {})}
        self.rate_limit_hits = dict(rate_limit_hits or {})
        self.retry_after = retry_after
        self.expire_token_after = expire_token_after
        self.redirect_fit = redirect_fit
        self.extra_summary_fields = extra_summary_fields or {}
        self.always_429 = always_429
        self.hrv_renamed = hrv_renamed
        self.file_status = file_status
        self.tokens_issued = 0
        self.data_requests = 0
        self.log: list[str] = []
        self.cdn_saw_authorization: bool | None = None
        self.valid_tokens: set[str] = set()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "MockGarmin":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()

    # -- synthetic data --------------------------------------------------

    def _in_history(self, day: date) -> bool:
        return 0 <= (self.today - day).days <= self.history_days

    def _worn(self, day: date) -> bool:
        return (self.today - day).days % 50 != 7

    def sleep_row(self, day: date) -> dict[str, Any]:
        if not self._in_history(day) or not self._worn(day):
            return {"calendarDate": day.isoformat(), "sleepTimeSeconds": None}
        partial = (self.today - day).days % 40 == 3
        seconds = 2 * 3600 if partial else 7 * 3600
        wake = datetime(day.year, day.month, day.day, 6, 30)
        bed = wake - timedelta(seconds=seconds + 900)
        offset = timedelta(hours=5, minutes=30)
        return {
            "id": 111, "userProfilePK": PLANTED_PROFILE_ID, "calendarDate": day.isoformat(),
            "sleepTimeSeconds": seconds, "napTimeSeconds": 0,
            "deepSleepSeconds": seconds // 7, "lightSleepSeconds": seconds * 4 // 7,
            "remSleepSeconds": seconds - seconds // 7 - seconds * 4 // 7, "awakeSleepSeconds": 900,
            "unmeasurableSleepSeconds": 0, "deviceRemCapable": True, "sleepFromDevice": True,
            "sleepWindowConfirmationType": "auto_confirmed_final",
            "sleepStartTimestampLocal": ms(bed), "sleepEndTimestampLocal": ms(wake),
            "sleepStartTimestampGMT": ms(bed - offset), "sleepEndTimestampGMT": ms(wake - offset),
            "averageRespirationValue": 14.5, "lowestRespirationValue": 11.0, "highestRespirationValue": 19.0,
            "averageSpO2Value": None, "userNote": "SECRET_NOTE",
            "sleepScores": {"overall": {"value": 78, "qualifierKey": "FAIR"}},
            "sleepNeed": {"baseline": 480, "actual": 500, "calendarDate": day.isoformat()},
        }

    def v2_row(self, day: date) -> dict[str, Any]:
        worn = self._in_history(day) and self._worn(day)
        return {
            "uuid": "SECRET_UUID", "userProfilePk": PLANTED_PROFILE_ID, "calendarDate": day.isoformat(),
            "includesWellnessData": worn, "source": "garmin",
            "movement": {"steps": {"goal": 8000, "value": 9000 if worn else 0}},
            "heartRate": {"minValue": 45, "maxValue": 120, "restingValue": 52 if worn else None},
            "intensityMinutes": {"goal": 150, "moderate": 0 if worn else None, "vigorous": 20 if worn else None},
            "stress": {"lowStressProportion": 0.5 if worn else None},
            "bodyBattery": {"minValue": 20 if worn else None, "maxValue": 80 if worn else None},
            "respiration": {"avgValue": 15 if worn else None},
            "pulseOx": {"avgValue": None},
            **self.extra_summary_fields,
        }

    def activities(self) -> list[dict[str, Any]]:
        kinds = ["running", "road_biking", "lap_swimming", "open_water_swimming", "multi_sport", "strength_training"]
        rows = []
        for i in range(0, min(self.history_days, 240), 2):
            day = self.today - timedelta(days=i)
            kind = kinds[i // 2 % len(kinds)]
            swim = "swim" in kind
            rows.append({
                "activityId": 10_000 + i, "activityName": "SECRET_ACTIVITY_NAME", "description": "SECRET_DESCRIPTION",
                "ownerFullName": "SECRET_OWNER", "ownerDisplayName": "SECRET_DISPLAY",
                "startTimeLocal": f"{day.isoformat()} 06:00:00", "startTimeGMT": f"{day.isoformat()} 00:30:00",
                "activityType": {"typeKey": kind}, "startLatitude": PLANTED_LATITUDE, "startLongitude": 73.8,
                "duration": 3600.0, "distance": 1500.0 if swim else 10000.0, "averageHR": None if swim else 140.0,
                "maxHR": None if swim else 178.0, "activityTrainingLoad": None if swim else 90.0,
                "aerobicTrainingEffect": 3.1, "vO2MaxValue": 48.0 if kind == "running" else None,
                "averageSwolf": 40.0 if swim else None, "isParent": kind == "multi_sport",
            })
        return rows

    # -- HTTP ------------------------------------------------------------

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None,
                      content_type: str = "application/json") -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj: Any, status: int = 200) -> None:
                self._send(status, json.dumps(obj).encode())

            def do_POST(self) -> None:
                if self.path == "/personalapitoken-service/personal-api/personal-api-key/token":
                    if self.headers.get("Authorization") != f"ApiKey {GOOD_KEY}":
                        return self._send(401)
                    token = fake_jwt() + f"-{mock.tokens_issued}".replace("-", "")
                    mock.tokens_issued += 1
                    mock.valid_tokens = {token}
                    return self._send(200, token.encode(), content_type="text/plain")
                return self._send(404)

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                path, query = parsed.path, dict(urllib.parse.parse_qsl(parsed.query))
                mock.log.append(self.path)
                if path.startswith("/cdn/"):
                    mock.cdn_saw_authorization = self.headers.get("Authorization") is not None
                    return self._send(200, build_activity_zip(), content_type="application/x-zip-compressed")
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer ") or auth[7:] not in mock.valid_tokens:
                    return self._send(401)
                mock.data_requests += 1
                if mock.expire_token_after is not None and mock.data_requests == mock.expire_token_after:
                    mock.valid_tokens = set()
                    return self._send(401)
                if mock.always_429:
                    return self._send(429, headers={"Retry-After": mock.retry_after})
                for needle, remaining in list(mock.rate_limit_hits.items()):
                    if needle in path and remaining > 0:
                        mock.rate_limit_hits[needle] = remaining - 1
                        return self._send(429, headers={"Retry-After": mock.retry_after, "X-RateLimit-Remaining": "0"})
                return self._route(path, query)

            def _range_ok(self, start: str, end: str, limit_key: str | None) -> bool:
                limit = mock.window_limits.get(limit_key) if limit_key else None
                span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
                return limit is None or span <= limit

            def _dates(self, start: str, end: str) -> list[date]:
                first, last = date.fromisoformat(start), date.fromisoformat(end)
                return [first + timedelta(days=i) for i in range((last - first).days + 1)]

            def _route(self, path: str, q: dict[str, str]) -> None:
                if path == "/userprofile-service/userprofile/settings":
                    return self._json({"displayName": "SECRET_DISPLAY", "timeZone": "Asia/Kolkata",
                                       "measurementSystem": "metric"})
                if path == "/biometric-service/heartRateZones/v2":
                    return self._json([{"trainingMethod": "HR_MAX", "sport": "DEFAULT", "maxHeartRateUsed": 190,
                                        "restingHeartRateUsed": 50, "zone1Floor": 95, "zone2Floor": 114,
                                        "zone3Floor": 133, "zone4Floor": 152, "zone5Floor": 171}])
                if path == "/activitylist-service/activities/search/activities":
                    start, limit = int(q.get("start", 0)), min(int(q.get("limit", 99)), 50)  # server caps below the ask
                    return self._json(mock.activities()[start : start + limit])
                if match := re.fullmatch(r"/activity-service/activity/(\d+)", path):
                    return self._json({"activityId": int(match.group(1)), "activityName": "SECRET_ACTIVITY_NAME",
                                       "summaryDTO": {"averageHR": 140.0, "recoveryHeartRate": 30}})
                if re.fullmatch(r"/activity-service/activity/\d+/workouts", path):
                    return self._json([])
                if match := re.fullmatch(r"/download-service/files/activity/(\d+)", path):
                    if mock.file_status is not None:
                        return self._send(mock.file_status)
                    if mock.redirect_fit:
                        # A different hostname for the same server, like a presigned download host.
                        return self._send(302, headers={"Location": f"http://localhost:{mock.port}/cdn/{match.group(1)}.zip"})
                    return self._send(200, build_activity_zip(), content_type="application/x-zip-compressed")
                if path == "/usersummary-service/v2/dailysummaries":
                    if not self._range_ok(q["startDate"], q["endDate"], "dailysummaries"):
                        return self._send(400)
                    return self._json({"data": [mock.v2_row(d) for d in self._dates(q["startDate"], q["endDate"])]})
                if match := re.fullmatch(r"/hrv-service/hrv/daily/([\d-]+)/([\d-]+)", path):
                    if mock.hrv_renamed:
                        return self._json({"nightlyVariability": [{"night": match.group(1)}]})
                    rows = []
                    for d in self._dates(match.group(1), match.group(2)):
                        if (mock.today - d).days <= mock.hrv_days and mock._worn(d):
                            rows.append({"calendarDate": d.isoformat(), "lastNightAvg": 55, "lastNight5MinHigh": 80,
                                         "weeklyAvg": 54, "status": "BALANCED",
                                         "baseline": {"lowUpper": 40, "balancedLow": 45, "balancedUpper": 65, "markerValue": 0.5}})
                    return self._json({"hrvSummaries": rows, "userProfilePk": PLANTED_PROFILE_ID}) if rows else self._send(204)
                if path == "/sleep-service/sleep/dailySleepSummariesByDate":
                    if not self._range_ok(q["startDate"], q["endDate"], "dailySleepSummaries"):
                        return self._send(400)
                    return self._json([mock.sleep_row(d) for d in self._dates(q["startDate"], q["endDate"])])
                if path == "/wellness-service/wellness/bodyBattery/reports/daily":
                    if not self._range_ok(q["startDate"], q["endDate"], "bodyBattery"):
                        return self._send(400)
                    # Like the real API: every date gets a row and an array, even before the account existed.
                    return self._json([{"date": d.isoformat(), "bodyBatteryValuesArray": [[1, None]],
                                        "charged": 60 if mock._in_history(d) else None,
                                        "drained": 55 if mock._in_history(d) else None}
                                       for d in self._dates(q["startDate"], q["endDate"])])
                if match := re.fullmatch(r"/usersummary-service/stats/(stress|steps|hydration)/daily/([\d-]+)/([\d-]+)", path):
                    kind, start, end = match.groups()
                    if not self._range_ok(start, end, kind):
                        return self._send(400)
                    rows = []
                    for d in self._dates(start, end):
                        if not mock._in_history(d):
                            continue
                        if kind == "stress":
                            rows.append({"calendarDate": d.isoformat(), "values": {"overallStressLevel": 30 if mock._worn(d) else -1}})
                        elif kind == "steps":
                            rows.append({"calendarDate": d.isoformat(), "totalSteps": 9000 if mock._worn(d) else 0, "stepGoal": 8000})
                        else:
                            rows.append({"calendarDate": d.isoformat(), "valueInML": 0.0, "userId": PLANTED_PROFILE_ID})
                    return self._json(rows)
                if re.fullmatch(r"/weight-service/weight/all/[\d-]+/[\d-]+", path):
                    return self._json([])
                if path == "/sleep-service/sleep/dailySleep":
                    return self._json(mock.sleep_row(date.fromisoformat(q["date"])))
                if match := re.fullmatch(r"/hrv-service/hrv/([\d-]+)", path):
                    d = date.fromisoformat(match.group(1))
                    if (mock.today - d).days > mock.hrv_days or not mock._worn(d):
                        return self._send(204)
                    return self._json({
                        "userProfilePk": PLANTED_PROFILE_ID,
                        "hrvSummary": {"calendarDate": d.isoformat(), "lastNightAvg": 55, "status": "BALANCED"},
                        "hrvReadings": [{"hrvValue": 50 + i, "readingTimeGMT": f"{d.isoformat()}T00:{i * 5:02d}:00.0"} for i in range(6)],
                        "sleepStartTimestampLocal": f"{(d - timedelta(days=1)).isoformat()}T23:00:00.0",
                        "sleepEndTimestampLocal": f"{d.isoformat()}T06:30:00.0",
                    })
                if path == "/wellness-service/wellness/dailyHeartRate":
                    d = date.fromisoformat(q["date"])
                    ok = mock._in_history(d) and mock._worn(d)
                    return self._json({"restingHeartRate": 52 if ok else None, "heartRateValues": [[1, 60], [2, 61]] if ok else None})
                if re.fullmatch(r"/wellness-service/wellness/daily/spo2acclimation/[\d-]+", path):
                    return self._json({"averageSpO2": None, "spO2HourlyAverages": None})
                if path == "/usersummary-service/usersummary/daily":
                    d = date.fromisoformat(q["calendarDate"])
                    ok = mock._in_history(d) and mock._worn(d)
                    return self._json({"displayName": "SECRET_DISPLAY", "calendarDate": d.isoformat(),
                                       "restingHeartRate": 53 if ok else None, "totalSteps": 9000 if ok else None,
                                       "lastSyncTimestampGMT": "2020-01-01T00:00:00.0"})
                if re.fullmatch(r"/fitnessage-service/fitnessage/v2/[\d-]+", path):
                    return self._json([{"fitnessAge": 30.5, "chronologicalAge": 34}])
                if match := re.fullmatch(r"/wellnessactivity-service/activity/summary/range/([\d-]+)/([\d-]+)", path):
                    return self._json([
                        {"calendarDate": d.isoformat(), "activityName": "SECRET_ACTIVITY_NAME",
                         "wellnessActivityType": "HEALTH_MONITORING",
                         "summaryTypeDataList": [{"summaryType": "RMSSD_HRV", "minValue": 20.0, "maxValue": 90.0, "avgValue": 54.0},
                                                 {"summaryType": "SDRR_HRV", "minValue": 30.0, "maxValue": 99.0, "avgValue": 70.0}]}
                        for d in self._dates(match.group(1), match.group(2)) if mock._worn(d)])
                if re.fullmatch(r"/weight-service/weight/range/[\d-]+/[\d-]+", path):
                    return self._json({"dailyWeightSummaries": []})
                if re.fullmatch(r"/goal-service/goal/user/effective/weightgoal/[\d-]+/[\d-]+", path):
                    return self._json({})
                if re.fullmatch(r"/nutrition-service/food/logs/[\d-]+", path):
                    return self._json({})
                # Matches the reported behaviour of the host: anything undocumented is a 404.
                return self._send(404)

        return Handler
