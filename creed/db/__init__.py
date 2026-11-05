"""Postgres access. Only server code may import this package."""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


def connect(url: str) -> psycopg.Connection:
    # prepare_threshold=None because Supabase's transaction pooler can't keep prepared statements.
    return psycopg.connect(url, row_factory=dict_row, prepare_threshold=None, connect_timeout=15)
