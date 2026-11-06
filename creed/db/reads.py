"""Load what the metrics need from the database into plain data."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import psycopg

from creed.metrics.base import ActivityRecord, MetricContext, Settings, SleepRecord


def _local_minutes(moment: datetime | None, offset_minutes: int | None) -> int | None:
    if moment is None or offset_minutes is None:
        return None
    local = moment.astimezone(timezone.utc) + timedelta(minutes=offset_minutes)
    return local.hour * 60 + local.minute


def metric_series(conn: psycopg.Connection, names: list[str], start: date, end: date) -> dict[str, dict[date, Any]]:
    """Values by metric and day. Flagged values stay out."""
    rows = conn.execute(
        "select calendar_date, metric, value_num, value_text from daily_metric_best "
        "where metric = any(%s) and calendar_date between %s and %s and quality = 'ok'",
        (names, start, end),
    ).fetchall()
    series: dict[str, dict[date, Any]] = {name: {} for name in names}
    for r in rows:
        series[r["metric"]][r["calendar_date"]] = r["value_text"] if r["value_text"] is not None else r["value_num"]
    return series


def recent_quality_flags(conn: psycopg.Connection, since: date, severities: tuple[str, ...]) -> list[dict[str, Any]]:
    """Open flags on records from `since` onwards. Old ones stay on the Data Quality page only."""
    return conn.execute(
        """
        select f.scope, f.ref_key, f.code, f.severity, f.detail, f.last_seen,
               coalesce(a.local_date, case when f.ref_key ~ '^\\d{4}-\\d{2}-\\d{2}$' then f.ref_key::date end) as day
        from quality_flag f
        left join activity a on f.scope in ('activity', 'activity_file') and a.activity_id::text = f.ref_key
        where f.resolved_at is null and f.severity = any(%s)
          and coalesce(a.local_date, case when f.ref_key ~ '^\\d{4}-\\d{2}-\\d{2}$' then f.ref_key::date end) >= %s
        order by day desc, f.severity
        """,
        (list(severities), since),
    ).fetchall()


def quality_summary(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        "select scope, code, severity, max(detail) as example, count(*) as open_count, max(last_seen) as last_seen "
        "from quality_flag where resolved_at is null "
        "group by scope, code, severity "
        "order by case severity when 'problem' then 0 when 'warning' then 1 else 2 end, open_count desc"
    ).fetchall()


def latest_run(conn: psycopg.Connection) -> dict[str, Any] | None:
    return conn.execute(
        "select status, trigger, started_at, finished_at, requests, records, backfill_pending, message "
        "from sync_run where trigger is distinct from 'export' order by id desc limit 1"
    ).fetchone()


def sync_running(conn: psycopg.Connection, within_minutes: int) -> bool:
    return conn.execute(
        "select exists (select 1 from sync_run where status = 'running' "
        "and started_at > now() - make_interval(mins => %s)) as running",
        (within_minutes,),
    ).fetchone()["running"]


def last_good_run(conn: psycopg.Connection) -> datetime | None:
    row = conn.execute(
        "select max(finished_at) as finished_at from sync_run where status in ('ok', 'partial') "
        "and trigger is distinct from 'export'"
    ).fetchone()
    return row["finished_at"]


def list_activities(conn: psycopg.Connection, discipline: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    """Normalized columns only, so names, notes and GPS can't reach a response from here."""
    return conn.execute(
        "select a.activity_id, a.type_key, a.discipline, a.start_time, a.local_date, a.utc_offset_minutes, "
        "a.duration_seconds, a.distance_m, a.avg_speed_mps, a.avg_hr, a.max_hr, a.garmin_load, a.aerobic_effect, "
        "a.anaerobic_effect, a.avg_power, a.norm_power, a.avg_swolf, a.quality, d.hr_coverage, d.steady, "
        "d.efficiency, d.decoupling_pct "
        "from activity a left join activity_derived d using (activity_id) "
        "where not a.is_parent and (%(d)s::text is null or a.discipline = %(d)s) "
        "order by a.start_time desc nulls last limit %(l)s offset %(o)s",
        {"d": discipline, "l": limit, "o": offset},
    ).fetchall()


def get_activity(conn: psycopg.Connection, activity_id: int) -> dict[str, Any] | None:
    return conn.execute(
        "select a.activity_id, a.type_key, a.discipline, a.start_time, a.local_date, a.utc_offset_minutes, "
        "a.duration_seconds, a.moving_seconds, a.elapsed_seconds, a.distance_m, a.avg_speed_mps, a.avg_hr, a.max_hr, "
        "a.garmin_load, a.aerobic_effect, a.anaerobic_effect, a.moderate_minutes, a.vigorous_minutes, a.avg_power, "
        "a.max_power, a.norm_power, a.pool_length_m, a.active_lengths, a.strokes, a.avg_swolf, a.is_manual, a.quality, "
        "a.fit_status, d.samples, d.hr_coverage, d.hr_seconds, d.steady, d.efficiency, d.decoupling_pct "
        "from activity a left join activity_derived d using (activity_id) where a.activity_id = %s",
        (activity_id,),
    ).fetchone()


def activity_file(conn: psycopg.Connection, activity_id: int) -> bytes | None:
    row = conn.execute("select content from activity_file where activity_id = %s", (activity_id,)).fetchone()
    return bytes(row["content"]) if row else None


def activity_flags(conn: psycopg.Connection, activity_id: int) -> list[dict[str, Any]]:
    return conn.execute(
        "select code, severity, detail from quality_flag "
        "where scope in ('activity', 'activity_file') and ref_key = %s and resolved_at is null",
        (str(activity_id),),
    ).fetchall()


def load_context(conn: psycopg.Connection, today: date, settings: Settings | None = None,
                 now: datetime | None = None) -> MetricContext:
    metrics = conn.execute(
        "select calendar_date, metric, value_num from daily_metric_best "
        "where metric in ('hrv_last_night_avg', 'resting_hr') and quality = 'ok' and value_num is not null "
        "and calendar_date <= %s",
        (today,),
    ).fetchall()
    hrv = {r["calendar_date"]: r["value_num"] for r in metrics if r["metric"] == "hrv_last_night_avg"}
    resting = {r["calendar_date"]: r["value_num"] for r in metrics if r["metric"] == "resting_hr"}

    sleep = [
        SleepRecord(
            day=r["calendar_date"],
            seconds=r["sleep_seconds"],
            start_local_minutes=_local_minutes(r["sleep_start"], r["utc_offset_minutes"]),
            end_local_minutes=_local_minutes(r["sleep_end"], r["utc_offset_minutes"]),
            deep_seconds=r["deep_seconds"],
            light_seconds=r["light_seconds"],
            rem_seconds=r["rem_seconds"],
            respiration=r["respiration_avg"],
            score=r["score_overall"],
            flagged=r["quality"] != "ok",
        )
        for r in conn.execute("select * from sleep_night_best where calendar_date <= %s", (today,)).fetchall()
        if r["sleep_seconds"]
    ]

    activities = [
        ActivityRecord(
            activity_id=r["activity_id"],
            day=r["local_date"],
            discipline=r["discipline"],
            type_key=r["type_key"],
            duration_seconds=r["duration_seconds"],
            distance_m=r["distance_m"],
            avg_hr=r["avg_hr"],
            max_hr=r["max_hr"],
            is_parent=r["is_parent"],
            flagged=r["quality"] != "ok",
            hr_seconds={int(k): v for k, v in (r["hr_seconds"] or {}).items()} or None,
            steady=bool(r["steady"]),
            efficiency=r["efficiency"],
            decoupling_pct=r["decoupling_pct"],
            steady_speed_mps=r["steady_speed_mps"],
            steady_hr=r["steady_hr"],
        )
        for r in conn.execute(
            "select a.*, d.hr_seconds, d.steady, d.efficiency, d.decoupling_pct, d.steady_speed_mps, d.steady_hr "
            "from activity a left join activity_derived d using (activity_id) "
            "where a.local_date is not null and a.local_date <= %s",
            (today,),
        ).fetchall()
    ]
    return MetricContext(today=today, now=now or datetime.now(timezone.utc), settings=settings or Settings(),
                         hrv=hrv, resting_hr=resting, sleep=sleep, activities=activities)
