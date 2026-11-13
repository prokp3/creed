"""Check that your intervals.icu key works, and see what Creed would get from it, before you sync.

Reads INTERVALS_API_KEY (and INTERVALS_ATHLETE_ID if set) from the environment or .env. Prints only counts and which
fields are present for the last 30 days: never the key, names, notes or locations. Makes three requests.

    python tools/intervals_check.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from creed import config  # noqa: E402
from creed.garmin.api import ApiError  # noqa: E402
from creed.garmin.client import ApiStopped, AuthFailed  # noqa: E402
from creed.intervals import api  # noqa: E402
from creed.intervals import normalize as inorm  # noqa: E402
from creed.intervals.client import BASE_URL_ENV_VAR, DEFAULT_BASE_URL, Client  # noqa: E402

DAYS = 30
WELLNESS_FIELDS = ("restingHR", "hrv", "sleepSecs", "sleepScore", "steps", "spO2", "respiration")


def main() -> int:
    config.load_dotenv()
    try:
        client = Client(os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL), api.resolve_api_key(), max_requests=3)
        athlete = api.athlete_id()
        today = config.local_today()
        start = today - timedelta(days=DAYS - 1)
        wellness = api.wellness(client, athlete, start, today)
        activities = api.activities(client, athlete, start, today)
    except AuthFailed as exc:
        print(f"Key problem: {exc}")
        return 2
    except (ApiError, ApiStopped) as exc:
        print(f"intervals.icu didn't answer as expected: {exc}")
        return 1

    print(f"The key works. Last {DAYS} days:")
    print(f"  Wellness: {len(wellness)} days")
    for field in WELLNESS_FIELDS:
        present = sum(1 for row in wellness if row.get(field) not in (None, 0))
        print(f"    {field:<12} {present:>3} days")
    sources = Counter(str(row.get("source") or "unknown") for row in activities)
    readable = 0
    for row in activities:
        try:
            inorm.activity(row)
            readable += 1
        except inorm.BadRecord:
            pass
    print(f"  Activities: {len(activities)}, of which Creed can read {readable}")
    for source, n in sources.most_common():
        print(f"    from {source}: {n}")
    if sources.get("STRAVA"):
        print("  Activities that came from Strava can't be shared with other apps. Connect your watch to intervals.icu "
              "directly to include them.")
    if sources.get("GARMIN_CONNECT"):
        print("  Garmin is limiting what intervals.icu can share. If Garmin activities stop arriving, set "
              "CREED_DATA_SOURCE=garmin and use a Garmin key instead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
