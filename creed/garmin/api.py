"""The documented endpoints the sync uses, with their responses checked for shape.

A response that no longer looks as expected raises SchemaChanged instead of being
read as "no data", so a Garmin change shows up as a visible error.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from creed.garmin.client import Client, Resp

ACTIVITY_PAGE_SIZE = 99  # Swagger's documented default.


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class SchemaChanged(ApiError):
    """Garmin answered, but not in the shape this code expects."""


def _json(client: Client, path: str, params: dict[str, Any] | None = None) -> Any:
    r = client.get(path, params)
    return _decoded(r, path)


def _decoded(r: Resp, path: str) -> Any:
    if not r.ok:
        raise ApiError(f"{path} answered HTTP {r.status or r.error}", r.status)
    try:
        return r.json()
    except ValueError as exc:
        raise SchemaChanged(f"{path} did not answer with JSON") from exc


def _rows(body: Any, path: str, expected: tuple[str, ...]) -> list[dict]:
    if body is None:
        return []
    if not isinstance(body, list) or not all(isinstance(row, dict) for row in body):
        raise SchemaChanged(f"{path} did not answer with a list of records")
    if body and not any(key in row for row in body for key in expected):
        raise SchemaChanged(f"{path} records no longer contain any of: {', '.join(expected)}")
    return body


def daily_summaries(client: Client, start: date, end: date) -> list[dict]:
    path = "/usersummary-service/v2/dailysummaries"
    body = _json(client, path, {"startDate": start.isoformat(), "endDate": end.isoformat()})
    if body is None:
        return []
    if not isinstance(body, dict) or "data" not in body:
        raise SchemaChanged(f"{path} no longer has a data list")
    return _rows(body["data"], path, ("heartRate", "movement", "stress", "bodyBattery"))


def hrv_summaries(client: Client, start: date, end: date) -> list[dict]:
    path = "/hrv-service/hrv/daily"
    body = _json(client, f"{path}/{start.isoformat()}/{end.isoformat()}")
    if body is None:  # Documented: 204 means no data.
        return []
    if not isinstance(body, dict) or "hrvSummaries" not in body:
        raise SchemaChanged(f"{path} no longer has an hrvSummaries list")
    return _rows(body["hrvSummaries"], path, ("lastNightAvg", "status", "baseline"))


def sleep_summaries(client: Client, start: date, end: date) -> list[dict]:
    path = "/sleep-service/sleep/dailySleepSummariesByDate"
    body = _json(client, path, {"startDate": start.isoformat(), "endDate": end.isoformat()})
    return _rows(body, path, ("sleepTimeSeconds", "sleepStartTimestampGMT"))


def activities_page(client: Client, start: int, limit: int = ACTIVITY_PAGE_SIZE) -> list[dict]:
    path = "/activitylist-service/activities/search/activities"
    body = _json(client, path, {"start": start, "limit": limit, "excludeChildren": "false"})
    return _rows(body, path, ("activityId",))


def activity_file(client: Client, activity_id: int) -> Resp:
    """The original file as ZIP bytes. Returned as a response so the caller can read its status."""
    return client.get(
        f"/download-service/files/activity/{activity_id}",
        accept="application/zip, application/x-zip-compressed, application/octet-stream",
    )


def heart_rate_zones(client: Client) -> Any:
    return _json(client, "/biometric-service/heartRateZones/v2")


def profile_settings(client: Client) -> Any:
    return _json(client, "/userprofile-service/userprofile/settings")
