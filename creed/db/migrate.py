"""Apply SQL migrations in order. Safe to run repeatedly: `python -m creed.db.migrate`."""
from __future__ import annotations

from pathlib import Path

import psycopg

from creed import config
from creed.db import connect

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply each migration not yet recorded, one transaction each. Returns those applied."""
    conn.execute(
        "create table if not exists schema_migration ("
        "version text primary key, applied_at timestamptz not null default now())"
    )
    conn.execute("alter table schema_migration enable row level security")
    conn.commit()
    done = {row["version"] for row in conn.execute("select version from schema_migration").fetchall()}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into schema_migration (version) values (%s)", (path.name,))
        applied.append(path.name)
    conn.commit()
    return applied


def main() -> None:
    config.load_dotenv()
    with connect(config.database_url()) as conn:
        applied = migrate(conn)
    print("Applied: " + ", ".join(applied) if applied else "Already up to date.")


if __name__ == "__main__":
    main()
