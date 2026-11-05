from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest import mock

import pytest

from creed import config


def test_dotenv_loads_values_and_skips_comments_and_blanks(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# a comment\nDATABASE_URL='postgresql://x'\nGARMIN_PERSONAL_API_KEY=\n", encoding="utf-8")
    with mock.patch.dict(os.environ, {}, clear=True):
        config.load_dotenv(env_file)
        assert os.environ["DATABASE_URL"] == "postgresql://x"
        # A blank line in .env must not hide the key saved in the user's folder.
        assert "GARMIN_PERSONAL_API_KEY" not in os.environ


def test_real_environment_variables_win_over_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=from-file\n", encoding="utf-8")
    with mock.patch.dict(os.environ, {"DATABASE_URL": "from-env"}, clear=True):
        config.load_dotenv(env_file)
        assert os.environ["DATABASE_URL"] == "from-env"


def test_missing_dotenv_is_fine(tmp_path):
    config.load_dotenv(tmp_path / "nothing")


def test_missing_database_url_says_what_to_do():
    with mock.patch.dict(os.environ, {}, clear=True), pytest.raises(RuntimeError, match=".env.example"):
        config.database_url()


def test_today_is_the_date_in_india_not_utc():
    late_evening_utc = datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)
    with mock.patch.object(config, "datetime") as fake:
        fake.now.return_value = late_evening_utc
        assert config.local_today("Asia/Kolkata").isoformat() == "2026-11-06"
        assert config.local_today("UTC").isoformat() == "2026-11-05"
