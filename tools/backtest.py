#!/usr/bin/env python3
"""Check the metrics against your real history: `python tools/backtest.py`.

This prints aggregates of your health data to the screen and writes nothing to disk.
"""
from __future__ import annotations

import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from creed import config  # noqa: E402
from creed.db import connect  # noqa: E402
from creed.db.reads import load_context  # noqa: E402
from creed.metrics import backtest, compute_all, hr_params, recovery, strain  # noqa: E402
from creed.metrics.base import MetricContext, OK, Settings  # noqa: E402


def number(value, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def main() -> None:
    config.load_dotenv()
    today = config.local_today()
    with connect(config.database_url()) as conn:
        ctx = load_context(conn, today, Settings(), datetime.now(timezone.utc))
        garmin_loads = {
            r["activity_id"]: r["garmin_load"]
            for r in conn.execute("select activity_id, garmin_load from activity where garmin_load is not null").fetchall()
        }

    print("== Today")
    for key, result in compute_all(ctx).items():
        shown = result.reason if result.state != OK else f"{number(float(result.value))} {result.unit}"
        print(f"  {key:<9} {result.state:<13} confidence={result.confidence:<7} {shown}")

    params = hr_params.estimate(ctx)
    print("\n== Heart rate estimates")
    print(f"  Max {params.max_hr}: {params.max_source}")
    print(f"  Resting {params.resting_hr}: {params.resting_source}")

    print("\n== Does Strain track Garmin's own per-activity load? (agreement is a sanity check, not a goal)")
    threshold = strain.swim_threshold_speed(ctx.activities)
    for discipline in ("run", "bike", "swim", "other"):
        pairs = []
        methods: dict[str, int] = {}
        for a in strain.counted(ctx.activities):
            if a.discipline != discipline or a.activity_id not in garmin_loads:
                continue
            load, method = strain.activity_load(a, params, threshold, ctx.settings.trimp_curve)
            methods[method] = methods.get(method, 0) + 1
            if load is not None:
                pairs.append((load, garmin_loads[a.activity_id]))
        correlation = backtest.spearman([p[0] for p in pairs], [p[1] for p in pairs])
        print(f"  {discipline:<6} activities={len(pairs):<3} correlation={number(correlation)} methods={methods}")

    print("\n== Do hard days tend to lower next-morning HRV?")
    for label, nights in (("Recovery's own baseline rule, 14 nights", recovery.MIN_BASELINE_NIGHTS),
                          ("Looser baseline, 5 nights, less reliable", 5)):
        response = backtest.load_vs_next_hrv(ctx, nights)
        print(f"  {label}:")
        print(f"    Nights usable: {response.pairs}")
        print(f"    Correlation of load with next-morning HRV z: {number(response.correlation)} "
              "(negative is the expected direction)")
        print(f"    Average HRV z after hard days: {number(response.after_hard_days)} ({response.hard_days} nights)")
        print(f"    Average HRV z after rest days: {number(response.after_rest_days)} ({response.rest_days} nights)")
        print(f"    Enough data to read anything into this: {'yes' if response.enough_data else 'NO'}")

    print("\n== Recovery across your history")
    scored = []
    for offset in range(0, 830):
        day = today - timedelta(days=offset)
        day_ctx = MetricContext(today=day, now=ctx.now, settings=ctx.settings, hrv=ctx.hrv,
                                resting_hr=ctx.resting_hr, sleep=ctx.sleep, activities=ctx.activities)
        score, _ = recovery.score_on(day_ctx, day)
        if score is not None:
            scored.append((day, score))
    print(f"  Mornings with a score: {len(scored)} of {len(ctx.hrv)} nights with HRV")
    if scored:
        values = [s for _, s in scored]
        print(f"  Lowest {min(values):.0f}, median {statistics.median(values):.0f}, highest {max(values):.0f}")
        print(f"  Most recent score: {scored[0][0]}")

    steady = [a for a in ctx.activities if a.steady]
    print("\n== Steady runs usable for aerobic efficiency")
    print(f"  {len(steady)} of {sum(1 for a in ctx.activities if a.discipline == 'run')} runs")
    if steady:
        print(f"  Efficiency median {statistics.median(a.efficiency for a in steady):.2f} m/min per bpm, "
              f"drift median {statistics.median(a.decoupling_pct for a in steady):.1f}%")
        print(f"  Most recent steady run: {max(a.day for a in steady)}")


if __name__ == "__main__":
    main()
