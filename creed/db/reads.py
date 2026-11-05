"""Load what the metrics need from the database into plain data."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import psycopg

from creed.metrics.base import ActivityRecord, MetricContext, Settings, SleepRecord


def _local_minutes(moment: datetime | None, offset_minutes: int | None) -> int | None:
    if moment is None or offset_minutes is None:
        return None
    local = moment.astimezone(timezone.utc) + timedelta(minutes=offset_minutes)
    return local.hour * 60 + local.minute


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
