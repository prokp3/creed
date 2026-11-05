"""The sync: incremental, idempotent and resumable.

Each run first refreshes the last few days, because a watch can sync late and Garmin can
correct a day afterwards. It then uses whatever request and time budget is left to walk
further back through history. Progress is committed after every window or file, so a run
that gets cut off loses nothing and the next run carries on from the same place.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from creed.db.store import Cursor, Store
from creed.garmin import api
from creed.garmin.api import ApiError, SchemaChanged
from creed.garmin.client import ApiStopped, AuthFailed, Client
from creed.garmin.fit import read_activity_zip
from creed.sync import normalize
from creed.sync.normalize import BadRecord, Flag

SOURCE = "api"
TOKEN_SECRET = "garmin_token"
REFRESH_DAYS = 3
WINDOW_STEPS = (365, 180, 90, 31, 28, 14, 7, 1)
# Stop looking further back after this many empty days in a row.
EMPTY_STOP_DAYS = 400
# HRV and sleep can have long gaps, so they look a little past the first day of daily data.
HISTORY_MARGIN_DAYS = 31
ACTIVITIES = "activities"
PROFILE = "profile"
MAX_FILE_ATTEMPTS = 3


class _WindowShrunk(Exception):
    """Garmin rejected a window as too wide. It has been narrowed, so try again."""


@dataclass
class SyncResult:
    status: str
    message: str | None
    requests: int
    records: int
    backfill_pending: bool
    errors: list[dict[str, Any]] = field(default_factory=list)


def _ingest_daily(store: Store, row: dict) -> date | None:
    record = normalize.daily_summary(row)
    key = record.calendar_date.isoformat()
    if record.metrics:
        store.save_raw("daily_summary", key, SOURCE, row)
    store.replace_day_metrics(record.calendar_date, SOURCE, normalize.DAILY_METRICS, record.metrics)
    store.replace_flags("daily", key, record.flags)
    return record.calendar_date if record.has_data else None


def _ingest_hrv(store: Store, row: dict) -> date | None:
    record = normalize.hrv_summary(row)
    key = record.calendar_date.isoformat()
    if record.metrics:
        store.save_raw("hrv_summary", key, SOURCE, row)
    store.replace_day_metrics(record.calendar_date, SOURCE, normalize.HRV_METRICS, record.metrics)
    store.replace_flags("hrv", key, record.flags)
    return record.calendar_date if record.has_data else None


def _ingest_sleep(store: Store, row: dict) -> date | None:
    parsed = normalize.sleep_night(row)
    day = normalize.parse_date(row.get("calendarDate"))
    if parsed is None:
        store.delete_sleep(day, SOURCE)
        store.replace_flags("sleep", day.isoformat(), [])
        return None
    values, flags = parsed
    store.save_raw("sleep_summary", day.isoformat(), SOURCE, row)
    store.upsert_sleep(values, SOURCE)
    store.replace_flags("sleep", day.isoformat(), flags)
    return day


@dataclass(frozen=True)
class RangeSet:
    name: str
    first_window: int  # The widest window measured to work on a real account.
    fetch: Callable[[Client, date, date], list[dict]]
    ingest: Callable[[Store, dict], date | None]


RANGE_SETS = (
    RangeSet("daily_summary", 365, api.daily_summaries, _ingest_daily),
    RangeSet("hrv_summary", 365, api.hrv_summaries, _ingest_hrv),
    RangeSet("sleep_summary", 31, api.sleep_summaries, _ingest_sleep),
)
# Daily summaries go first: where they start tells the others how far back to look.
HISTORY_ANCHOR = RANGE_SETS[0].name


class _Run:
    def __init__(self, store: Store, client: Client, today: date) -> None:
        self.store = store
        self.client = client
        self.today = today
        self.records = 0
        self.errors: list[dict[str, Any]] = []

    def guarded(self, step: str, work: Callable[[], None]) -> None:
        """One dataset failing mustn't stop the others."""
        try:
            work()
        except ApiError as exc:
            self.store.rollback()
            self.errors.append({
                "step": step,
                "status": exc.status,
                "schema_changed": isinstance(exc, SchemaChanged),
                "message": self.client.redact(str(exc)),
            })

    def _ingest_rows(self, name: str, ingest: Callable[[Store, dict], date | None], rows: list[dict],
                     ref: str, cursor: Cursor) -> bool:
        any_data = False
        unreadable = 0
        for row in rows:
            try:
                with self.store.conn.transaction():
                    day = ingest(self.store, row)
            except (BadRecord, TypeError, ValueError, AttributeError):
                unreadable += 1
                continue
            self.records += 1
            if day is not None:
                any_data = True
                if cursor.first_data_date is None or day < cursor.first_data_date:
                    cursor.first_data_date = day
        flags = [Flag("unreadable_records", "problem", f"{unreadable} records couldn't be read.")] if unreadable else []
        self.store.replace_flags("sync", f"{name}:{ref}", flags)
        return any_data

    def _fetch(self, ds: RangeSet, cursor: Cursor, start: date, end: date) -> list[dict]:
        try:
            return ds.fetch(self.client, start, end)
        except ApiError as exc:
            span = (end - start).days + 1
            smaller = next((w for w in WINDOW_STEPS if w < span), None)
            if exc.status in (400, 413, 422) and smaller is not None and not isinstance(exc, SchemaChanged):
                cursor.window_days = smaller
                self.store.save_cursor(cursor)
                self.store.commit()
                raise _WindowShrunk from exc
            raise

    def refresh(self, ds: RangeSet) -> None:
        cursor = self.store.get_cursor(ds.name)
        recent = self.today - timedelta(days=REFRESH_DAYS - 1)
        # After downtime, cover everything since the last good date as well.
        day = min(recent, cursor.newest_date - timedelta(days=REFRESH_DAYS - 1)) if cursor.newest_date else recent
        if cursor.oldest_date is None:
            cursor.oldest_date = day
        while day <= self.today:
            window = cursor.window_days or ds.first_window
            end = min(day + timedelta(days=window - 1), self.today)
            try:
                rows = self._fetch(ds, cursor, day, end)
            except _WindowShrunk:
                continue
            self._ingest_rows(ds.name, ds.ingest, rows, end.isoformat(), cursor)
            cursor.newest_date = end
            self.store.save_cursor(cursor)
            self.store.commit()
            day = end + timedelta(days=1)

    def backfill(self, ds: RangeSet) -> None:
        cursor = self.store.get_cursor(ds.name)
        if cursor.backfill_done or cursor.oldest_date is None:
            return
        floor: date | None = None
        if ds.name != HISTORY_ANCHOR:
            anchor = self.store.get_cursor(HISTORY_ANCHOR)
            if not anchor.backfill_done:
                return  # Wait until the start of your history is known.
            if anchor.first_data_date:
                floor = anchor.first_data_date - timedelta(days=HISTORY_MARGIN_DAYS)
        while not cursor.backfill_done:
            end = cursor.oldest_date - timedelta(days=1)
            if floor is not None and end < floor:
                cursor.backfill_done = True
                break
            window = cursor.window_days or ds.first_window
            start = end - timedelta(days=window - 1)
            if floor is not None:
                start = max(start, floor)
            try:
                rows = self._fetch(ds, cursor, start, end)
            except _WindowShrunk:
                continue
            had_data = self._ingest_rows(ds.name, ds.ingest, rows, end.isoformat(), cursor)
            cursor.oldest_date = start
            cursor.empty_days = 0 if had_data else cursor.empty_days + (end - start).days + 1
            if floor is None and cursor.empty_days >= EMPTY_STOP_DAYS:
                cursor.backfill_done = True
            self.store.save_cursor(cursor)
            self.store.commit()
        self.store.save_cursor(cursor)
        self.store.commit()

    def _ingest_activity(self, store: Store, row: dict) -> date | None:
        values, flags = normalize.activity(row)
        key = str(values["activity_id"])
        store.save_raw("activity", key, SOURCE, row)
        store.upsert_activity(values, SOURCE)
        store.replace_flags("activity", key, flags)
        return values["local_date"]

    def activities_latest(self) -> None:
        cursor = self.store.get_cursor(ACTIVITIES)
        rows = api.activities_page(self.client, 0)
        self._ingest_rows(ACTIVITIES, self._ingest_activity, rows, "latest", cursor)
        cursor.newest_date = self.today
        if cursor.page_offset == 0:
            cursor.page_offset = len(rows)
            cursor.backfill_done = not rows
        self.store.save_cursor(cursor)
        self.store.commit()

    def activities_backfill(self) -> None:
        cursor = self.store.get_cursor(ACTIVITIES)
        while not cursor.backfill_done:
            rows = api.activities_page(self.client, cursor.page_offset)
            # The server may cap a page below the size asked for, so only an empty page ends this.
            self._ingest_rows(ACTIVITIES, self._ingest_activity, rows, f"page-{cursor.page_offset}", cursor)
            cursor.page_offset += len(rows)
            cursor.backfill_done = not rows
            self.store.save_cursor(cursor)
            self.store.commit()

    def download_files(self) -> None:
        while True:
            pending = self.store.activities_needing_file(10, MAX_FILE_ATTEMPTS)
            if not pending:
                return
            for item in pending:
                self._download_file(item["activity_id"], item["discipline"])

    def _download_file(self, activity_id: int, discipline: str) -> None:
        r = api.activity_file(self.client, activity_id)
        if r.status in (204, 404) or (r.ok and not r.body):
            self.store.set_file_status(activity_id, "none")
        elif not r.ok:
            self.store.set_file_status(activity_id, "failed")
            self.errors.append({"step": "activity_file", "status": r.status, "schema_changed": False,
                                "message": f"Activity file answered HTTP {r.status or r.error}"})
        else:
            self.store.save_activity_file(activity_id, r.body, hashlib.sha256(r.body).hexdigest())
            self.store.replace_flags("activity_file", str(activity_id),
                                     normalize.fit_flags(discipline, read_activity_zip(r.body)))
            self.records += 1
        self.store.commit()

    def profile(self) -> None:
        cursor = self.store.get_cursor(PROFILE)
        if cursor.newest_date == self.today:
            return
        self.store.save_raw("heart_rate_zones", "current", SOURCE, api.heart_rate_zones(self.client))
        self.store.save_raw("profile_settings", "current", SOURCE, api.profile_settings(self.client))
        cursor.newest_date = self.today
        cursor.backfill_done = True
        self.store.save_cursor(cursor)
        self.store.commit()


def run_sync(store: Store, client: Client, *, today: date, trigger: str = "manual") -> SyncResult:
    run_id = store.start_run(trigger)
    store.commit()
    run = _Run(store, client, today)
    status, message = "ok", None
    backfilling = False
    try:
        client.ensure_token()
        store.commit()
        run.guarded("profile", run.profile)
        for ds in RANGE_SETS:
            run.guarded(ds.name, lambda ds=ds: run.refresh(ds))
        run.guarded(ACTIVITIES, run.activities_latest)

        # Today's numbers are in. Files and history can carry over to the next run if need be.
        backfilling = True
        run.guarded("activity_file", run.download_files)
        for ds in RANGE_SETS:
            run.guarded(f"{ds.name} history", lambda ds=ds: run.backfill(ds))
        run.guarded(f"{ACTIVITIES} history", run.activities_backfill)
        run.guarded("activity_file", run.download_files)
    except AuthFailed as exc:
        store.rollback()
        status, message = "auth_failed", client.redact(str(exc))
    except ApiStopped as exc:
        store.rollback()
        # Running out of budget while walking history is expected. The next run carries on.
        if not (backfilling and exc.reason in ("budget", "time")):
            status = "partial"
        message = client.redact(str(exc))
    except Exception as exc:  # noqa: BLE001  A run must always end with its outcome on record.
        store.rollback()
        status, message = "failed", client.redact(f"{type(exc).__name__}: {exc}")
    if run.errors and status == "ok":
        status = "partial"
        message = message or f"{len(run.errors)} step(s) failed; see details."

    names = [ds.name for ds in RANGE_SETS] + [ACTIVITIES]
    pending = store.backfill_pending(names)
    details = {"errors": run.errors, "rate_limit_events": client.rate_limit_events[:5]}
    store.finish_run(run_id, status=status, requests=client.requests, records=run.records,
                     backfill_pending=pending, message=message, details=details)
    store.commit()
    return SyncResult(status, message, client.requests, run.records, pending, run.errors)
