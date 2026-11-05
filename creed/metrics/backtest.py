"""Sanity checks on real history: do the numbers behave the way the physiology says they should?

These can't prove the metrics right. They can catch a metric that's clearly wrong, and they report how
much data each check rests on, so a weak result isn't mistaken for a strong one.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import timedelta

from creed.metrics import recovery, strain
from creed.metrics.base import MetricContext

MIN_PAIRS = 10


def _ranks(values: list[float]) -> list[float]:
    """Ranks starting at 1, with tied values sharing their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    """Rank correlation, from -1 to 1. None if there are too few pairs or a side never varies."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mean_x, mean_y = statistics.fmean(rx), statistics.fmean(ry)
    spread = math.sqrt(sum((a - mean_x) ** 2 for a in rx) * sum((b - mean_y) ** 2 for b in ry))
    if spread == 0:
        return None
    return sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry)) / spread


@dataclass
class HrvResponse:
    pairs: int
    correlation: float | None
    after_hard_days: float | None
    hard_days: int
    after_rest_days: float | None
    rest_days: int
    enough_data: bool


def load_vs_next_hrv(ctx: MetricContext, min_baseline_nights: int = recovery.MIN_BASELINE_NIGHTS) -> HrvResponse:
    """Hard days should raise strain and tend to lower the next night's HRV against its baseline.

    A smaller min_baseline_nights uses more of a sparse history, but each comparison is less reliable.
    """
    loads = {day: sum(d.values()) for day, d in strain.daily_loads(ctx).items()}
    pairs: list[tuple[float, float]] = []
    for night, value in sorted(ctx.hrv.items()):
        baseline = [math.log(v) for d, v in ctx.hrv.items()
                    if timedelta(0) < night - d <= timedelta(days=recovery.BASELINE_DAYS)]
        if len(baseline) < min_baseline_nights:
            continue
        z = recovery.z_score(math.log(value), baseline)
        if z is not None:
            # HRV is filed under the morning you woke, so it follows the previous day's training.
            pairs.append((loads.get(night - timedelta(days=1), 0.0), z))

    nonzero = sorted(load for load, _ in pairs if load > 0)
    hard_line = statistics.median(nonzero) if nonzero else None
    hard = [z for load, z in pairs if hard_line is not None and load >= hard_line and load > 0]
    rest = [z for load, z in pairs if load == 0]
    return HrvResponse(
        pairs=len(pairs),
        correlation=spearman([p[0] for p in pairs], [p[1] for p in pairs]),
        after_hard_days=statistics.fmean(hard) if hard else None,
        hard_days=len(hard),
        after_rest_days=statistics.fmean(rest) if rest else None,
        rest_days=len(rest),
        enough_data=len(hard) >= MIN_PAIRS and len(rest) >= MIN_PAIRS,
    )
