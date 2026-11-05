"""Turns a watch's GPS samples into a line for the map.

Nothing is filled in. Where the watch lost signal or paused, the line stops and starts again rather than drawing a
straight line across a stretch nobody recorded. Coordinates are [longitude, latitude], the order map libraries use.
"""
from __future__ import annotations

import math
from typing import Any

from creed.garmin.fit import TrackPoint

MAP_DISCIPLINES = {"run", "bike"}
INDOOR_TYPES = {"treadmill_running", "indoor_running", "indoor_cycling", "virtual_ride"}

EARTH_RADIUS_M = 6_371_000
MAX_GAP_SECONDS = 30  # Longer than this between samples means a pause or lost signal.
MAX_SPEED_MPS = 30.0  # 108 km/h. Faster than this between samples is a GPS jump, not movement.
MIN_STEP_METRES = 5.0  # Closer points add nothing you could see, and cost bytes on a phone.
MAX_POINTS = 2000
DECIMALS = 5  # About a metre.
NO_GPS = "This activity has no GPS recording."


def can_have_map(discipline: str | None, type_key: str | None) -> bool:
    return discipline in MAP_DISCIPLINES and type_key not in INDOOR_TYPES


def metres_between(a: TrackPoint, b: TrackPoint) -> float:
    """Great-circle distance, by the haversine formula."""
    lat_a, lat_b = math.radians(a.latitude), math.radians(b.latitude)
    d_lat = lat_b - lat_a
    d_lon = math.radians(b.longitude - a.longitude)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _is_possible(point: TrackPoint) -> bool:
    return abs(point.latitude) <= 90 and abs(point.longitude) <= 180


def _breaks(a: TrackPoint, b: TrackPoint) -> bool:
    seconds = b.timestamp - a.timestamp
    if seconds == 0:
        return False
    if seconds < 0 or seconds > MAX_GAP_SECONDS:
        return True
    return metres_between(a, b) / seconds > MAX_SPEED_MPS


def split_segments(points: list[TrackPoint]) -> list[list[TrackPoint]]:
    """Stretches of continuous recording. A lone point can't be drawn as a line, so it's left out."""
    segments: list[list[TrackPoint]] = []
    current: list[TrackPoint] = []
    for point in points:
        if not _is_possible(point):
            continue
        if current and _breaks(current[-1], point):
            segments.append(current)
            current = []
        current.append(point)
    segments.append(current)
    return [segment for segment in segments if len(segment) >= 2]


def _thin(segment: list[TrackPoint], step: float) -> list[TrackPoint]:
    kept = [segment[0]]
    for point in segment[1:-1]:
        if metres_between(kept[-1], point) >= step:
            kept.append(point)
    kept.append(segment[-1])
    return kept


def _coordinate(point: TrackPoint) -> list[float]:
    return [round(point.longitude, DECIMALS), round(point.latitude, DECIMALS)]


def build_route(points: list[TrackPoint]) -> dict[str, Any]:
    segments = split_segments(points)
    if not segments:
        return {"segments": [], "reason": NO_GPS}
    total = sum(metres_between(a, b) for segment in segments for a, b in zip(segment, segment[1:]))
    step = max(MIN_STEP_METRES, total / MAX_POINTS)
    thinned = [_thin(segment, step) for segment in segments]
    everything = [point for segment in thinned for point in segment]
    longitudes = [p.longitude for p in everything]
    latitudes = [p.latitude for p in everything]
    return {
        "segments": [[_coordinate(p) for p in segment] for segment in thinned],
        "bounds": [
            [round(min(longitudes), DECIMALS), round(min(latitudes), DECIMALS)],
            [round(max(longitudes), DECIMALS), round(max(latitudes), DECIMALS)],
        ],
        "start": _coordinate(thinned[0][0]),
        "finish": _coordinate(thinned[-1][-1]),
        "gaps": len(thinned) - 1,
    }
