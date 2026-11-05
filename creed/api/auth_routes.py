"""The sign-in routes. Registration is closed unless the setup secret or a just-used recovery code opens it."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from creed import auth
from creed.api.deps import Conn, Session

router = APIRouter(prefix="/api/auth")


async def _body(request: Request) -> dict[str, Any]:
    """Read by hand because the framework's own 422 errors repeat the input, which here could be a secret."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Send a JSON object.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Send a JSON object.")
    return body


def _begin_session(request: Request, response: Response, conn: Conn, kind: str = "passkey") -> None:
    auth.end_session(conn, request.cookies.get(auth.SESSION_COOKIE))
    token = auth.start_session(conn, kind)
    conn.commit()
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.COOKIE_MAX_AGE_SECONDS,
        path="/",
        secure=auth.relying_party().secure,
        httponly=True,
        samesite="strict",
    )


@router.get("/status")
def status(request: Request, conn: Conn) -> dict[str, Any]:
    """All the app needs to pick a screen. It says nothing about anything but sign-in."""
    session = auth.find_session(conn, request.cookies.get(auth.SESSION_COOKIE))
    return {
        "signed_in": session is not None,
        "session_kind": session["kind"] if session else None,
        "has_passkey": auth.has_passkey(conn),
    }


@router.post("/register/options")
async def register_options(request: Request, conn: Conn) -> dict[str, Any]:
    body = await _body(request)
    session = auth.find_session(conn, request.cookies.get(auth.SESSION_COOKIE))
    if session is None or session["kind"] != "recovery":
        auth.check_setup_secret(body.get("setup_secret"))
    options = auth.registration_options(conn)
    conn.commit()
    return options


@router.post("/register/verify")
async def register_verify(request: Request, response: Response, conn: Conn) -> dict[str, Any]:
    body = await _body(request)
    auth.finish_registration(conn, body.get("credential"), body.get("label"))
    code = None if auth.has_recovery_code(conn) else auth.new_recovery_code(conn)
    _begin_session(request, response, conn)
    return {"recovery_code": code}


@router.post("/sign-in/options")
def sign_in_options(conn: Conn) -> dict[str, Any]:
    options = auth.sign_in_options(conn)
    conn.commit()
    return options


@router.post("/sign-in/verify")
async def sign_in_verify(request: Request, response: Response, conn: Conn) -> dict[str, Any]:
    body = await _body(request)
    auth.check_passkey(conn, body.get("credential"))
    _begin_session(request, response, conn)
    return {"signed_in": True}


@router.post("/recover")
async def recover(request: Request, response: Response, conn: Conn) -> dict[str, Any]:
    """The code works once. Every other session ends, and a new code replaces it straight away."""
    body = await _body(request)
    if not auth.use_recovery_code(conn, body.get("code")):
        raise auth.Refused("That recovery code isn't right, or it's already been used.")
    auth.end_all_sessions(conn)
    code = auth.new_recovery_code(conn)
    _begin_session(request, response, conn, kind="recovery")
    return {"recovery_code": code}


@router.post("/sign-out")
def sign_out(request: Request, response: Response, conn: Conn) -> dict[str, Any]:
    auth.end_session(conn, request.cookies.get(auth.SESSION_COOKIE))
    conn.commit()
    response.delete_cookie(auth.SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return {"signed_in": False}


@router.get("/details")
def details(_: Session, conn: Conn) -> dict[str, Any]:
    return {"passkeys": auth.list_passkeys(conn), "recovery_code_created_at": auth.recovery_code_created(conn)}


@router.delete("/passkeys/{encoded_id}")
def remove_passkey(encoded_id: str, _: Session, conn: Conn) -> dict[str, Any]:
    auth.remove_passkey(conn, encoded_id)
    conn.commit()
    return {"passkeys": auth.list_passkeys(conn)}


@router.post("/recovery-code")
async def replace_recovery_code(request: Request, _: Session, conn: Conn) -> dict[str, Any]:
    """Needs Face ID as well as the session, because whoever holds this code can get back in."""
    body = await _body(request)
    auth.check_passkey(conn, body.get("credential"))
    code = auth.new_recovery_code(conn)
    conn.commit()
    return {"recovery_code": code}
