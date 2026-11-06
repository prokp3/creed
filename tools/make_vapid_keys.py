#!/usr/bin/env python3
"""Make the key pair that signs this deployment's notifications: `.venv/Scripts/python tools/make_vapid_keys.py`.

It adds PUSH_VAPID_PRIVATE_KEY and PUSH_VAPID_PUBLIC_KEY to .env (which git ignores) and prints nothing secret.
Then copy both into Vercel's Environment Variables and redeploy. Make them once: new keys stop every phone that
already turned notifications on from getting them until it turns them on again.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from creed.push import PRIVATE_KEY_ENV, PUBLIC_KEY_ENV, generate_vapid_keys


def main() -> None:
    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    names = {line.split("=", 1)[0].strip() for line in text.splitlines() if "=" in line}
    if PRIVATE_KEY_ENV in names or PUBLIC_KEY_ENV in names:
        sys.exit(f"{env.name} already has notification keys. Remove both lines first if you really want new ones.")
    private, public = generate_vapid_keys()
    with env.open("a", encoding="utf-8") as handle:
        if text and not text.endswith("\n"):
            handle.write("\n")
        handle.write(f"{PRIVATE_KEY_ENV}={private}\n{PUBLIC_KEY_ENV}={public}\n")
    print(f"Added {PRIVATE_KEY_ENV} and {PUBLIC_KEY_ENV} to {env}. Copy both into Vercel, then redeploy.")


if __name__ == "__main__":
    main()
