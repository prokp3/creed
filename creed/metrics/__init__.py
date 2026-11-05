"""The seven v1 metrics. To add one, write a module with compute(ctx) and list it here."""
from __future__ import annotations

from creed.metrics import aerobic, fitness, race, recovery, sleep, strain, weekly
from creed.metrics.base import MetricContext, MetricResult

ALL = (recovery, strain, fitness, sleep, weekly, aerobic, race)


def compute_all(ctx: MetricContext) -> dict[str, MetricResult]:
    results = (module.compute(ctx) for module in ALL)
    return {result.key: result for result in results}
