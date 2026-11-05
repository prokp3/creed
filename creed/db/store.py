"""All reads and writes the sync needs. Every write is an upsert, so repeating one changes nothing."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from creed.sync.normalize import Flag, Metric


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


class Store:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def _upsert(self, table: str, row: dict[str, Any], keys: tuple[str, ...]) -> None:
        columns = list(row)
        updates = [c for c in columns if c not in keys]
        statement = sql.SQL(
            "insert into {table} ({columns}) values ({values}) on conflict ({keys}) do update set {updates}"
        ).format(
            table=sql.Identifier(table),
            columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
            values=sql.SQL(", ").join(map(sql.Placeholder, columns)),
            keys=sql.SQL(", ").join(map(sql.Identifier, keys)),
            updates=sql.SQL(", ").join(
                [sql.SQL("{0} = excluded.{0}").format(sql.Identifier(c)) for c in updates]
                + [sql.SQL("updated_at = now()")]
            ),
        )
        self.conn.execute(statement, row)

    # -- secrets ---------------------------------------------------------

    def get_secret(self, name: str) -> str | None:
        row = self.conn.execute("select value from app_secret where name = %s", (name,)).fetchone()
        return row["value"] if row else None

    def set_secret(self, name: str, value: str, expires_at_epoch: float | None = None) -> None:
        expires = datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc) if expires_at_epoch else None
        self._upsert("app_secret", {"name": name, "value": value, "expires_at": expires}, ("name",))

    # -- data ------------------------------------------------------------

    def replace_day_metrics(self, day: date, source: str, owned: Iterable[str], metrics: list[Metric]) -> None:
        """Make the stored values for these metrics match what Garmin says now, removing any it withdrew."""
        self.conn.execute(
            "delete from daily_metric where calendar_date = %s and source = %s and metric = any(%s)",
            (day, source, list(owned)),
        )
        for m in metrics:
            self.conn.execute(
                "insert into daily_metric (calendar_date, metric, source, value_num, value_text, quality) "
                "values (%s, %s, %s, %s, %s, %s)",
                (day, m.metric, source, m.value_num, m.value_text, m.quality),
            )

    def upsert_sleep(self, row: dict[str, Any], source: str) -> None:
        self._upsert("sleep_night", {**row, "source": source}, ("calendar_date", "source"))

    def delete_sleep(self, day: date, source: str) -> None:
        self.conn.execute("delete from sleep_night where calendar_date = %s and source = %s", (day, source))

    def upsert_activity(self, row: dict[str, Any], source: str) -> None:
        values = {**row, "source": source}
        if row.get("is_manual"):
            values["fit_status"] = "none"  # A manual entry has no recording to download.
        self._upsert("activity", values, ("activity_id",))

    def save_raw(self, dataset: str, key: str, source: str, body: Any) -> None:
        self.conn.execute(
            "insert into raw_record (dataset, record_key, source, body) values (%s, %s, %s, %s) "
            "on conflict (dataset, record_key, source) do update set body = excluded.body, fetched_at = now()",
            (dataset, key, source, Jsonb(body)),
        )

    def activities_needing_file(self, limit: int, max_attempts: int = 3) -> list[dict[str, Any]]:
        return self.conn.execute(
            "select activity_id, discipline, fit_attempts from activity "
            "where fit_status = 'pending' or (fit_status = 'failed' and fit_attempts < %s) "
            "order by start_time desc nulls last limit %s",
            (max_attempts, limit),
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

    def replace_flags(self, scope: str, ref_key: str, flags: list[Flag]) -> None:
        """Record current problems for one record, and mark any that have gone away as resolved."""
        for flag in flags:
            self.conn.execute(
                "insert into quality_flag (scope, ref_key, code, severity, detail) values (%s, %s, %s, %s, %s) "
                "on conflict (scope, ref_key, code) do update set severity = excluded.severity, "
                "detail = excluded.detail, last_seen = now(), resolved_at = null",
                (scope, ref_key, flag.code, flag.severity, flag.detail),
            )
        self.conn.execute(
            "update quality_flag set resolved_at = now() "
            "where scope = %s and ref_key = %s and resolved_at is null and not (code = any(%s))",
            (scope, ref_key, [f.code for f in flags]),
        )

    # -- sync bookkeeping ------------------------------------------------

    def get_cursor(self, dataset: str) -> Cursor:
        row = self.conn.execute(
            "select dataset, newest_date, oldest_date, first_data_date, backfill_done, empty_days, window_days, "
            "page_offset from sync_cursor where dataset = %s",
            (dataset,),
        ).fetchone()
        return Cursor(**row) if row else Cursor(dataset)

    def save_cursor(self, cursor: Cursor) -> None:
        self._upsert("sync_cursor", asdict(cursor), ("dataset",))

    def backfill_pending(self, datasets: Iterable[str]) -> bool:
        names = list(datasets)
        done = self.conn.execute(
            "select count(*) as n from sync_cursor where dataset = any(%s) and backfill_done", (names,)
        ).fetchone()["n"]
        return done < len(names) or bool(self.activities_needing_file(1))

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
