"""What the routes share: a database connection for the request, and the session check."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

import psycopg
from fastapi import Depends, HTTPException, Request

from creed import auth, config
from creed.db import connect


def get_conn() -> Iterator[psycopg.Connection]:
    conn = connect(config.database_url())
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[psycopg.Connection, Depends(get_conn)]


def require_session(request: Request, conn: Conn) -> dict[str, Any]:
    session = auth.find_session(conn, request.cookies.get(auth.SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return session


Session = Annotated[dict[str, Any], Depends(require_session)]


def require_owner(session: Session) -> dict[str, Any]:
    """Garmin data, the dashboard built from it and the app's settings belong to the owner alone."""
    if not session["is_owner"]:
        raise HTTPException(status_code=403, detail="This account has no Garmin data here.")
    return session


OwnerSession = Annotated[dict[str, Any], Depends(require_owner)]
