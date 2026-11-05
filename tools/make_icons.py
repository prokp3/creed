#!/usr/bin/env python3
"""Draw Creed's neutral app icon: an open white ring with a red dot, on near-black.

Standard library only. Run it again to regenerate web/public/icons. No third-party logo is used.
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "web" / "public" / "icons"
SIZES = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512, "icon-1024.png": 1024}

BACKGROUND = (8, 8, 10)
RING = (255, 255, 255)
DOT = (255, 59, 71)
# In fractions of the icon's width, all inside the safe zone of a maskable icon.
RADIUS = 0.255
THICKNESS = 0.085
GAP_DEGREES = 42
DOT_RADIUS = 0.058


def mix(under: tuple[int, int, int], over: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(a + (b - a) * amount) for a, b in zip(under, over))


def coverage(distance: float, pixel: float) -> float:
    """How much of a pixel lies inside a shape, from the signed distance to its edge."""
    return max(0.0, min(1.0, 0.5 - distance / pixel))


def draw(size: int) -> bytes:
    pixel = 1 / size
    rows = bytearray()
    gap = math.radians(GAP_DEGREES)
    cap_x, cap_y = RADIUS * math.cos(gap), RADIUS * math.sin(gap)
    for row in range(size):
        rows.append(0)  # PNG filter type: none.
        y = (row + 0.5) * pixel - 0.5
        for column in range(size):
            x = (column + 0.5) * pixel - 0.5
            angle = abs(math.atan2(y, x))
            if angle > gap:
                ring = abs(math.hypot(x, y) - RADIUS) - THICKNESS / 2
            else:
                # Inside the gap, distance is to the nearest rounded end of the ring.
                ring = math.hypot(x - cap_x, abs(y) - cap_y) - THICKNESS / 2
            dot = math.hypot(x - RADIUS, y) - DOT_RADIUS
            color = mix(BACKGROUND, RING, coverage(ring, pixel))
            color = mix(color, DOT, coverage(dot, pixel))
            rows.extend(color)
    return bytes(rows)


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(size: int) -> bytes:
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB with no alpha, as iOS prefers.
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(draw(size), 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        (OUTPUT / name).write_bytes(png(size))
        print(f"{name}: {size}x{size}")


if __name__ == "__main__":
    main()
