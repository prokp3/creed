"""A real Postgres for tests, so they exercise the same SQL that runs on Supabase."""
from __future__ import annotations

import pytest

pgserver = pytest.importorskip("pgserver")

from creed.db import connect  # noqa: E402
from creed.db.migrate import migrate  # noqa: E402
from creed.db.store import Store  # noqa: E402


@pytest.fixture(scope="session")
def database_url(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("pg"))
    yield server.get_uri()
    server.cleanup()


@pytest.fixture
def conn(database_url):
    connection = connect(database_url)
    connection.execute("drop schema public cascade")
    connection.execute("create schema public")
    connection.commit()
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def store(conn):
    migrate(conn)
    return Store(conn)
