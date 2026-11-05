"""The hosting files, which nothing else exercises until a real deploy."""
from __future__ import annotations

import json
from pathlib import Path

from creed.api import app as api_module

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
ENTRY = CONFIG["functions"]["api/index.py"]


def security_headers() -> dict[str, str]:
    rule = next(r for r in CONFIG["headers"] if r["source"] == "/(.*)")
    return {h["key"]: h["value"] for h in rule["headers"]}


def test_the_entry_point_serves_the_real_app():
    from api.index import app

    assert app is api_module.app


def test_every_route_lives_under_the_path_sent_to_python():
    assert CONFIG["rewrites"] == [{"source": "/api/(.*)", "destination": "/api/index"}]
    paths = [route.path for route in api_module.app.routes if hasattr(route, "path")]
    assert paths
    assert all(path.startswith("/api/") for path in paths), paths


def test_the_function_can_outlast_the_sync():
    assert ENTRY["maxDuration"] > api_module.SYNC_TIME_BUDGET_SECONDS
    assert ENTRY["maxDuration"] <= 300  # The most the free plan allows.


def test_the_screens_and_tests_stay_out_of_the_function():
    for folder in ("web/**", "tests/**", "tools/**"):
        assert folder in ENTRY["excludeFiles"]


def test_the_screens_come_from_the_web_build():
    assert CONFIG["outputDirectory"] == "web/dist"
    assert (ROOT / "web/package-lock.json").exists()  # npm ci needs it.


def test_no_settings_or_secrets_live_in_the_config():
    assert "env" not in CONFIG
    assert "build" not in CONFIG


def test_other_sites_cannot_frame_the_app_or_inject_scripts():
    headers = security_headers()
    policy = headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in policy
    assert "script-src 'self'" in policy
    script_rule = next(part for part in policy.split(";") if "script-src" in part)
    assert "unsafe" not in script_rule
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_python_version_matches_what_was_tested():
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"
