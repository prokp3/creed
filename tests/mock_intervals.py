"""A local stand-in for the intervals.icu API, shaped after its OpenAPI document. All data is synthetic.

Values starting SECRET_, and PLANTED_LATITUDE inside the FIT files, are planted so tests can prove they never reach a
normalized table or a report.
"""
from __future__ import annotations

import base64
import gzip
import json
import threading
import urllib.parse
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from mock_garmin import PLANTED_LATITUDE, build_gps_fit

GOOD_KEY = "SECRET_INTERVALS_KEY_xyz789"
ACTIVITY_EVERY_DAYS = 3
STRAVA_STUB_ID = "16000001"
NOT_SHARED_FILE = 7  # The seventh activity's file is refused, as intervals.icu does for some sources.


def gps_points() -> list[tuple[int, float, float]]:
    return [(i * 2, PLANTED_LATITUDE + i * 0.0001, 73.8 + i * 0.0001) for i in range(30)]


class MockIntervals:
    def __init__(self, today: date, history_days: int = 120, *, rate_limit_hits: int = 0,
                 unworn_every: int = 10, sleep_days: int | None = None) -> None:
        self.today = today
        self.history_days = history_days
        self.rate_limit_hits = rate_limit_hits
        self.unworn_every = unworn_every
        self.sleep_days = history_days if sleep_days is None else sleep_days
        self.overrides: dict[str, dict[str, Any]] = {}
        self.data_requests = 0
        self.log: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "MockIntervals":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()

    # -- data -------------------------------------------------------------

    def first_day(self) -> date:
        return self.today - timedelta(days=self.history_days)

    def wellness_row(self, day: date) -> dict[str, Any]:
        n = (self.today - day).days
        row: dict[str, Any] = {"id": day.isoformat(), "ctl": 40.0, "atl": 45.0, "updated": "2026-11-05T06:00:00.000+00:00",
                               "comments": "SECRET_WELLNESS_NOTE"}
        if self.unworn_every and n % self.unworn_every == self.unworn_every - 1:
            row["steps"] = 0  # Not worn: nothing else measured.
            return {**row, **self.overrides.get(day.isoformat(), {})}
        row.update({"restingHR": 48 + n % 5, "hrv": 60.0 + n % 7, "steps": 9000 + n, "spO2": 97.0})
        if n < self.sleep_days:
            row.update({"sleepSecs": 7 * 3600 + (n % 4) * 600, "sleepScore": 80 + n % 10, "respiration": 14.5})
        return {**row, **self.overrides.get(day.isoformat(), {})}

    def activities(self) -> list[dict[str, Any]]:
        rows = []
        kinds = [("Run", False), ("Ride", True), ("Swim", False), ("Run", False), ("Ride", False)]
        for index, n in enumerate(range(0, self.history_days + 1, ACTIVITY_EVERY_DAYS)):
            day = self.today - timedelta(days=n)
            kind, trainer = kinds[index % len(kinds)]
            start_utc = datetime(day.year, day.month, day.day, 1, 0, 0)
            row = {
                "id": f"i{5_000_000 + index}",
                "start_date_local": (start_utc + timedelta(hours=5, minutes=30)).isoformat(),
                "start_date": start_utc.isoformat() + "Z",
                "type": kind,
                "trainer": trainer,
                "name": "SECRET_ACTIVITY_NAME",
                "description": "SECRET_NOTE",
                "moving_time": 3000,
                "elapsed_time": 3300,
                "distance": 10000.0 if kind != "Swim" else 2000.0,
                "average_speed": 3.33 if kind == "Run" else 8.0 if kind == "Ride" else 0.8,
                "average_heartrate": 145,
                "max_heartrate": 172,
                "icu_training_load": 60,
                "icu_weighted_avg_watts": 210 if kind == "Ride" else None,
                "pool_length": 25.0 if kind == "Swim" else None,
                "lengths": 80 if kind == "Swim" else None,
                "source": "COROS",
                "timezone": "Asia/Kolkata",
            }
            rows.append(row)
        # A Strava upload: intervals.icu lists it but shares nothing more.
        rows.append({"id": STRAVA_STUB_ID, "source": "STRAVA", "start_date_local": f"{self.today.isoformat()}T07:00:00",
                     "_note": "STRAVA activities are not available via the API"})
        return rows

    def fit_for(self, activity_id: str) -> tuple[int, bytes]:
        index = int(activity_id.removeprefix("i")) - 5_000_000
        if index == NOT_SHARED_FILE:
            return 403, b'{"error":"not available"}'
        return 200, gzip.compress(build_gps_fit(gps_points()))

    # -- server -----------------------------------------------------------

    def _handler(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
                self.send_response(status)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, body: Any) -> None:
                self._send(200, json.dumps(body).encode(), {"Content-Type": "application/json"})

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                query = dict(urllib.parse.parse_qsl(parsed.query))
                mock.log.append(parsed.path)
                expected = "Basic " + base64.b64encode(f"API_KEY:{GOOD_KEY}".encode()).decode()
                if self.headers.get("Authorization") != expected:
                    return self._send(401, b'{"error":"Unauthorized"}')
                if "python-urllib" in (self.headers.get("User-Agent") or "").lower():
                    return self._send(403, b"blocked")
                if mock.rate_limit_hits > 0:
                    mock.rate_limit_hits -= 1
                    return self._send(429, b"", {"Retry-After": "1"})
                mock.data_requests += 1
                parts = parsed.path.strip("/").split("/")
                if parts[:3] == ["api", "v1", "athlete"] and len(parts) == 5:
                    if parts[3] != "0":
                        return self._send(403, b'{"error":"Access denied"}')
                    oldest = date.fromisoformat(query["oldest"][:10])
                    newest = date.fromisoformat(query.get("newest", mock.today.isoformat())[:10])
                    if parts[4] == "wellness":
                        days = [newest - timedelta(days=i) for i in range((newest - oldest).days + 1)]
                        return self._json([mock.wellness_row(d) for d in sorted(days)
                                           if mock.first_day() <= d <= mock.today])
                    if parts[4] == "activities":
                        return self._json([a for a in mock.activities()
                                           if oldest <= date.fromisoformat(a["start_date_local"][:10]) <= newest])
                if parts[:3] == ["api", "v1", "activity"] and len(parts) == 5 and parts[4] == "fit-file":
                    status, body = mock.fit_for(parts[3])
                    return self._send(status, body, {"Content-Type": "application/octet-stream"})
                return self._send(404, b'{"error":"Not found"}')

        return Handler
