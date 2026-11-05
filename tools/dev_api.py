#!/usr/bin/env python3
"""Run the API on this computer for development: `.venv/Scripts/python tools/dev_api.py`.

It listens on this computer only. It creates a random token in .dev-token, which git ignores, and the web
dev server adds that token to API calls. Passkey login replaces this before anything is deployed.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / ".dev-token"


def main() -> None:
    sys.path.insert(0, str(ROOT))
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    os.environ["CREED_API_TOKEN"] = TOKEN_FILE.read_text(encoding="utf-8").strip()

    import uvicorn

    uvicorn.run("creed.api.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
