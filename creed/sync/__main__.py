"""Run a sync from the command line: `python -m creed.sync`."""
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
from creed.sync.engine import TOKEN_SECRET, run_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy Garmin data into the database.")
    parser.add_argument("--max-requests", type=int, default=150, help="stop after this many requests (default 150)")
    parser.add_argument("--time-budget", type=float, default=240, help="stop after this many seconds (default 240)")
    parser.add_argument("--delay", type=float, default=1.2, help="seconds between requests (default 1.2)")
    parser.add_argument("--trigger", default="manual", help="label recorded with this run")
    args = parser.parse_args(argv)

    config.load_dotenv()
    try:
        api_key = resolve_api_key()
    except AuthFailed as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 2

    with connect(config.database_url()) as conn:
        store = Store(conn)
        client = Client(
            os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL),
            api_key,
            delay=args.delay,
            max_requests=args.max_requests,
            deadline=time.monotonic() + args.time_budget,
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
