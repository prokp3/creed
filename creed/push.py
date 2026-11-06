"""Web Push: notifications to the installed app, with no third-party service in between.

A phone that agrees to notifications gives the app an address at its push service (Apple's, for an iPhone) and two
keys. A message is encrypted for that phone (RFC 8291, aes128gcm) so the push service can't read it, and signed with
this deployment's VAPID key (RFC 8292) so the push service knows who sent it. Everything here uses the
`cryptography` package, which passkeys already need.

The VAPID key pair lives in two server-side environment variables. tools/make_vapid_keys.py creates them.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PRIVATE_KEY_ENV = "PUSH_VAPID_PRIVATE_KEY"
PUBLIC_KEY_ENV = "PUSH_VAPID_PUBLIC_KEY"
RECORD_SIZE = 4096
TIMEOUT_SECONDS = 10

# What the push service said, in the terms the app cares about.
SENT = "sent"
GONE = "gone"  # The phone unsubscribed or the app was removed: forget this address.
FAILED = "failed"


class PushNotConfigured(RuntimeError):
    """The VAPID keys aren't set on the server."""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def generate_vapid_keys() -> tuple[str, str]:
    """A new key pair: the private key's 32 bytes and the public key's 65, both base64url."""
    private = ec.generate_private_key(ec.SECP256R1())
    number = private.private_numbers().private_value.to_bytes(32, "big")
    return b64url(number), b64url(_public_bytes(private.public_key()))


@dataclass(frozen=True)
class VapidKeys:
    private: ec.EllipticCurvePrivateKey
    public_b64: str


def load_vapid_keys() -> VapidKeys | None:
    """The deployment's keys, or None when notifications aren't set up. A mismatched pair is refused."""
    private_text = os.environ.get(PRIVATE_KEY_ENV, "").strip()
    public_text = os.environ.get(PUBLIC_KEY_ENV, "").strip()
    if not private_text or not public_text:
        return None
    private = ec.derive_private_key(int.from_bytes(unb64url(private_text), "big"), ec.SECP256R1())
    if b64url(_public_bytes(private.public_key())) != public_text:
        raise PushNotConfigured(f"{PUBLIC_KEY_ENV} doesn't match {PRIVATE_KEY_ENV}.")
    return VapidKeys(private, public_text)


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            sender: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """The message body for one phone (RFC 8291). `salt` and `sender` are only passed in tests."""
    receiver_bytes = unb64url(p256dh)
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver_bytes)
    auth_secret = unb64url(auth)
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    sender_bytes = _public_bytes(sender.public_key())
    salt = salt or secrets.token_bytes(16)

    shared = sender.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + receiver_bytes + sender_bytes, 32)
    key = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    if len(payload) > RECORD_SIZE - 16 - 1 - 86:
        raise ValueError("A notification must be under 4 KB.")
    # One record, so it ends with the last-record delimiter and no padding.
    ciphertext = AESGCM(key).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(sender_bytes)) + sender_bytes
    return header + ciphertext


def vapid_authorization(endpoint: str, keys: VapidKeys, subject: str, now: float | None = None) -> str:
    """The Authorization header: a signed token saying which deployment sent this, valid for 12 hours."""
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": subject}
    header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    r, s = decode_dss_signature(keys.private.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    signature = b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{body}.{signature}, k={keys.public_b64}"


def subject() -> str:
    """Who to contact about these notifications: the deployment's own address, never a personal email."""
    origin = os.environ.get("CREED_ORIGIN", "").strip().rstrip("/")
    return origin if origin.startswith("https://") else "https://github.com/prokp3/creed"


def send(subscription: dict[str, Any], message: dict[str, Any], keys: VapidKeys, *, ttl: int = 3600,
         urgency: str = "normal") -> str:
    """Send one notification. Returns SENT, GONE (forget this phone) or FAILED (try again another time)."""
    endpoint = subscription["endpoint"]
    if not endpoint.startswith("https://"):
        return GONE
    body = encrypt(json.dumps(message, separators=(",", ":")).encode(), subscription["p256dh"], subscription["auth"])
    request = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": urgency,
        "Authorization": vapid_authorization(endpoint, keys, subject()),
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return SENT if 200 <= response.status < 300 else FAILED
    except urllib.error.HTTPError as exc:
        return GONE if exc.code in (404, 410) else FAILED
    except (urllib.error.URLError, TimeoutError, OSError):
        return FAILED
