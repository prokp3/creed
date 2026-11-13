"""The intervals.icu sync: incremental, idempotent and resumable, like Garmin's.

Each run refreshes the last few days first, since a watch can sync late, then walks back through history with whatever
request and time budget is left. Progress is committed after every window or file, so a run that's cut off loses
nothing. Rows are written with source = 'intervals' into the same tables Garmin's go to, so every metric and screen
reads them unchanged. FIT files go through the same reader as Garmin's, for route maps and heart rate load.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from creed.db.store import Batch, Cursor, Store
from creed.garmin.api import ApiError, SchemaChanged
from creed.garmin.client import ApiStopped, AuthFailed
from creed.garmin.fit import read_activity_zip
from creed.intervals import api
from creed.intervals import normalize as inorm
from creed.intervals.client import Client, gunzipped
from creed.sync import normalize
from creed.sync.engine import EMPTY_STOP_DAYS, MAX_FILE_ATTEMPTS, REFRESH_DAYS, SyncResult, derive_pending
from creed.sync.normalize import BadRecord, Flag

SOURCE = "intervals"
WELLNESS = "intervals_wellness"
ACTIVITIES = "intervals_activities"
DATASETS = (WELLNESS, ACTIVITIES)
# A year of wellness is one small response. Activities are bigger, so they come half a year at a time.
WINDOW_DAYS = {WELLNESS: 365, ACTIVITIES: 180}
# Nothing synced to intervals.icu before this, so history never needs to look further back.
HISTORY_FLOOR = date(2008, 1, 1)
NOT_SHARED_SOURCES = {"STRAVA": "Strava", "GARMIN_CONNECT": "Garmin"}


def _parse_wellness(batch: Batch, row: dict, _unavailable: Counter) -> date | None:
    record, sleep, sleep_flags = inorm.wellness(row)
    day = record.calendar_date
    key = day.isoformat()
    if record.metrics or sleep:
        batch.raw[("intervals_wellness", key)] = row
    batch.add_metrics(day, inorm.WELLNESS_METRICS, record.metrics)
    batch.add_flags("daily", key, record.flags)
    if sleep is None:
        batch.sleep_removed.add(day)
    else:
        batch.sleep[day] = sleep
    batch.add_flags("sleep", key, sleep_flags)
    return day if record.has_data or sleep else None


def _parse_activity(batch: Batch, row: dict, unavailable: Counter) -> date | None:
    try:
        values, flags = inorm.activity(row)
    except inorm.Unavailable:
        unavailable[NOT_SHARED_SOURCES.get(row.get("source"), "another service")] += 1
        return normalize.parse_date(row.get("start_date_local"))
    key = str(values["activity_id"])
    batch.raw[("intervals_activity", key)] = row
    batch.activities[values["activity_id"]] = values
    batch.add_flags("activity", key, flags)
    return values["local_date"]


PARSERS: dict[str, Callable[[Batch, dict, Counter], date | None]] = {WELLNESS: _parse_wellness, ACTIVITIES: _parse_activity}


def _fetch(client: Client, athlete: str, name: str, start: date, end: date) -> list[dict]:
    if name == WELLNESS:
        return api.wellness(client, athlete, start, end)
    return api.activities(client, athlete, start, end)


class _Run:
    def __init__(self, store: Store, client: Client, athlete: str, today: date) -> None:
        self.store = store
        self.client = client
        self.athlete = athlete
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

    def _ingest(self, name: str, rows: list[dict], ref: str, cursor: Cursor) -> bool:
        """Parse a window of records, then write them together. One bad record doesn't cost the others."""
        batch = Batch()
        any_data = False
        unreadable = 0
        unavailable: Counter = Counter()
        for row in rows:
            try:
                day = PARSERS[name](batch, row, unavailable)
            except (BadRecord, TypeError, ValueError, AttributeError):
                unreadable += 1
                continue
            self.records += 1
            if day is not None:
                any_data = True
                if cursor.first_data_date is None or day < cursor.first_data_date:
                    cursor.first_data_date = day
        flags = [Flag("unreadable_records", "problem", f"{unreadable} records couldn't be read.")] if unreadable else []
        for service, count in unavailable.items():
            flags.append(Flag(f"not_shared_{service.lower().replace(' ', '_')}", "info",
                              f"{count} activities came to intervals.icu from {service}, which doesn't let it pass "
                              "them on to other apps."))
        batch.add_flags("sync", f"{name}:{ref}", flags)
        self.store.write_batch(batch, SOURCE)
        return any_data

    def refresh(self, name: str) -> None:
        cursor = self.store.get_cursor(name)
        recent = self.today - timedelta(days=REFRESH_DAYS - 1)
        # After downtime, cover everything since the last good date as well.
        day = min(recent, cursor.newest_date - timedelta(days=REFRESH_DAYS - 1)) if cursor.newest_date else recent
        if cursor.oldest_date is None:
            cursor.oldest_date = day
        while day <= self.today:
            end = min(day + timedelta(days=WINDOW_DAYS[name] - 1), self.today)
            rows = _fetch(self.client, self.athlete, name, day, end)
            self._ingest(name, rows, end.isoformat(), cursor)
            cursor.newest_date = end
            self.store.save_cursor(cursor)
            self.store.commit()
            day = end + timedelta(days=1)

    def backfill(self, name: str) -> None:
        cursor = self.store.get_cursor(name)
        if cursor.backfill_done or cursor.oldest_date is None:
            return
        while not cursor.backfill_done:
            end = cursor.oldest_date - timedelta(days=1)
            if end < HISTORY_FLOOR:
                cursor.backfill_done = True
                break
            start = max(end - timedelta(days=WINDOW_DAYS[name] - 1), HISTORY_FLOOR)
            rows = _fetch(self.client, self.athlete, name, start, end)
            had_data = self._ingest(name, rows, end.isoformat(), cursor)
            cursor.oldest_date = start
            cursor.empty_days = 0 if had_data else cursor.empty_days + (end - start).days + 1
            if cursor.empty_days >= EMPTY_STOP_DAYS:
                cursor.backfill_done = True
            self.store.save_cursor(cursor)
            self.store.commit()
        self.store.save_cursor(cursor)
        self.store.commit()

    def download_files(self) -> None:
        while True:
            pending = self.store.activities_needing_file(10, MAX_FILE_ATTEMPTS, intervals=True)
            if not pending:
                return
            for item in pending:
                self._download_file(item["activity_id"], item["discipline"])

    def _download_file(self, activity_id: int, discipline: str) -> None:
        r = api.activity_fit(self.client, inorm.intervals_id(activity_id))
        content = gunzipped(r.body) if r.ok else b""
        if r.status in (204, 404) or (r.ok and not content):
            self.store.set_file_status(activity_id, "none")
        elif r.status in (403, 422):
            # intervals.icu won't hand over some files, such as ones that came from Strava. The summary still counts.
            self.store.set_file_status(activity_id, "none")
            self.store.replace_flags("activity_file", str(activity_id), [
                Flag("file_not_shared", "info", "intervals.icu didn't share this activity's file, so it has no map "
                                                "or heart rate breakdown.")])
        elif not r.ok:
            self.store.set_file_status(activity_id, "failed")
            self.errors.append({"step": "activity_file", "status": r.status, "schema_changed": False,
                                "message": f"Activity file answered HTTP {r.status or r.error}"})
        else:
            self.store.save_activity_file(activity_id, content, hashlib.sha256(content).hexdigest())
            self.store.replace_flags("activity_file", str(activity_id),
                                     normalize.fit_flags(discipline, read_activity_zip(content)))
            self.records += 1
        self.store.commit()


def run_intervals_sync(store: Store, client: Client, *, athlete: str, today: date,
                       trigger: str = "manual") -> SyncResult:
    store.close_abandoned_runs()
    run_id = store.start_run(trigger)
    store.commit()
    run = _Run(store, client, athlete, today)
    status, message = "ok", None
    backfilling = False
    try:
        for name in DATASETS:
            run.guarded(name, lambda name=name: run.refresh(name))

        # Today's numbers are in. Files and history can carry over to the next run if need be.
        backfilling = True
        run.guarded("activity_file", run.download_files)
        for name in DATASETS:
            run.guarded(f"{name} history", lambda name=name: run.backfill(name))
        run.guarded("activity_file", run.download_files)
        derive_pending(store)
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

    pending = store.backfill_pending(DATASETS, intervals=True)
    details = {"source": SOURCE, "errors": run.errors, "rate_limit_events": client.rate_limit_events[:5]}
    store.finish_run(run_id, status=status, requests=client.requests, records=run.records,
                     backfill_pending=pending, message=message, details=details)
    store.commit()
    return SyncResult(status, message, client.requests, run.records, pending, run.errors)
