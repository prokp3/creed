"""All reads and writes the sync needs. Every write is an upsert, so repeating one changes nothing.

Writes go in batches. The database is a network trip away, about 45 ms per statement from
India to Supabase in Mumbai, so a year of daily data written row by row would take minutes
and overrun a serverless function. Multi-row statements are used rather than psycopg's
executemany, because executemany relies on pipelining and Supabase's transaction pooler
doesn't support it.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from creed.sync.normalize import Flag, Metric

ROWS_PER_STATEMENT = 1000  # Postgres allows 65,535 parameters in a statement.
FLAG_KEY_SEPARATOR = "\x1f"


@dataclass
class Cursor:
    dataset: str
    newest_date: date | None = None
    oldest_date: date | None = None
    first_data_date: date | None = None
    backfill_done: bool = False
    empty_days: int = 0
    window_days: int | None = None
    page_offset: int = 0


@dataclass
class Batch:
    """Everything parsed from one window of responses. Keyed, so a repeated record can't conflict."""

    metric_groups: dict[tuple[str, ...], dict[date, list[Metric]]] = field(default_factory=dict)
    sleep: dict[date, dict[str, Any]] = field(default_factory=dict)
    sleep_removed: set[date] = field(default_factory=set)
    activities: dict[int, dict[str, Any]] = field(default_factory=dict)
    raw: dict[tuple[str, str], Any] = field(default_factory=dict)
    flags: dict[str, dict[str, list[Flag]]] = field(default_factory=dict)

    def add_metrics(self, day: date, owned: tuple[str, ...], metrics: list[Metric]) -> None:
        self.metric_groups.setdefault(owned, {})[day] = metrics

    def add_flags(self, scope: str, ref_key: str, flags: list[Flag]) -> None:
        self.flags.setdefault(scope, {})[ref_key] = flags


class Store:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def _write_rows(
        self,
        table: str,
        rows: list[dict[str, Any]],
        keys: tuple[str, ...] | None = None,
        stamp: str = "updated_at = now()",
    ) -> None:
        """Insert rows in as few statements as possible. With keys, existing rows are updated."""
        by_columns: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for row in rows:
            by_columns.setdefault(tuple(row), []).append(row)
        for columns, group in by_columns.items():
            head = sql.SQL("insert into {} ({}) values ").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns))
            )
            one_row = sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() * len(columns)))
            tail = sql.SQL("")
            if keys:
                updates = [sql.SQL("{0} = excluded.{0}").format(sql.Identifier(c)) for c in columns if c not in keys]
                tail = sql.SQL(" on conflict ({}) do update set {}").format(
                    sql.SQL(", ").join(map(sql.Identifier, keys)),
                    sql.SQL(", ").join([*updates, sql.SQL(stamp)]),
                )
            for start in range(0, len(group), ROWS_PER_STATEMENT):
                chunk = group[start : start + ROWS_PER_STATEMENT]
                statement = head + sql.SQL(", ").join([one_row] * len(chunk)) + tail
                self.conn.execute(statement, [row[c] for row in chunk for c in columns])

    def write_batch(self, batch: Batch, source: str) -> None:
        for owned, days in batch.metric_groups.items():
            self.replace_metrics(days, source, owned)
        if batch.sleep_removed:
            self.conn.execute(
                "delete from sleep_night where calendar_date = any(%s) and source = %s",
                (list(batch.sleep_removed), source),
            )
        self._write_rows("sleep_night", [{**row, "source": source} for row in batch.sleep.values()],
                         ("calendar_date", "source"))
        self._write_rows("activity", [self._activity_row(row, source) for row in batch.activities.values()],
                         ("activity_id",))
        self._write_rows(
            "raw_record",
            [{"dataset": dataset, "record_key": key, "source": source, "body": Jsonb(body)}
             for (dataset, key), body in batch.raw.items()],
            ("dataset", "record_key", "source"),
            stamp="fetched_at = now()",
        )
        for scope, by_ref in batch.flags.items():
            self.replace_flags_many(scope, by_ref)

    # -- secrets ---------------------------------------------------------

    def get_secret(self, name: str) -> str | None:
        row = self.conn.execute("select value from app_secret where name = %s", (name,)).fetchone()
        return row["value"] if row else None

    def set_secret(self, name: str, value: str, expires_at_epoch: float | None = None) -> None:
        expires = datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc) if expires_at_epoch else None
        self._write_rows("app_secret", [{"name": name, "value": value, "expires_at": expires}], ("name",))

    # -- data ------------------------------------------------------------

    def replace_metrics(self, days: dict[date, list[Metric]], source: str, owned: Iterable[str]) -> None:
        """Make the stored values for these metrics match what Garmin says now, removing any it withdrew."""
        if not days:
            return
        self.conn.execute(
            "delete from daily_metric where calendar_date = any(%s) and source = %s and metric = any(%s)",
            (list(days), source, list(owned)),
        )
        rows = [
            {"calendar_date": day, "metric": m.metric, "source": source, "value_num": m.value_num,
             "value_text": m.value_text, "quality": m.quality}
            for day, metrics in days.items()
            for m in metrics
        ]
        self._write_rows("daily_metric", rows)

    def replace_day_metrics(self, day: date, source: str, owned: Iterable[str], metrics: list[Metric]) -> None:
        self.replace_metrics({day: metrics}, source, owned)

    @staticmethod
    def _activity_row(row: dict[str, Any], source: str) -> dict[str, Any]:
        values = {**row, "source": source}
        if row.get("is_manual"):
            values["fit_status"] = "none"  # A manual entry has no recording to download.
        return values

    def activities_needing_file(self, limit: int, max_attempts: int = 3, *, intervals: bool = False) -> list[dict[str, Any]]:
        """Each source fetches only its own files: intervals.icu's rows, or everything else (Garmin's IDs)."""
        return self.conn.execute(
            "select activity_id, discipline, fit_attempts from activity "
            "where (fit_status = 'pending' or (fit_status = 'failed' and fit_attempts < %s)) "
            "and (source = 'intervals') = %s "
            "order by start_time desc nulls last limit %s",
            (max_attempts, intervals, limit),
        ).fetchall()

    def save_activity_file(self, activity_id: int, content: bytes, sha256: str) -> None:
        self.conn.execute(
            "insert into activity_file (activity_id, content, sha256) values (%s, %s, %s) "
            "on conflict (activity_id) do update set content = excluded.content, sha256 = excluded.sha256, "
            "fetched_at = now()",
            (activity_id, content, sha256),
        )
        self.set_file_status(activity_id, "ok")

    def set_file_status(self, activity_id: int, status: str, attempted: bool = True) -> None:
        self.conn.execute(
            "update activity set fit_status = %s, fit_attempts = fit_attempts + %s, updated_at = now() "
            "where activity_id = %s",
            (status, 1 if attempted else 0, activity_id),
        )

    def activity_files_to_derive(self, version: int, limit: int) -> list[dict[str, Any]]:
        return self.conn.execute(
            "select a.activity_id, a.discipline, a.type_key, f.content from activity a "
            "join activity_file f using (activity_id) "
            "left join activity_derived d using (activity_id) "
            "where d.activity_id is null or d.derive_version < %s "
            "order by a.start_time desc nulls last limit %s",
            (version, limit),
        ).fetchall()

    def save_derived(self, rows: list[dict[str, Any]]) -> None:
        self._write_rows("activity_derived",
                         [{**row, "hr_seconds": Jsonb(row["hr_seconds"])} for row in rows], ("activity_id",))

    def replace_flags_many(self, scope: str, by_ref: dict[str, list[Flag]]) -> None:
        """Record current problems for these records, and mark any that have gone away as resolved."""
        if not by_ref:
            return
        rows = [
            {"scope": scope, "ref_key": ref, "code": f.code, "severity": f.severity, "detail": f.detail}
            for ref, flags in by_ref.items()
            for f in {flag.code: flag for flag in flags}.values()
        ]
        self._write_rows("quality_flag", rows, ("scope", "ref_key", "code"),
                         stamp="last_seen = now(), resolved_at = null")
        current = [f"{row['ref_key']}{FLAG_KEY_SEPARATOR}{row['code']}" for row in rows]
        self.conn.execute(
            "update quality_flag set resolved_at = now() "
            "where scope = %s and ref_key = any(%s) and resolved_at is null "
            "and not (ref_key || %s || code = any(%s))",
            (scope, list(by_ref), FLAG_KEY_SEPARATOR, current),
        )

    def replace_flags(self, scope: str, ref_key: str, flags: list[Flag]) -> None:
        self.replace_flags_many(scope, {ref_key: flags})

    # -- sync bookkeeping ------------------------------------------------

    def get_cursor(self, dataset: str) -> Cursor:
        row = self.conn.execute(
            "select dataset, newest_date, oldest_date, first_data_date, backfill_done, empty_days, window_days, "
            "page_offset from sync_cursor where dataset = %s",
            (dataset,),
        ).fetchone()
        return Cursor(**row) if row else Cursor(dataset)

    def save_cursor(self, cursor: Cursor) -> None:
        self._write_rows("sync_cursor", [asdict(cursor)], ("dataset",))

    def backfill_pending(self, datasets: Iterable[str], *, intervals: bool = False) -> bool:
        names = list(datasets)
        done = self.conn.execute(
            "select count(*) as n from sync_cursor where dataset = any(%s) and backfill_done", (names,)
        ).fetchone()["n"]
        return done < len(names) or bool(self.activities_needing_file(1, intervals=intervals))

    def close_abandoned_runs(self, older_than_minutes: int = 15) -> int:
        """A run killed from outside, such as by a serverless time limit, can't record its own end."""
        return self.conn.execute(
            "update sync_run set status = 'failed', finished_at = now(), "
            "message = 'The run was cut off before it could finish.' "
            "where status = 'running' and started_at < now() - make_interval(mins => %s)",
            (older_than_minutes,),
        ).rowcount

    def start_run(self, trigger: str) -> int:
        return self.conn.execute(
            "insert into sync_run (trigger) values (%s) returning id", (trigger,)
        ).fetchone()["id"]

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        requests: int,
        records: int,
        backfill_pending: bool,
        message: str | None,
        details: dict[str, Any],
    ) -> None:
        self.conn.execute(
            "update sync_run set finished_at = now(), status = %s, requests = %s, records = %s, "
            "backfill_pending = %s, message = %s, details = %s where id = %s",
            (status, requests, records, backfill_pending, message, Jsonb(details), run_id),
        )
