"""Settings read from the environment, with an optional local .env file."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Kolkata"


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=value lines from .env. Real environment variables win."""
    target = path or Path(__file__).resolve().parent.parent / ".env"
    if not target.exists():
        return
    for line in target.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if value:
            os.environ.setdefault(name.strip(), value)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return url


# Where the training data comes from. Garmin is read directly. Everything else (COROS, Polar, Suunto, Wahoo and more)
# arrives through intervals.icu, which those watches already sync to.
DATA_SOURCE_ENV_VAR = "CREED_DATA_SOURCE"
GARMIN = "garmin"
INTERVALS = "intervals"
SOURCE_LABELS = {GARMIN: "Garmin", INTERVALS: "intervals.icu"}


def data_source() -> str:
    """garmin unless CREED_DATA_SOURCE says intervals. A typo stops the app rather than quietly syncing the wrong place."""
    value = os.environ.get(DATA_SOURCE_ENV_VAR, "").strip().lower() or GARMIN
    if value not in SOURCE_LABELS:
        raise RuntimeError(f"{DATA_SOURCE_ENV_VAR} must be garmin or intervals, not {value!r}.")
    return value


def source_label() -> str:
    """How screens name the data source, such as on the tag beside a value: Garmin or intervals.icu."""
    return SOURCE_LABELS[data_source()]


def local_today(tz_name: str | None = None) -> date:
    tz = ZoneInfo(tz_name or os.environ.get("CREED_TIMEZONE") or DEFAULT_TIMEZONE)
    return datetime.now(timezone.utc).astimezone(tz).date()
