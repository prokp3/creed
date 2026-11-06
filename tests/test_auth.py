"""Signing in, against a real Postgres and the real WebAuthn checks. Only the device is simulated."""
from __future__ import annotations

import re

import pytest
from fake_passkey import FakePasskey
from fastapi.testclient import TestClient

from creed import auth
from creed.api import app as api_module

ORIGIN = "http://localhost:5173"
SECRET = "correct-horse-battery-staple-setup-secret"


@pytest.fixture
def client(store, database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv(auth.ORIGIN_ENV_VAR, ORIGIN)
    monkeypatch.setenv(auth.SETUP_SECRET_ENV_VAR, SECRET)
    monkeypatch.delenv("CREED_API_TOKEN", raising=False)
    store.commit()
    return TestClient(api_module.app)


def register(client, passkey=None, secret=SECRET, **kwargs):
    passkey = passkey or FakePasskey(ORIGIN)
    options = client.post("/api/auth/register/options", json={"setup_secret": secret}).json()
    response = client.post(
        "/api/auth/register/verify", json={"credential": passkey.register(options, **kwargs), "label": "iPhone"}
    )
    return passkey, response


def sign_in(client, passkey, **kwargs):
    options = client.post("/api/auth/sign-in/options").json()
    return client.post("/api/auth/sign-in/verify", json={"credential": passkey.sign_in(options, **kwargs)})


def signed_in(client) -> bool:
    return client.get("/api/settings").status_code == 200


def set_up(client):
    """A deployment with one passkey and a recovery code, signed out."""
    passkey, response = register(client)
    assert response.status_code == 200
    client.post("/api/auth/sign-out")
    return passkey, response.json()["recovery_code"]


class TestSetup:
    def test_a_new_deployment_says_so_and_nothing_else(self, client):
        assert client.get("/api/auth/status").json() == {"signed_in": False, "session_kind": None, "has_passkey": False}

    def test_registration_needs_the_secret(self, client):
        assert client.post("/api/auth/register/options", json={}).status_code == 403
        assert client.post("/api/auth/register/options", json={"setup_secret": "wrong"}).status_code == 403

    def test_a_wrong_secret_is_not_echoed(self, client):
        response = client.post("/api/auth/register/options", json={"setup_secret": "my-wrong-guess"})
        assert "my-wrong-guess" not in response.text

    def test_registration_is_closed_with_no_secret_on_the_server(self, client, monkeypatch):
        monkeypatch.delenv(auth.SETUP_SECRET_ENV_VAR)
        response = client.post("/api/auth/register/options", json={"setup_secret": ""})
        assert response.status_code == 403
        assert "closed" in response.json()["detail"]

    def test_a_short_server_secret_is_refused_on_a_real_address(self, client, monkeypatch):
        monkeypatch.setenv(auth.ORIGIN_ENV_VAR, "https://creed.example")
        monkeypatch.setenv(auth.SETUP_SECRET_ENV_VAR, "short")
        response = client.post("/api/auth/register/options", json={"setup_secret": "short"})
        assert response.status_code == 503
        assert str(auth.MIN_SETUP_SECRET_LENGTH) in response.json()["detail"]

    def test_a_short_server_secret_works_on_this_computer(self, client, monkeypatch):
        monkeypatch.setenv(auth.SETUP_SECRET_ENV_VAR, "short")
        assert client.post("/api/auth/register/options", json={"setup_secret": "short"}).status_code == 200
        assert client.post("/api/auth/register/options", json={"setup_secret": "wrong"}).status_code == 403

    def test_first_registration_signs_in_and_gives_a_code_once(self, client):
        _, response = register(client)
        assert response.status_code == 200
        assert re.fullmatch(r"([0-9A-Z]{5}-){4}[0-9A-Z]{5}", response.json()["recovery_code"])
        assert signed_in(client)
        assert client.get("/api/auth/status").json() == {"signed_in": True, "session_kind": "passkey", "has_passkey": True}

    def test_registration_is_closed_afterwards_without_the_secret(self, client):
        set_up(client)
        assert client.post("/api/auth/register/options", json={}).status_code == 403

    def test_a_signed_in_session_does_not_open_registration(self, client):
        register(client)
        assert signed_in(client)
        assert client.post("/api/auth/register/options", json={}).status_code == 403

    def test_the_secret_reopens_it_and_the_code_stays_as_it_was(self, client):
        _, code = set_up(client)
        second, response = register(client, FakePasskey(ORIGIN))
        assert response.status_code == 200
        assert response.json()["recovery_code"] is None
        assert sign_in(client, second).status_code == 200
        client.post("/api/auth/sign-out")
        assert client.post("/api/auth/recover", json={"code": code}).status_code == 200

    def test_an_answer_with_no_challenge_from_the_secret_is_refused(self, client):
        # Someone without the secret can get a sign-in challenge, but it can't be spent on registering.
        options = client.post("/api/auth/sign-in/options").json()
        credential = FakePasskey(ORIGIN).register(options)
        assert client.post("/api/auth/register/verify", json={"credential": credential}).status_code == 401
        assert client.get("/api/auth/status").json()["has_passkey"] is False

    def test_registration_must_use_face_id(self, client):
        _, response = register(client, user_verified=False)
        assert response.status_code == 401
        assert client.get("/api/auth/status").json()["has_passkey"] is False

    def test_registration_from_another_site_is_refused(self, client):
        _, response = register(client, origin="https://evil.example")
        assert response.status_code == 401

    def test_registration_for_another_domain_is_refused(self, client):
        _, response = register(client, rp_id="evil.example")
        assert response.status_code == 401

    def test_options_ask_for_a_discoverable_passkey_and_face_id(self, client):
        options = client.post("/api/auth/register/options", json={"setup_secret": SECRET}).json()
        assert options["rp"]["id"] == "localhost"
        assert options["authenticatorSelection"]["residentKey"] == "required"
        assert options["authenticatorSelection"]["userVerification"] == "required"
        assert options["attestation"] == "none"

    def test_the_user_handle_stays_the_same(self, client):
        first = client.post("/api/auth/register/options", json={"setup_secret": SECRET}).json()
        second = client.post("/api/auth/register/options", json={"setup_secret": SECRET}).json()
        assert first["user"]["id"] == second["user"]["id"]
        assert first["challenge"] != second["challenge"]

    def test_a_device_with_a_passkey_is_told_not_to_make_another(self, client):
        passkey, _ = register(client)
        options = client.post("/api/auth/register/options", json={"setup_secret": SECRET}).json()
        assert [c["id"] for c in options["excludeCredentials"]] == [passkey.register({"challenge": ""})["id"]]


class TestSignIn:
    def test_a_registered_passkey_signs_in(self, client):
        passkey, _ = set_up(client)
        assert not signed_in(client)
        assert sign_in(client, passkey).status_code == 200
        assert signed_in(client)

    def test_options_name_no_passkeys_and_require_face_id(self, client):
        set_up(client)
        options = client.post("/api/auth/sign-in/options").json()
        assert options["allowCredentials"] == []
        assert options["userVerification"] == "required"

    def test_an_unregistered_passkey_is_refused(self, client):
        set_up(client)
        assert sign_in(client, FakePasskey(ORIGIN)).status_code == 401
        assert not signed_in(client)

    def test_without_face_id_is_refused(self, client):
        passkey, _ = set_up(client)
        assert sign_in(client, passkey, user_verified=False).status_code == 401
        assert not signed_in(client)

    def test_from_another_site_is_refused(self, client):
        passkey, _ = set_up(client)
        assert sign_in(client, passkey, origin="https://evil.example").status_code == 401

    def test_for_another_domain_is_refused(self, client):
        passkey, _ = set_up(client)
        assert sign_in(client, passkey, rp_id="evil.example").status_code == 401

    def test_a_registration_style_answer_is_refused(self, client):
        passkey, _ = set_up(client)
        assert sign_in(client, passkey, kind="webauthn.create").status_code == 401

    def test_a_signature_from_a_different_key_is_refused(self, client):
        passkey, _ = set_up(client)
        impostor = FakePasskey(ORIGIN)
        impostor.credential_id = passkey.credential_id
        assert sign_in(client, impostor).status_code == 401
        assert not signed_in(client)

    def test_an_answer_cannot_be_replayed(self, client):
        passkey, _ = set_up(client)
        options = client.post("/api/auth/sign-in/options").json()
        answer = passkey.sign_in(options)
        assert client.post("/api/auth/sign-in/verify", json={"credential": answer}).status_code == 200
        client.post("/api/auth/sign-out")
        assert client.post("/api/auth/sign-in/verify", json={"credential": answer}).status_code == 401
        assert not signed_in(client)

    def test_a_failed_answer_uses_up_the_challenge(self, client):
        passkey, _ = set_up(client)
        options = client.post("/api/auth/sign-in/options").json()
        bad = passkey.sign_in(options, user_verified=False)
        assert client.post("/api/auth/sign-in/verify", json={"credential": bad}).status_code == 401
        good = passkey.sign_in(options)
        assert client.post("/api/auth/sign-in/verify", json={"credential": good}).status_code == 401

    def test_an_expired_challenge_is_refused(self, client, store):
        passkey, _ = set_up(client)
        options = client.post("/api/auth/sign-in/options").json()
        store.conn.execute("update auth_challenge set expires_at = now() - interval '1 second'")
        store.commit()
        answer = passkey.sign_in(options)
        response = client.post("/api/auth/sign-in/verify", json={"credential": answer})
        assert response.status_code == 401
        assert "expired" in response.json()["detail"]

    def test_a_cloned_hardware_key_is_caught_by_its_counter(self, client):
        passkey, _ = register(client, FakePasskey(ORIGIN, counting=True, synced=False))
        client.post("/api/auth/sign-out")
        assert sign_in(client, passkey).status_code == 200
        client.post("/api/auth/sign-out")
        passkey.counter -= 1  # The clone is one step behind.
        assert sign_in(client, passkey).status_code == 401

    def test_icloud_passkeys_always_at_zero_still_work(self, client):
        passkey, _ = set_up(client)
        for _ in range(2):
            assert sign_in(client, passkey).status_code == 200
            client.post("/api/auth/sign-out")

    @pytest.mark.parametrize("credential", [
        None, "text", [], {}, {"response": {}}, {"response": {"clientDataJSON": "!!!"}}, {"rawId": 5, "response": 5},
    ])
    def test_nonsense_answers_are_refused_without_crashing(self, client, credential):
        set_up(client)
        response = client.post("/api/auth/sign-in/verify", json={"credential": credential})
        assert response.status_code in (400, 401)
        assert not signed_in(client)

    def test_a_real_challenge_with_nonsense_around_it_is_refused(self, client):
        passkey, _ = set_up(client)
        options = client.post("/api/auth/sign-in/options").json()
        answer = passkey.sign_in(options)
        answer["response"]["signature"] = "AAAA"
        assert client.post("/api/auth/sign-in/verify", json={"credential": answer}).status_code == 401

    @pytest.mark.parametrize("route", ["/api/auth/sign-in/verify", "/api/auth/register/verify", "/api/auth/recover"])
    def test_a_body_that_is_not_an_object_is_refused(self, client, route):
        assert client.post(route, json=["list"]).status_code == 422
        assert client.post(route, content="not json", headers={"Content-Type": "application/json"}).status_code == 422

    def test_waiting_sign_ins_cannot_fill_the_database(self, client, store, monkeypatch):
        monkeypatch.setattr(auth, "MAX_WAITING_SIGN_INS", 5)
        for _ in range(12):
            client.post("/api/auth/sign-in/options")
        count = store.conn.execute("select count(*) as n from auth_challenge").fetchone()["n"]
        store.commit()
        assert count == 5

    def test_the_cap_does_not_touch_a_registration_in_progress(self, client, store, monkeypatch):
        monkeypatch.setattr(auth, "MAX_WAITING_SIGN_INS", 2)
        passkey = FakePasskey(ORIGIN)
        options = client.post("/api/auth/register/options", json={"setup_secret": SECRET}).json()
        for _ in range(6):
            client.post("/api/auth/sign-in/options")
        response = client.post("/api/auth/register/verify", json={"credential": passkey.register(options)})
        assert response.status_code == 200


class TestSessions:
    def test_the_cookie_cannot_be_read_by_scripts_or_sent_by_other_sites(self, client):
        _, response = register(client)
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{auth.SESSION_COOKIE}=")
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "Path=/" in cookie

    def test_the_cookie_is_https_only_on_a_real_address(self, client, monkeypatch):
        origin = "https://creed.example"
        monkeypatch.setenv(auth.ORIGIN_ENV_VAR, origin)
        _, response = register(client, FakePasskey(origin))
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]

    def test_the_cookie_is_not_https_only_on_localhost(self, client):
        _, response = register(client)
        assert "Secure" not in response.headers["set-cookie"]

    def test_tokens_are_stored_only_as_hashes(self, client, store):
        register(client)
        token = client.cookies[auth.SESSION_COOKIE]
        stored = bytes(store.conn.execute("select token_hash from auth_session").fetchone()["token_hash"])
        store.commit()
        assert token.encode() not in stored
        assert len(stored) == 32

    def test_a_copied_hash_cannot_be_used_as_a_session(self, client, store):
        register(client)
        stored = bytes(store.conn.execute("select token_hash from auth_session").fetchone()["token_hash"])
        store.commit()
        response = TestClient(api_module.app).get("/api/settings", headers={"Cookie": f"{auth.SESSION_COOKIE}={stored.hex()}"})
        assert response.status_code == 401

    def test_signing_out_ends_the_session_on_the_server(self, client, store):
        register(client)
        token = client.cookies[auth.SESSION_COOKIE]
        client.post("/api/auth/sign-out")
        assert not signed_in(client)
        replay = TestClient(api_module.app).get("/api/settings", headers={"Cookie": f"{auth.SESSION_COOKIE}={token}"})
        assert replay.status_code == 401
        assert store.conn.execute("select count(*) as n from auth_session").fetchone()["n"] == 0
        store.commit()

    def test_an_expired_session_is_refused(self, client, store):
        register(client)
        store.conn.execute("update auth_session set expires_at = now() - interval '1 second'")
        store.commit()
        assert not signed_in(client)

    def test_using_the_app_keeps_a_passkey_session_going(self, client, store):
        register(client)
        store.conn.execute("update auth_session set last_seen_at = now() - interval '2 days', "
                           "expires_at = now() + interval '1 day'")
        store.commit()
        assert signed_in(client)
        left = store.conn.execute("select expires_at - now() as left from auth_session").fetchone()["left"]
        store.commit()
        assert left.days >= auth.SESSION_DAYS - 1

    def test_a_session_is_not_written_to_on_every_request(self, client, store):
        register(client)
        store.conn.execute("update auth_session set expires_at = now() + interval '1 day'")
        store.commit()
        assert signed_in(client)
        left = store.conn.execute("select expires_at - now() as left from auth_session").fetchone()["left"]
        store.commit()
        assert left.days == 0 or left.days == 1

    def test_signing_in_again_replaces_the_old_session(self, client, store):
        passkey, _ = register(client)
        assert sign_in(client, passkey).status_code == 200
        assert store.conn.execute("select count(*) as n from auth_session").fetchone()["n"] == 1
        store.commit()

    def test_expired_sessions_are_cleaned_up(self, client, store):
        passkey, _ = register(client)
        store.conn.execute("update auth_session set expires_at = now() - interval '1 second'")
        store.commit()
        assert sign_in(client, passkey).status_code == 200
        assert store.conn.execute("select count(*) as n from auth_session").fetchone()["n"] == 1
        store.commit()


class TestRecovery:
    def test_a_code_signs_in_once_and_gives_a_new_one(self, client):
        _, code = set_up(client)
        response = client.post("/api/auth/recover", json={"code": code})
        assert response.status_code == 200
        assert signed_in(client)
        replacement = response.json()["recovery_code"]
        assert replacement != code
        client.post("/api/auth/sign-out")
        assert client.post("/api/auth/recover", json={"code": code}).status_code == 401
        assert not signed_in(client)
        assert client.post("/api/auth/recover", json={"code": replacement}).status_code == 200

    @pytest.mark.parametrize("given", ["", "nope", "AAAAA-AAAAA-AAAAA-AAAAA-AAAAA", None, 12345, ["x"], {"a": 1}])
    def test_a_wrong_code_is_refused(self, client, given):
        set_up(client)
        assert client.post("/api/auth/recover", json={"code": given}).status_code == 401
        assert not signed_in(client)

    def test_a_wrong_code_does_not_use_up_the_real_one(self, client):
        _, code = set_up(client)
        client.post("/api/auth/recover", json={"code": "AAAAA-AAAAA-AAAAA-AAAAA-AAAAA"})
        assert client.post("/api/auth/recover", json={"code": code}).status_code == 200

    def test_a_code_typed_loosely_still_works(self, client):
        _, code = set_up(client)
        loose = code.replace("-", " ").lower().replace("0", "o").replace("1", "l")
        assert client.post("/api/auth/recover", json={"code": loose}).status_code == 200

    def test_the_code_is_stored_only_as_a_hash(self, client, store):
        _, code = set_up(client)
        stored = bytes(store.conn.execute("select code_hash from auth_recovery_code").fetchone()["code_hash"])
        store.commit()
        assert code.replace("-", "").encode() not in stored

    def test_it_ends_every_other_session(self, client):
        passkey, code = set_up(client)
        other_device = TestClient(api_module.app)
        assert sign_in(other_device, passkey).status_code == 200
        assert signed_in(other_device)
        client.post("/api/auth/recover", json={"code": code})
        assert not signed_in(other_device)

    def test_the_session_is_short_and_not_extended(self, client, store):
        _, code = set_up(client)
        client.post("/api/auth/recover", json={"code": code})
        assert client.get("/api/auth/status").json()["session_kind"] == "recovery"
        left = store.conn.execute("select expires_at - now() as left from auth_session").fetchone()["left"]
        assert left.total_seconds() <= auth.RECOVERY_SESSION_MINUTES * 60
        store.conn.execute("update auth_session set last_seen_at = now() - interval '2 days'")
        store.commit()
        assert signed_in(client)
        left = store.conn.execute("select expires_at - now() as left from auth_session").fetchone()["left"]
        store.commit()
        assert left.total_seconds() <= auth.RECOVERY_SESSION_MINUTES * 60

    def test_it_lets_you_make_a_new_passkey_without_the_secret(self, client, store):
        _, code = set_up(client)
        client.post("/api/auth/recover", json={"code": code})
        replacement = FakePasskey(ORIGIN)
        options = client.post("/api/auth/register/options", json={}).json()
        response = client.post("/api/auth/register/verify", json={"credential": replacement.register(options)})
        assert response.status_code == 200
        assert response.json()["recovery_code"] is None  # It already gave you one.
        assert client.get("/api/auth/status").json()["session_kind"] == "passkey"
        client.post("/api/auth/sign-out")
        assert sign_in(client, replacement).status_code == 200


class TestSignInDetails:
    def test_needs_a_session(self, client):
        assert client.get("/api/auth/details").status_code == 401
        assert client.delete("/api/auth/passkeys/AAAA").status_code == 401
        assert client.post("/api/auth/recovery-code", json={}).status_code == 401

    def test_lists_passkeys_without_their_keys(self, client):
        register(client)
        response = client.get("/api/auth/details")
        passkeys = response.json()["passkeys"]
        assert [p["label"] for p in passkeys] == ["iPhone"]
        assert passkeys[0]["synced"] is True
        assert passkeys[0]["last_used_at"] is None
        assert set(passkeys[0]) == {"id", "label", "synced", "created_at", "last_used_at"}
        assert response.json()["recovery_code_created_at"]

    def test_signing_in_records_when_it_was_used(self, client):
        passkey, _ = set_up(client)
        sign_in(client, passkey)
        assert client.get("/api/auth/details").json()["passkeys"][0]["last_used_at"]

    def test_a_long_label_is_cut_and_a_missing_one_has_a_default(self, client):
        options = client.post("/api/auth/register/options", json={"setup_secret": SECRET}).json()
        client.post("/api/auth/register/verify", json={"credential": FakePasskey(ORIGIN).register(options), "label": "x" * 500})
        options = client.post("/api/auth/register/options", json={"setup_secret": SECRET}).json()
        client.post("/api/auth/register/verify", json={"credential": FakePasskey(ORIGIN).register(options), "label": 5})
        labels = [p["label"] for p in client.get("/api/auth/details").json()["passkeys"]]
        assert labels == ["x" * auth.MAX_LABEL_LENGTH, "Passkey"]

    def test_a_passkey_can_be_removed_and_then_stops_working(self, client):
        first, _ = register(client)
        second, _ = register(client, FakePasskey(ORIGIN))
        ids = [p["id"] for p in client.get("/api/auth/details").json()["passkeys"]]
        assert client.delete(f"/api/auth/passkeys/{ids[0]}").status_code == 200
        client.post("/api/auth/sign-out")
        assert sign_in(client, first).status_code == 401
        assert sign_in(client, second).status_code == 200

    def test_the_only_passkey_cannot_be_removed(self, client):
        register(client)
        only = client.get("/api/auth/details").json()["passkeys"][0]["id"]
        response = client.delete(f"/api/auth/passkeys/{only}")
        assert response.status_code == 409
        assert len(client.get("/api/auth/details").json()["passkeys"]) == 1

    def test_removing_an_unknown_passkey_is_404(self, client):
        register(client)
        assert client.delete("/api/auth/passkeys/AAAA").status_code == 404

    def test_replacing_the_code_needs_face_id_as_well_as_a_session(self, client):
        passkey, old = set_up(client)
        sign_in(client, passkey)
        assert client.post("/api/auth/recovery-code", json={}).status_code in (400, 401)
        options = client.post("/api/auth/sign-in/options").json()
        answer = passkey.sign_in(options, user_verified=False)
        assert client.post("/api/auth/recovery-code", json={"credential": answer}).status_code == 401
        options = client.post("/api/auth/sign-in/options").json()
        response = client.post("/api/auth/recovery-code", json={"credential": passkey.sign_in(options)})
        assert response.status_code == 200
        new = response.json()["recovery_code"]
        client.post("/api/auth/sign-out")
        assert client.post("/api/auth/recover", json={"code": old}).status_code == 401
        assert client.post("/api/auth/recover", json={"code": new}).status_code == 200


class TestOtherSites:
    def test_changes_from_another_site_are_refused(self, client):
        register(client)
        evil = {"Origin": "https://evil.example"}
        assert client.put("/api/settings", json={"trimp_curve": "female"}, headers=evil).status_code == 403
        assert client.post("/api/auth/sign-out", headers=evil).status_code == 403
        assert signed_in(client)
        assert client.get("/api/settings").json()["trimp_curve"] == "male"

    def test_changes_from_the_app_itself_are_allowed(self, client):
        register(client)
        response = client.put("/api/settings", json={"trimp_curve": "female"}, headers={"Origin": ORIGIN})
        assert response.status_code == 200

    def test_a_refusal_is_not_cached(self, client):
        response = client.post("/api/auth/sign-in/options", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        assert response.headers["Cache-Control"] == "no-store"

    def test_the_scheduled_sync_has_no_browser_and_uses_its_own_secret(self, client, monkeypatch):
        monkeypatch.setenv("CRON_SECRET", "cron-secret")
        response = client.post("/api/cron/sync", headers={"Origin": "https://github.com"})
        assert response.status_code == 401


class TestAddress:
    @pytest.mark.parametrize("origin, rp_id, secure", [
        ("https://creed.example", "creed.example", True),
        ("https://creed.example/", "creed.example", True),
        ("https://creed.vercel.app", "creed.vercel.app", True),
        ("http://localhost:5173", "localhost", False),
    ])
    def test_good_addresses(self, monkeypatch, origin, rp_id, secure):
        monkeypatch.setenv(auth.ORIGIN_ENV_VAR, origin)
        party = auth.relying_party()
        assert (party.rp_id, party.secure) == (rp_id, secure)
        assert party.origin == origin.rstrip("/")

    @pytest.mark.parametrize("origin", [
        "http://creed.example", "https://creed.example/app", "https://creed.example?x=1", "http://127.0.0.1:5173",
        "https://192.168.1.5", "https://[::1]", "creed.example", "ftp://creed.example",
    ])
    def test_bad_addresses_are_refused_with_a_reason(self, monkeypatch, origin):
        monkeypatch.setenv(auth.ORIGIN_ENV_VAR, origin)
        with pytest.raises(auth.NotConfigured):
            auth.relying_party()

    def test_with_no_address_sign_in_says_what_to_set(self, client, monkeypatch):
        monkeypatch.delenv(auth.ORIGIN_ENV_VAR)
        response = client.post("/api/auth/sign-in/options")
        assert response.status_code == 503
        assert auth.ORIGIN_ENV_VAR in response.json()["detail"]

    def test_with_no_address_a_browser_is_told_what_to_set_and_nothing_runs(self, client, store, monkeypatch):
        monkeypatch.delenv(auth.ORIGIN_ENV_VAR)
        response = client.post("/api/auth/recover", json={"code": "anything"}, headers={"Origin": ORIGIN})
        assert response.status_code == 503
        assert auth.ORIGIN_ENV_VAR in response.json()["detail"]
        assert client.put("/api/settings", json={}, headers={"Origin": ORIGIN}).status_code == 503
        store.commit()

    def test_a_passkey_made_on_the_old_address_stops_working_when_it_changes(self, client, monkeypatch):
        passkey, code = set_up(client)
        monkeypatch.setenv(auth.ORIGIN_ENV_VAR, "https://new.example")
        new_address_client = TestClient(api_module.app)
        assert sign_in(new_address_client, passkey).status_code == 401
        # The recovery code isn't tied to the address, so it's the way back in.
        assert new_address_client.post("/api/auth/recover", json={"code": code}).status_code == 200


def second_person(client, store):
    """Someone besides the owner, given a recovery code and then a passkey of their own. Returns both."""
    user_id = auth.create_user(store.conn)
    code = auth.new_recovery_code(store.conn, user_id)
    store.commit()
    assert client.post("/api/auth/recover", json={"code": code}).status_code == 200
    passkey, response = register(client, secret=None)
    assert response.status_code == 200
    return user_id, passkey


class TestPeople:
    def test_the_setup_secret_always_makes_passkeys_for_the_owner(self, client, store):
        register(client)
        register(client)
        rows = store.conn.execute("select count(*) as people, bool_and(is_owner) as owners from app_user").fetchone()
        assert rows == {"people": 1, "owners": True}

    def test_the_owner_has_a_starter_food_library(self, client, store):
        register(client)
        owner = auth.owner_id(store.conn)
        assert store.conn.execute("select count(*) as n from food where user_id = %s",
                                  (owner,)).fetchone()["n"] == 30

    def test_someone_else_signs_in_as_themselves(self, client, store):
        set_up(client)
        user_id, passkey = second_person(client, store)
        client.post("/api/auth/sign-out")
        assert sign_in(client, passkey).status_code == 200
        session = auth.find_session(store.conn, client.cookies.get(auth.SESSION_COOKIE))
        assert session["user_id"] == user_id
        assert session["is_owner"] is False

    @pytest.mark.parametrize("route", ["/api/race", "/api/today", "/api/in-depth", "/api/activities",
                                       "/api/activities/1", "/api/data-quality", "/api/settings"])
    def test_garmin_screens_belong_to_the_owner_alone(self, client, store, route):
        set_up(client)
        second_person(client, store)
        response = client.get(route)
        assert response.status_code == 403
        assert response.json() == {"detail": "This account has no Garmin data here."}

    def test_nor_can_they_change_settings_or_sync(self, client, store):
        set_up(client)
        second_person(client, store)
        assert client.put("/api/settings", json={"trimp_curve": "female"}).status_code == 403
        assert client.post("/api/sync").status_code == 403

    def test_each_person_sees_only_their_own_passkeys(self, client, store):
        set_up(client)
        second_person(client, store)
        passkeys = client.get("/api/auth/details").json()["passkeys"]
        assert len(passkeys) == 1

    def test_nobody_can_remove_someone_elses_passkey(self, client, store):
        owner_passkey, _ = set_up(client)
        sign_in(client, owner_passkey)
        owners = client.get("/api/auth/details").json()["passkeys"]
        client.post("/api/auth/sign-out")
        user_id, _ = second_person(client, store)
        # A second passkey of their own, so removing one would otherwise be allowed.
        store.conn.execute("insert into auth_credential (credential_id, public_key, label, user_id) "
                           "values ('\\x09', '\\x09', 'Laptop', %s)", (user_id,))
        store.commit()
        assert client.delete(f"/api/auth/passkeys/{owners[0]['id']}").status_code == 404
        assert len(auth.list_passkeys(store.conn, auth.owner_id(store.conn))) == 1

    def test_recovering_one_person_leaves_others_signed_in(self, client, store):
        owner_passkey, _ = set_up(client)
        owner = TestClient(api_module.app)
        assert sign_in(owner, owner_passkey).status_code == 200
        second_person(client, store)
        assert signed_in(owner)

    def test_a_recovery_code_only_ever_belongs_to_one_person(self, client, store):
        _, owner_code = set_up(client)
        second_person(client, store)
        client.post("/api/auth/sign-out")
        assert client.post("/api/auth/recover", json={"code": owner_code}).status_code == 200
        session = auth.find_session(store.conn, client.cookies.get(auth.SESSION_COOKIE))
        assert session["is_owner"] is True

    def test_a_new_code_needs_one_of_your_own_passkeys(self, client, store):
        owner_passkey, _ = set_up(client)
        second_person(client, store)
        options = client.post("/api/auth/sign-in/options").json()
        response = client.post("/api/auth/recovery-code", json={"credential": owner_passkey.sign_in(options)})
        assert response.status_code == 403


class TestUpgrade:
    """A deployment from before people existed keeps working, and everything it had becomes the owner's."""

    def test_existing_sign_in_becomes_the_owners(self, conn):
        from pathlib import Path

        from creed.db.migrate import MIGRATIONS, migrate

        conn.execute("create table schema_migration (version text primary key, "
                     "applied_at timestamptz not null default now())")
        for name in ("0001_init.sql", "0002_activity_derived.sql", "0003_auth.sql"):
            conn.execute(Path(MIGRATIONS, name).read_text(encoding="utf-8"))
            conn.execute("insert into schema_migration (version) values (%s)", (name,))
        conn.execute("insert into app_secret (name, value) values ('passkey_user_handle', 'the-old-handle')")
        conn.execute("insert into auth_credential (credential_id, public_key, label) values ('\x01', '\x02', 'iPhone')")
        conn.execute("insert into auth_session (token_hash, kind, expires_at) values ('\x03', 'passkey', now() + interval '1 day')")
        conn.execute("insert into auth_recovery_code (code_hash) values ('\x04')")
        conn.commit()

        assert migrate(conn) == ["0004_users.sql", "0005_food.sql", "0006_food_seed.sql", "0007_food_settings_push.sql"]
        owner = conn.execute("select id, passkey_handle from app_user where is_owner").fetchone()
        assert owner["passkey_handle"] == "the-old-handle"
        for table in ("auth_credential", "auth_session", "auth_recovery_code"):
            row = conn.execute(f"select user_id from {table}").fetchone()
            assert row["user_id"] == owner["id"]
        assert conn.execute("select count(*) as n from food where user_id = %s", (owner["id"],)).fetchone()["n"] == 30
        assert conn.execute("select count(*) as n from app_secret where name = 'passkey_user_handle'").fetchone()[
            "n"] == 0

    def test_a_fresh_deployment_has_nobody_until_registration(self, store):
        assert store.conn.execute("select count(*) as n from app_user").fetchone()["n"] == 0
