"""Signing in: passkeys, sessions and the recovery code. No web code here, so it can be tested directly.

One deployment, one person, so there are no usernames. A passkey either belongs to this deployment or it doesn't.
Each function leaves committing to its caller, except that a challenge is committed as soon as it's used, so a
failed answer can't be tried again.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url, parse_client_data_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from creed.db.store import Store

log = logging.getLogger(__name__)

APP_NAME = "Creed"
ORIGIN_ENV_VAR = "CREED_ORIGIN"
SETUP_SECRET_ENV_VAR = "CREED_SETUP_SECRET"
MIN_SETUP_SECRET_LENGTH = 32
USER_HANDLE_SECRET = "passkey_user_handle"

SESSION_COOKIE = "creed_session"
COOKIE_MAX_AGE_SECONDS = 365 * 24 * 3600  # The server decides when a session ends. See the lifetimes below.
SESSION_DAYS = 30  # Counted from the last time the app was used.
RECOVERY_SESSION_MINUTES = 60  # Long enough to make a new passkey, and no longer.
DEV_SESSION_HOURS = 24

CHALLENGE_MINUTES = 5
PASSKEY_TIMEOUT_MS = 120_000
# Anyone can ask to sign in, so what they can make the database hold has to be limited.
MAX_WAITING_SIGN_INS = 50

# Crockford's base32: no I, L, O or U, so it survives being written down. 25 characters is 125 random bits,
# far beyond guessing, which is why there is no attempt limit that could also lock the owner out.
RECOVERY_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
RECOVERY_LENGTH = 25
RECOVERY_LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})
MAX_LABEL_LENGTH = 40


class NotConfigured(Exception):
    """The server is missing a setting that signing in needs."""


class Refused(Exception):
    """The attempt failed. The message is safe to show."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RelyingParty:
    origin: str
    rp_id: str
    secure: bool


def relying_party() -> RelyingParty:
    """The app's one address. It's a fixed setting, never read from a request, because a passkey is tied to it."""
    origin = os.environ.get(ORIGIN_ENV_VAR, "").strip().rstrip("/")
    if not origin:
        raise NotConfigured(f"Set {ORIGIN_ENV_VAR} to this app's address first.")
    parts = urlsplit(origin)
    host = parts.hostname or ""
    if parts.path or parts.query or parts.fragment or not host or _is_ip_address(host):
        raise NotConfigured(f"{ORIGIN_ENV_VAR} must be an address with a domain name and no path.")
    if parts.scheme != "https" and not (parts.scheme == "http" and host == "localhost"):
        raise NotConfigured(f"{ORIGIN_ENV_VAR} must use https, because passkeys only work over a secure connection.")
    return RelyingParty(origin=origin, rp_id=host, secure=parts.scheme == "https")


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


# -- setup secret ---------------------------------------------------------


def check_setup_secret(given: Any) -> None:
    expected = os.environ.get(SETUP_SECRET_ENV_VAR, "").strip()
    if not expected:
        raise Refused(f"Registration is closed. Set {SETUP_SECRET_ENV_VAR} on the server to open it.", 403)
    # There's no attempt limit, so on a real address a short secret could be guessed by anyone. Only this computer
    # can reach a localhost server, so the owner's choice of any length is safe there.
    if len(expected) < MIN_SETUP_SECRET_LENGTH and relying_party().secure:
        raise NotConfigured(f"{SETUP_SECRET_ENV_VAR} must be at least {MIN_SETUP_SECRET_LENGTH} characters on a real address.")
    if not isinstance(given, str) or not hmac.compare_digest(given.strip().encode(), expected.encode()):
        raise Refused("That setup secret isn't right.", 403)


# -- challenges -----------------------------------------------------------


def _save_challenge(conn: psycopg.Connection, challenge: bytes, purpose: str) -> None:
    conn.execute("delete from auth_challenge where expires_at <= now()")
    conn.execute(
        "insert into auth_challenge (challenge, purpose, expires_at) "
        "values (%s, %s, now() + make_interval(mins => %s))",
        (challenge, purpose, CHALLENGE_MINUTES),
    )
    if purpose == "sign_in":
        conn.execute(
            "delete from auth_challenge where purpose = 'sign_in' and challenge not in ("
            "select challenge from auth_challenge where purpose = 'sign_in' "
            "order by created_at desc limit %s)",
            (MAX_WAITING_SIGN_INS,),
        )


def _take_challenge(conn: psycopg.Connection, credential: Any, purpose: str) -> bytes:
    """Use up the challenge this answer claims to be for. Committed at once, so it can't be tried twice."""
    try:
        client_data = parse_client_data_json(base64url_to_bytes(credential["response"]["clientDataJSON"]))
        claimed = client_data.challenge
    except Exception:
        raise Refused("That answer couldn't be read.", 400) from None
    row = conn.execute(
        "delete from auth_challenge where challenge = %s and purpose = %s and expires_at > now() returning challenge",
        (claimed, purpose),
    ).fetchone()
    conn.commit()
    if row is None:
        raise Refused("That attempt has expired. Try again.")
    return bytes(row["challenge"])


# -- passkeys -------------------------------------------------------------


def _user_handle(conn: psycopg.Connection) -> bytes:
    """Random and stable, so registering again on a device replaces its passkey for this app."""
    store = Store(conn)
    handle = store.get_secret(USER_HANDLE_SECRET)
    if handle is None:
        handle = secrets.token_urlsafe(32)
        store.set_secret(USER_HANDLE_SECRET, handle)
    return handle.encode()


def has_passkey(conn: psycopg.Connection) -> bool:
    return conn.execute("select exists (select 1 from auth_credential) as found").fetchone()["found"]


def registration_options(conn: psycopg.Connection) -> dict[str, Any]:
    rp = relying_party()
    existing = conn.execute("select credential_id from auth_credential").fetchall()
    options = generate_registration_options(
        rp_id=rp.rp_id,
        rp_name=APP_NAME,
        user_name=APP_NAME,
        user_display_name=APP_NAME,
        user_id=_user_handle(conn),
        timeout=PASSKEY_TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=bytes(row["credential_id"])) for row in existing],
    )
    _save_challenge(conn, options.challenge, "register")
    return json.loads(options_to_json(options))


def finish_registration(conn: psycopg.Connection, credential: Any, label: Any) -> None:
    rp = relying_party()
    challenge = _take_challenge(conn, credential, "register")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            require_user_verification=True,
        )
    except Exception as exc:  # Anything unexpected in the answer must end in refusal, not a crash.
        log.warning("Passkey registration refused: %s", type(exc).__name__)
        raise Refused("That passkey couldn't be verified.") from None
    name = label.strip()[:MAX_LABEL_LENGTH] if isinstance(label, str) and label.strip() else "Passkey"
    conn.execute(
        "insert into auth_credential (credential_id, public_key, sign_count, backed_up, label) "
        "values (%s, %s, %s, %s, %s)",
        (verified.credential_id, verified.credential_public_key, verified.sign_count,
         verified.credential_backed_up, name),
    )


def sign_in_options(conn: psycopg.Connection) -> dict[str, Any]:
    rp = relying_party()
    options = generate_authentication_options(
        rp_id=rp.rp_id,
        timeout=PASSKEY_TIMEOUT_MS,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _save_challenge(conn, options.challenge, "sign_in")
    return json.loads(options_to_json(options))


def check_passkey(conn: psycopg.Connection, credential: Any) -> None:
    """Prove the owner holds a registered passkey and has just passed Face ID, or refuse."""
    rp = relying_party()
    challenge = _take_challenge(conn, credential, "sign_in")
    try:
        credential_id = base64url_to_bytes(credential["rawId"])
    except Exception:
        raise Refused("That answer couldn't be read.", 400) from None
    stored = conn.execute(
        "select public_key, sign_count from auth_credential where credential_id = %s", (credential_id,)
    ).fetchone()
    if stored is None:
        raise Refused("This passkey isn't registered here. Use your recovery code.")
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            credential_public_key=bytes(stored["public_key"]),
            credential_current_sign_count=stored["sign_count"],
            require_user_verification=True,
        )
    except Exception as exc:
        log.warning("Passkey sign-in refused: %s", type(exc).__name__)
        raise Refused("That passkey wasn't accepted.") from None
    conn.execute(
        "update auth_credential set sign_count = %s, backed_up = %s, last_used_at = now() where credential_id = %s",
        (verified.new_sign_count, verified.credential_backed_up, credential_id),
    )


def list_passkeys(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select credential_id, label, backed_up, created_at, last_used_at from auth_credential order by created_at"
    ).fetchall()
    return [
        {
            "id": bytes_to_base64url(bytes(row["credential_id"])),
            "label": row["label"],
            "synced": row["backed_up"],
            "created_at": row["created_at"].isoformat(),
            "last_used_at": row["last_used_at"].isoformat() if row["last_used_at"] else None,
        }
        for row in rows
    ]


def remove_passkey(conn: psycopg.Connection, encoded_id: str) -> None:
    try:
        credential_id = base64url_to_bytes(encoded_id)
    except Exception:
        raise Refused("No such passkey.", 404) from None
    count = conn.execute("select count(*) as n from auth_credential").fetchone()["n"]
    found = conn.execute("select 1 from auth_credential where credential_id = %s", (credential_id,)).fetchone()
    if found is None:
        raise Refused("No such passkey.", 404)
    if count <= 1:
        raise Refused("This is your only passkey, so it can't be removed.", 409)
    conn.execute("delete from auth_credential where credential_id = %s", (credential_id,))


# -- sessions -------------------------------------------------------------


def start_session(conn: psycopg.Connection, kind: str = "passkey") -> str:
    conn.execute("delete from auth_session where expires_at <= now()")
    token = secrets.token_urlsafe(32)
    lifetime = {"recovery": f"{RECOVERY_SESSION_MINUTES} minutes", "passkey": f"{SESSION_DAYS} days"}[kind]
    conn.execute(
        "insert into auth_session (token_hash, kind, expires_at) values (%s, %s, now() + %s::interval)",
        (_hash(token), kind, lifetime),
    )
    return token


def save_dev_session(conn: psycopg.Connection, token: str) -> None:
    """For tools/dev_api.py and the tests only. It's a normal row with a short life, so the API has one way in."""
    conn.execute(
        "insert into auth_session (token_hash, kind, expires_at) values (%s, 'dev', now() + %s::interval) "
        "on conflict (token_hash) do update set expires_at = excluded.expires_at",
        (_hash(token), f"{DEV_SESSION_HOURS} hours"),
    )


def find_session(conn: psycopg.Connection, token: str | None) -> dict[str, Any] | None:
    """The live session for this token, if any. Using the app keeps a passkey session going."""
    if not token:
        return None
    row = conn.execute(
        "select kind, now() - last_seen_at > interval '1 day' as stale from auth_session "
        "where token_hash = %s and expires_at > now()",
        (_hash(token),),
    ).fetchone()
    if row is None:
        return None
    if row["kind"] == "passkey" and row["stale"]:
        conn.execute(
            "update auth_session set last_seen_at = now(), expires_at = now() + %s::interval where token_hash = %s",
            (f"{SESSION_DAYS} days", _hash(token)),
        )
        conn.commit()
    return {"kind": row["kind"]}


def end_session(conn: psycopg.Connection, token: str | None) -> None:
    if token:
        conn.execute("delete from auth_session where token_hash = %s", (_hash(token),))


def end_all_sessions(conn: psycopg.Connection) -> None:
    conn.execute("delete from auth_session")


# -- recovery code --------------------------------------------------------


def new_recovery_code(conn: psycopg.Connection) -> str:
    """Replace any existing code. This is the only time the code is ever available."""
    code = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
    conn.execute("delete from auth_recovery_code")
    conn.execute("insert into auth_recovery_code (code_hash) values (%s)", (_hash(code),))
    return "-".join(code[i:i + 5] for i in range(0, RECOVERY_LENGTH, 5))


def has_recovery_code(conn: psycopg.Connection) -> bool:
    return conn.execute("select exists (select 1 from auth_recovery_code) as found").fetchone()["found"]


def recovery_code_created(conn: psycopg.Connection) -> str | None:
    row = conn.execute("select created_at from auth_recovery_code limit 1").fetchone()
    return row["created_at"].isoformat() if row else None


def use_recovery_code(conn: psycopg.Connection, given: Any) -> bool:
    """True if this was the code, which is then gone for good. Forgiving about case, spacing and lookalikes."""
    if not isinstance(given, str):
        return False
    cleaned = "".join(ch for ch in given.upper().translate(RECOVERY_LOOKALIKES) if ch in RECOVERY_ALPHABET)
    if len(cleaned) != RECOVERY_LENGTH:
        return False
    row = conn.execute(
        "delete from auth_recovery_code where code_hash = %s returning code_hash", (_hash(cleaned),)
    ).fetchone()
    return row is not None
