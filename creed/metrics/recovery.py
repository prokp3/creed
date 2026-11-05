"""Recovery: how last night compares with your own recent baseline.

    composite = 0.5 x HRV z + 0.2 x resting HR z + 0.1 x respiration z + 0.2 x sleep z
    score = 50 + 25 x composite, limited to 0-100

HRV is ln(Garmin's overnight average), compared with your previous 28 days. Resting HR and
respiration are flipped so that lower than usual counts as better.

Basis: Plews DJ et al. (2013), "Training adaptation and heart rate variability in elite endurance
athletes". Sports Med 43:773-781. Buchheit M (2014), "Monitoring training status with HR measures".
Front Physiol 5:73.

What is and isn't established:
  * Comparing ln-transformed HRV with a rolling personal baseline is the published approach.
  * The weights are a judgment call: HRV leads because it has the strongest evidence. I don't know of
    a validated formula for combining these inputs, and the UI says so.
  * Plews and Buchheit used rMSSD. Garmin doesn't publish which measure its overnight value is, and the
    FIT files carry no beat-to-beat data to check it, so this is ln(Garmin overnight HRV), not ln(rMSSD).
  * Whoop's algorithm is proprietary and isn't replicated. This score doesn't try to match Whoop or Garmin.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from creed.metrics import sleep as sleep_metric
from creed.metrics.base import COMPUTED, INSUFFICIENT, OK, MetricContext, MetricResult, Why

BASELINE_DAYS = 28
MIN_BASELINE_NIGHTS = 14
FULL_BASELINE_NIGHTS = 21
WEIGHTS = {"hrv": 0.5, "resting_hr": 0.2, "respiration": 0.1, "sleep": 0.2}
# A 15% sleep shortfall counts like one standard deviation. Long sleep helps less than short sleep hurts.
SLEEP_SCALE = 0.15
SLEEP_Z_LIMITS = (-2.0, 1.0)
MIN_BASELINE_VALUES = 7

WHY = Why(
    formula="50 + 25 x (0.5 HRV z + 0.2 resting HR z + 0.1 respiration z + 0.2 sleep z). HRV z is ln(overnight HRV) "
            "against your own baseline.",
    inputs="Garmin's overnight HRV, resting HR and sleep respiration, plus sleep vs need.",
    window="The previous 28 days, with at least 14 nights recorded.",
    citation="Plews et al. 2013, Buchheit 2014 (ln-HRV against a rolling baseline). The weights are a judgment call, "
             "not a validated formula.",
    note="Garmin doesn't publish which HRV measure it reports, so this isn't labelled rMSSD. Whoop's algorithm is "
         "proprietary and isn't replicated.",
)


def z_score(value: float, baseline: list[float]) -> float | None:
    if len(baseline) < 2:
        return None
    spread = statistics.stdev(baseline)
    return None if spread == 0 else (value - statistics.fmean(baseline)) / spread


def sleep_z(performance: float) -> float:
    low, high = SLEEP_Z_LIMITS
    return max(low, min(high, (performance - 1) / SLEEP_SCALE))


def composite_score(components: dict[str, float]) -> float:
    """Combine what's available. Weights are rescaled over those inputs. Nothing is filled in."""
    total = sum(WEIGHTS[name] for name in components)
    composite = sum(WEIGHTS[name] * z for name, z in components.items()) / total
    return max(0.0, min(100.0, 50 + 25 * composite))


def _baseline(values: dict[date, float], day: date) -> list[float]:
    return [v for d, v in values.items() if timedelta(0) < day - d <= timedelta(days=BASELINE_DAYS)]


def score_on(ctx: MetricContext, day: date) -> tuple[float | None, dict]:
    """The score for one morning, or None with the reason. Used for today and for backtests."""
    respiration = {n.day: n.respiration for n in ctx.sleep if n.respiration is not None and not n.flagged}
    tonight = ctx.hrv.get(day)
    hrv_base = _baseline(ctx.hrv, day)
    info: dict = {"baseline_nights": len(hrv_base), "nights_needed": MIN_BASELINE_NIGHTS}
    if tonight is None:
        return None, {**info, "reason": "No overnight HRV for last night."}
    if len(hrv_base) < MIN_BASELINE_NIGHTS:
        return None, {**info, "reason": f"Needs {MIN_BASELINE_NIGHTS} nights of HRV in the last {BASELINE_DAYS} days. "
                                        f"You have {len(hrv_base)}."}
    hrv_z = z_score(math.log(tonight), [math.log(v) for v in hrv_base])
    if hrv_z is None:
        return None, {**info, "reason": "HRV has been identical every night, so there's no spread to compare with."}

    components = {"hrv": hrv_z}
    inputs = {"hrv": {"value": tonight, "z": hrv_z}}
    rhr = ctx.resting_hr.get(day)
    rhr_base = _baseline(ctx.resting_hr, day)
    if rhr is not None and len(rhr_base) >= MIN_BASELINE_VALUES:
        z = z_score(rhr, rhr_base)
        if z is not None:
            components["resting_hr"] = -z
            inputs["resting_hr"] = {"value": rhr, "difference": rhr - statistics.fmean(rhr_base), "z": -z}
    resp = respiration.get(day)
    resp_base = _baseline(respiration, day)
    if resp is not None and len(resp_base) >= MIN_BASELINE_VALUES:
        z = z_score(resp, resp_base)
        if z is not None:
            components["respiration"] = -z
            inputs["respiration"] = {"value": resp, "difference": resp - statistics.fmean(resp_base), "z": -z}
    performance = sleep_metric.performance_on(ctx, day)
    if performance is not None:
        components["sleep"] = sleep_z(performance)
        inputs["sleep"] = {"performance": performance, "z": components["sleep"]}

    return composite_score(components), {**info, "inputs": inputs, "used": sorted(components)}


def compute(ctx: MetricContext) -> MetricResult:
    base = {"key": "recovery", "title": "Recovery", "tag": COMPUTED, "unit": "of 100", "why": WHY}
    score, info = score_on(ctx, ctx.today)
    if score is None:
        return MetricResult(**base, state=INSUFFICIENT, value=None, confidence="none",
                            reason=info["reason"], details=info)
    if len(info["used"]) == len(WEIGHTS) and info["baseline_nights"] >= FULL_BASELINE_NIGHTS:
        confidence = "high"
    elif len(info["used"]) >= 3:
        confidence = "medium"
    else:
        confidence = "low"
    return MetricResult(**base, state=OK, value=score, confidence=confidence, details=info)
