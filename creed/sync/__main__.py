"""Run a sync from the command line: `python -m creed.sync`. It syncs whichever source CREED_DATA_SOURCE names."""
from __future__ import annotations

import argparse
import os
import sys
import time

from creed import config
from creed.db import connect
from creed.db.store import Store
from creed.garmin.client import BASE_URL_ENV_VAR, DEFAULT_BASE_URL, AuthFailed, Client
from creed.garmin.keys import resolve_api_key
from creed.intervals import api as intervals_api
from creed.intervals import client as intervals_client
from creed.sync.engine import TOKEN_SECRET, SyncResult, run_sync
from creed.sync.intervals import run_intervals_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy Garmin or intervals.icu data into the database.")
    parser.add_argument("--max-requests", type=int, default=150, help="stop after this many requests (default 150)")
    parser.add_argument("--time-budget", type=float, default=240, help="stop after this many seconds (default 240)")
    parser.add_argument("--delay", type=float, default=None,
                        help="seconds between requests (default 1.2 for Garmin, 0.25 for intervals.icu)")
    parser.add_argument("--trigger", default="manual", help="label recorded with this run")
    args = parser.parse_args(argv)

    config.load_dotenv()
    intervals = config.data_source() == config.INTERVALS
    try:
        if intervals:
            api_key, athlete = intervals_api.resolve_api_key(), intervals_api.athlete_id()
        else:
            api_key, athlete = resolve_api_key(), ""
    except AuthFailed as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 2

    deadline = time.monotonic() + args.time_budget
    with connect(config.database_url()) as conn:
        store = Store(conn)
        result: SyncResult
        if intervals:
            client = intervals_client.Client(
                os.environ.get(intervals_client.BASE_URL_ENV_VAR, intervals_client.DEFAULT_BASE_URL), api_key,
                delay=0.25 if args.delay is None else args.delay, max_requests=args.max_requests, deadline=deadline,
            )
            result = run_intervals_sync(store, client, athlete=athlete, today=config.local_today(),
                                        trigger=args.trigger)
        else:
            client = Client(
                os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL),
                api_key,
                delay=1.2 if args.delay is None else args.delay,
                max_requests=args.max_requests,
                deadline=deadline,
                token=store.get_secret(TOKEN_SECRET),
                on_token=lambda token, expires: store.set_secret(TOKEN_SECRET, token, expires),
            )
            result = run_sync(store, client, today=config.local_today(), trigger=args.trigger)

    print(f"Status: {result.status}. {result.requests} requests, {result.records} records saved.")
    if result.message:
        print(result.message)
    for error in result.errors:
        print(f"  {error['step']}: {error['message']}")
    if result.backfill_pending:
        print("History is still being copied. Run the sync again to continue.")
    return 1 if result.status in ("auth_failed", "failed") else 0


if __name__ == "__main__":
    sys.exit(main())
