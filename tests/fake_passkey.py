"""A software passkey with a real P-256 key, so the tests run the real WebAuthn checks with nothing faked on the server."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

USER_PRESENT = 0x01
USER_VERIFIED = 0x04
BACKUP_ELIGIBLE = 0x08
BACKED_UP = 0x10
ATTESTED_DATA = 0x40


def encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class FakePasskey:
    def __init__(self, origin: str, *, synced: bool = True, counting: bool = False) -> None:
        self.origin = origin
        self.rp_id = origin.split("://")[1].split(":")[0].rstrip("/")
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.synced = synced
        self.counting = counting  # iCloud passkeys always report 0. Hardware keys count up.
        self.counter = 0

    def _public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _flags(self, user_verified: bool) -> int:
        flags = USER_PRESENT
        if user_verified:
            flags |= USER_VERIFIED
        if self.synced:
            flags |= BACKUP_ELIGIBLE | BACKED_UP
        return flags

    def _authenticator_data(self, flags: int, rp_id: str | None, attested: bytes = b"") -> bytes:
        rp_hash = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        return rp_hash + bytes([flags]) + struct.pack(">I", self.counter) + attested

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin or self.origin, "crossOrigin": False}
        ).encode()

    def register(
        self,
        options: dict[str, Any],
        *,
        origin: str | None = None,
        rp_id: str | None = None,
        user_verified: bool = True,
    ) -> dict[str, Any]:
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._public_key()
        data = self._authenticator_data(self._flags(user_verified) | ATTESTED_DATA, rp_id, attested)
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": data})
        return {
            "id": encode(self.credential_id),
            "rawId": encode(self.credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {"clientDataJSON": encode(client_data), "attestationObject": encode(attestation)},
        }

    def sign_in(
        self,
        options: dict[str, Any],
        *,
        origin: str | None = None,
        rp_id: str | None = None,
        user_verified: bool = True,
        kind: str = "webauthn.get",
    ) -> dict[str, Any]:
        if self.counting:
            self.counter += 1
        client_data = self._client_data(kind, options["challenge"], origin)
        data = self._authenticator_data(self._flags(user_verified), rp_id)
        signature = self.key.sign(data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": encode(self.credential_id),
            "rawId": encode(self.credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": encode(client_data),
                "authenticatorData": encode(data),
                "signature": encode(signature),
            },
        }
