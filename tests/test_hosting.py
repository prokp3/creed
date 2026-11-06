"""The hosting files, which nothing else exercises until a real deploy."""
from __future__ import annotations

import json
import re
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
    # Only the app's own scripts. WebAssembly (the barcode reader) may compile, but no inline scripts or eval.
    assert script_rule.split() == ["script-src", "'self'", "'wasm-unsafe-eval'"]
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_the_only_outside_site_the_app_may_reach_is_the_map_provider():
    policy = security_headers()["Content-Security-Policy"]
    outside = {word for word in policy.replace(";", " ").split() if word.startswith("https:") or "." in word}
    assert outside == {"https://tiles.openfreemap.org"}
    script_rule = next(part for part in policy.split(";") if "script-src" in part)
    assert "openfreemap" not in script_rule


class TestScheduledSync:
    workflow = (ROOT / ".github/workflows/sync.yml").read_text(encoding="utf-8")

    def test_runs_every_30_minutes_off_the_hour(self):
        minutes = re.search(r'cron: "([\d,]+) \* \* \* \*"', self.workflow).group(1).split(",")
        assert len(minutes) == 2
        assert abs(int(minutes[1]) - int(minutes[0])) == 30
        assert "0" not in minutes

    def test_can_be_run_by_hand(self):
        assert "workflow_dispatch:" in self.workflow

    def test_has_no_permissions_and_uses_nobody_elses_code(self):
        assert "permissions: {}" in self.workflow
        assert "uses:" not in self.workflow

    def test_prints_only_the_outcome_because_the_log_is_public(self):
        run = self.workflow.split("run: |")[1]
        printed = [line for line in run.splitlines() if "echo" in line]
        assert not [line for line in printed if "CRON_SECRET" in line.replace("CREED_URL and CRON_SECRET", "")]
        for private in (".message", ".records", ".requests", "cat response", "--verbose", "set -x"):
            assert private not in run

    def test_a_failed_sync_fails_the_job_but_a_partial_one_does_not(self):
        assert re.search(r"ok\) ;;", self.workflow)
        assert re.search(r"partial\).*::warning::", self.workflow)
        assert re.search(r"\*\).*exit 1", self.workflow)

    def test_gives_up_before_the_job_limit_and_after_the_function_limit(self):
        curl_limit = int(re.search(r"--max-time (\d+)", self.workflow).group(1))
        job_limit = int(re.search(r"timeout-minutes: (\d+)", self.workflow).group(1))
        assert curl_limit < job_limit * 60
        assert curl_limit < ENTRY["maxDuration"]
        assert curl_limit > api_module.SYNC_TIME_BUDGET_SECONDS

    def test_vercels_daily_backup_is_allowed_on_the_free_plan(self):
        (job,) = CONFIG["crons"]
        assert job["path"] == "/api/cron/sync"
        minute, hour, *rest = job["schedule"].split()
        assert minute.isdigit() and hour.isdigit()
        assert rest == ["*", "*", "*"]

    def test_the_route_takes_vercels_get_and_the_workflows_post(self):
        route = next(r for r in api_module.app.routes if getattr(r, "path", "") == CONFIG["crons"][0]["path"])
        assert {"GET", "POST"} <= route.methods


def test_python_version_matches_what_was_tested():
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"


def test_only_the_camera_is_allowed_and_only_for_the_app_itself():
    policy = security_headers()["Permissions-Policy"]
    assert "camera=(self)" in policy
    assert "microphone=()" in policy and "geolocation=()" in policy
