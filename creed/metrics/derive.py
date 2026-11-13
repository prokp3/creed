"""Numbers worked out once from an activity's samples, so FIT files aren't re-read on every request.

Heart-rate time is stored as seconds per bpm, so load can be recalculated when max or resting
HR changes without opening the file again.

Aerobic efficiency follows Joe Friel's Efficiency Factor (speed over heart rate) and aerobic
decoupling (Pa:HR), as described in "The Triathlete's Training Bible" and by TrainingPeaks.
"""
from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from creed.garmin.fit import Sample

# A gap longer than this between samples is a pause, not training time.
MAX_SAMPLE_GAP_SECONDS = 60
WARMUP_SECONDS = 600
MIN_STEADY_SECONDS = 1200
# Steadiness is judged mainly on 5-minute averages, because second-by-second wrist GPS is noisy: a
# 15% limit on raw speed failed all but one real run. Short intervals can average out over 5 minutes,
# so raw speed gets a wider limit that GPS noise alone rarely reaches. These limits are this project's
# choices and aren't published values.
MAX_SPEED_CV_5_MIN = 0.15
MAX_SPEED_CV_RAW = 0.35
MIN_HR_COVERAGE = 0.9
MIN_MOVING_SPEED_MPS = 1.0
STEADY_DISCIPLINES = {"run"}
# Treadmill speed comes from the wrist and isn't reliable enough to compare.
EXCLUDED_TYPES = {"treadmill_running", "indoor_running", "virtual_run"}


@dataclass
class Derived:
    samples: int = 0
    hr_coverage: float | None = None
    hr_seconds: dict[int, float] = field(default_factory=dict)
    steady: bool = False
    efficiency: float | None = None
    decoupling_pct: float | None = None
    steady_speed_mps: float | None = None
    steady_hr: float | None = None


def hr_seconds(samples: Sequence[Sample]) -> dict[int, float]:
    """Seconds at each heart rate. Each gap belongs to the sample that starts it. Pauses don't count."""
    totals: dict[int, float] = {}
    for current, following in zip(samples, samples[1:]):
        gap = following.timestamp - current.timestamp
        if current.heart_rate is None or gap <= 0 or gap > MAX_SAMPLE_GAP_SECONDS:
            continue
        totals[current.heart_rate] = totals.get(current.heart_rate, 0.0) + gap
    return totals


def _efficiency(samples: Sequence[Sample]) -> tuple[float, float, float] | None:
    """Metres per minute per heartbeat, weighted by time, with the average speed and heart rate."""
    seconds = distance = beats = 0.0
    for current, following in zip(samples, samples[1:]):
        gap = following.timestamp - current.timestamp
        if gap <= 0 or gap > MAX_SAMPLE_GAP_SECONDS:
            continue
        if current.heart_rate is None or current.speed_mps is None:
            continue
        seconds += gap
        distance += current.speed_mps * gap
        beats += current.heart_rate * gap
    if not seconds or not beats:
        return None
    speed = distance / seconds
    hr = beats / seconds
    return speed * 60 / hr, speed, hr


def averaged_speed_cv(samples: Sequence[Sample], bin_seconds: int) -> float | None:
    """How much speed varies between time blocks: standard deviation over mean."""
    blocks: dict[int, list[float]] = {}
    for s in samples:
        if s.speed_mps is not None:
            blocks.setdefault(s.timestamp // bin_seconds, []).append(s.speed_mps)
    if len(blocks) < 2:
        return None
    means = [statistics.fmean(block) for block in blocks.values()]
    return statistics.pstdev(means) / statistics.fmean(means)


def derive(samples: Sequence[Sample], discipline: str, type_key: str | None = None) -> Derived:
    result = Derived(samples=len(samples))
    if not samples:
        return result
    result.hr_coverage = sum(1 for s in samples if s.heart_rate is not None) / len(samples)
    result.hr_seconds = hr_seconds(samples)

    if discipline not in STEADY_DISCIPLINES or type_key in EXCLUDED_TYPES:
        return result
    if result.hr_coverage < MIN_HR_COVERAGE:
        return result
    start = samples[0].timestamp + WARMUP_SECONDS
    moving = [s for s in samples
              if s.timestamp >= start and s.heart_rate is not None
              and s.speed_mps is not None and s.speed_mps >= MIN_MOVING_SPEED_MPS]
    if len(moving) < 2 or moving[-1].timestamp - moving[0].timestamp < MIN_STEADY_SECONDS:
        return result
    five_minute = averaged_speed_cv(moving, 300)
    speeds = [s.speed_mps for s in moving]
    if five_minute is None or five_minute > MAX_SPEED_CV_5_MIN:
        return result
    if statistics.pstdev(speeds) / statistics.fmean(speeds) > MAX_SPEED_CV_RAW:
        return result

    middle = moving[0].timestamp + (moving[-1].timestamp - moving[0].timestamp) / 2
    whole = _efficiency(moving)
    first = _efficiency([s for s in moving if s.timestamp <= middle])
    second = _efficiency([s for s in moving if s.timestamp > middle])
    if not whole or not first or not second:
        return result
    result.steady = True
    result.efficiency, result.steady_speed_mps, result.steady_hr = whole
    result.decoupling_pct = (first[0] - second[0]) / first[0] * 100
    return result
