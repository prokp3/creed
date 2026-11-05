"""A small FIT reader: structure and field coverage only, field values are not kept.

Used to check what a file contains and to flag sensor dropouts. Bad input yields
parse_error, never a crash. Files are read in memory and never extracted to disk.
"""
from __future__ import annotations

import io
import statistics
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

MAX_FIT_BYTES = 64 * 1024 * 1024

FIT_BASE_SIZE = {0: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 1, 8: 4, 9: 8, 10: 1, 11: 2, 12: 4, 13: 1, 14: 8, 15: 8, 16: 8}
FIT_INVALID = {
    0: 0xFF, 1: 0x7F, 2: 0xFF, 3: 0x7FFF, 4: 0xFFFF, 5: 0x7FFFFFFF, 6: 0xFFFFFFFF, 7: 0x00,
    8: 0xFFFFFFFF, 9: 0xFFFFFFFFFFFFFFFF, 10: 0x00, 11: 0x0000, 12: 0x00000000, 13: 0xFF,
    14: 0x7FFFFFFFFFFFFFFF, 15: 0xFFFFFFFFFFFFFFFF, 16: 0x0000000000000000,
}
FIT_MESSAGES = {
    0: "file_id", 2: "device_settings", 3: "user_profile", 7: "zones_target", 8: "hr_zone", 9: "power_zone",
    12: "sport", 18: "session", 19: "lap", 20: "record", 21: "event", 23: "device_info", 34: "activity",
    35: "software", 49: "file_creator", 78: "hrv", 101: "length", 132: "hr", 160: "gps_metadata",
    206: "field_description", 207: "developer_data_id", 216: "time_in_zone", 290: "beat_intervals",
    297: "respiration_rate", 312: "split", 313: "split_summary",
}
FIT_RECORD_FIELDS = {
    0: "position_lat", 1: "position_long", 2: "altitude", 3: "heart_rate", 4: "cadence", 5: "distance",
    6: "speed", 7: "power", 13: "temperature", 53: "fractional_cadence", 73: "enhanced_speed",
    78: "enhanced_altitude", 253: "timestamp",
}
FIT_SESSION_FIELDS = {
    5: "sport", 6: "sub_sport", 7: "total_elapsed_time", 8: "total_timer_time", 9: "total_distance",
    16: "avg_heart_rate", 17: "max_heart_rate", 20: "avg_power", 21: "max_power", 24: "total_training_effect",
    34: "normalized_power", 35: "training_stress_score", 36: "intensity_factor", 44: "pool_length",
    137: "total_anaerobic_training_effect",
}
FIT_MSG_RECORD, FIT_MSG_SESSION, FIT_MSG_PHYSIO = 20, 18, 140


def read_fit(data: bytes) -> dict[str, Any]:
    """Count messages and valid fields in a FIT file."""
    messages: Counter = Counter()
    valid_fields: dict[int, Counter] = defaultdict(Counter)
    record_times: list[int] = []
    result: dict[str, Any] = {"parse_error": None, "truncated": False, "fit_files": 0}
    pos = 0
    try:
        while pos + 12 <= len(data):
            header_size = data[pos]
            if header_size not in (12, 14) or data[pos + 8 : pos + 12] != b".FIT":
                if result["fit_files"] == 0:
                    raise ValueError("no .FIT signature")
                break
            data_size = int.from_bytes(data[pos + 4 : pos + 8], "little")
            start = pos + header_size
            end = start + data_size
            if end > len(data):
                result["truncated"] = True
                end = len(data)
            _read_fit_records(data, start, end, messages, valid_fields, record_times)
            result["fit_files"] += 1
            pos = end + 2
        if result["fit_files"] == 0:
            raise ValueError("file too short")
    except (IndexError, ValueError, KeyError) as exc:
        result["parse_error"] = f"{type(exc).__name__}: {exc}"

    record_count = messages.get(FIT_MSG_RECORD, 0)
    deltas = [b - a for a, b in zip(record_times, record_times[1:]) if b >= a]
    result.update(
        messages={FIT_MESSAGES.get(num, f"unknown_{num}"): n for num, n in sorted(messages.items())},
        undocumented_messages=sorted(num for num in messages if num not in FIT_MESSAGES),
        record_count=record_count,
        record_median_interval_s=statistics.median(deltas) if deltas else None,
        record_field_pct={
            FIT_RECORD_FIELDS.get(num, f"field_{num}"): round(100 * n / record_count, 1)
            for num, n in sorted(valid_fields[FIT_MSG_RECORD].items())
        }
        if record_count
        else {},
        session_fields=sorted(
            FIT_SESSION_FIELDS.get(num, f"field_{num}") for num in valid_fields[FIT_MSG_SESSION]
        ),
        message_140_field_numbers=sorted(valid_fields[FIT_MSG_PHYSIO]),
    )
    return result


def _read_fit_records(
    data: bytes,
    start: int,
    end: int,
    messages: Counter,
    valid_fields: dict[int, Counter],
    record_times: list[int],
) -> None:
    definitions: dict[int, tuple[int, str, list[tuple[int, int, int]], int]] = {}
    last_ts: int | None = None
    p = start
    while p < end:
        header = data[p]
        p += 1
        compressed_offset: int | None = None
        if header & 0x80:
            local = (header >> 5) & 0x03
            compressed_offset = header & 0x1F
        elif header & 0x40:
            local = header & 0x0F
            has_dev = bool(header & 0x20)
            byteorder = "big" if data[p + 1] else "little"
            global_num = int.from_bytes(data[p + 2 : p + 4], byteorder)
            count = data[p + 4]
            p += 5
            fields = [(data[p + 3 * i], data[p + 3 * i + 1], data[p + 3 * i + 2]) for i in range(count)]
            p += 3 * count
            dev_size = 0
            if has_dev:
                dev_count = data[p]
                p += 1
                dev_size = sum(data[p + 3 * i + 1] for i in range(dev_count))
                p += 3 * dev_count
            definitions[local] = (global_num, byteorder, fields, dev_size)
            continue
        else:
            local = header & 0x0F
        if local not in definitions:
            raise ValueError("data message before its definition")
        global_num, byteorder, fields, dev_size = definitions[local]
        if p + sum(f[1] for f in fields) + dev_size > end:
            return  # Trailing partial message in a truncated file.
        messages[global_num] += 1
        ts: int | None = None
        for num, size, base in fields:
            raw = data[p : p + size]
            p += size
            if _fit_field_valid(raw, base, byteorder):
                valid_fields[global_num][num] += 1
                if num == 253 and size == 4:
                    ts = int.from_bytes(raw, byteorder)
        p += dev_size
        if ts is None and compressed_offset is not None and last_ts is not None:
            ts = (last_ts & ~0x1F) | compressed_offset
            if compressed_offset < (last_ts & 0x1F):
                ts += 0x20
        if ts is not None:
            last_ts = ts
            if global_num == FIT_MSG_RECORD:
                record_times.append(ts)


def _fit_field_valid(raw: bytes, base: int, byteorder: str) -> bool:
    number = base & 0x1F
    element = FIT_BASE_SIZE.get(number)
    if element is None or not raw:
        return bool(raw)
    invalid = FIT_INVALID[number]
    if number == 7:
        return any(raw)
    for i in range(0, len(raw) - element + 1, element):
        if int.from_bytes(raw[i : i + element], byteorder) != invalid:
            return True
    return False


def read_activity_zip(content: bytes) -> dict[str, Any]:
    """Garmin's download endpoint returns a ZIP. Read it in memory and never extract to disk."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        # Some originals may not be zipped: look at the bytes directly.
        return {"zip": False, "bytes": len(content), **read_fit(content)}
    with archive:
        names = archive.infolist()
        fits = [i for i in names if i.filename.lower().endswith(".fit") and i.file_size <= MAX_FIT_BYTES]
        extensions = sorted({Path(i.filename).suffix.lower() for i in names})
        if not fits:
            return {"zip": True, "bytes": len(content), "entries": len(names), "extensions": extensions,
                    "parse_error": "no .fit entry in the archive"}
        fit = max(fits, key=lambda i: i.file_size)
        return {"zip": True, "bytes": len(content), "entries": len(names), "extensions": extensions,
                **read_fit(archive.read(fit))}
