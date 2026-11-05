#!/usr/bin/env python3
"""Run the API on this computer for development: `.venv/Scripts/python tools/dev_api.py`.

It listens on this computer only. It keeps a random token in .dev-token, which git ignores, and saves it as a
session lasting 24 hours. The web dev server sends that session for you, so you start signed in. Sign out in the
app to try the real sign-in screen; restarting this brings the session back.

The session is a normal row in whichever database DATABASE_URL points at, so keep .dev-token private.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / ".dev-token"
DEV_ORIGIN = "http://localhost:5173"


def main() -> None:
    sys.path.insert(0, str(ROOT))
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    os.environ["CREED_ORIGIN"] = DEV_ORIGIN

    import uvicorn

    from creed import auth, config
    from creed.db import connect

    config.load_dotenv()
    with connect(config.database_url()) as conn:
        try:
            auth.save_dev_session(conn, token)
        except psycopg.errors.UndefinedTable:
            sys.exit("The sign-in tables are missing. Run: .venv/Scripts/python -m creed.db.migrate")

    print(f"Open {DEV_ORIGIN} once the web dev server is running.")
    uvicorn.run("creed.api.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
