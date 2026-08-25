"""End-to-end authentication behaviour against a real database."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from coresync.application.common.ports import OidcIdentity
from tests.api.conftest import DEFAULT_PASSWORD, auth_header, register_and_verify
from tests.fakes import CapturingEmailSender, FakeOidcVerifier

pytestmark = pytest.mark.integration


class TestRegistration:
    async def test_registration_sends_a_verification_email(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        response = await client.post(
            "/v1/auth/register",
            json={
                "email": "new@example.com",
                "password": DEFAULT_PASSWORD,
                "displayName": "New Lifter",
                "timezone": "Europe/Athens",
                "acceptedTerms": True,
            },
        )
        assert response.status_code == 201
        assert email_sender.last("verification")["to"] == "new@example.com"

    async def test_registering_an_existing_email_is_indistinguishable_from_success(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """User enumeration must be impossible.

        The second attempt returns the identical status and body; only the *owner* of
        the address learns anything, via a different email.
        """
        payload = {
            "email": "taken@example.com",
            "password": DEFAULT_PASSWORD,
            "displayName": "First",
            "timezone": "UTC",
            "acceptedTerms": True,
        }
        first = await client.post("/v1/auth/register", json=payload)
        second = await client.post("/v1/auth/register", json={**payload, "displayName": "Second"})

        assert first.status_code == second.status_code == 201
        assert first.json() == second.json()
        assert email_sender.last("account_exists")["to"] == "taken@example.com"

    async def test_rejects_a_weak_password(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/register",
            json={
                "email": "weak@example.com",
                "password": "password123456",
                "displayName": "Weak",
                "timezone": "UTC",
                "acceptedTerms": True,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] in ("weak_password", "validation_error")

    async def test_rejects_a_breached_password(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/register",
            json={
                "email": "breach@example.com",
                "password": "leaked-passphrase-alpha",
                "displayName": "Breached",
                "timezone": "UTC",
                "acceptedTerms": True,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "breached_password"

    async def test_terms_must_be_accepted(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/register",
            json={
                "email": "noterms@example.com",
                "password": DEFAULT_PASSWORD,
                "displayName": "No Terms",
                "timezone": "UTC",
                "acceptedTerms": False,
            },
        )
        assert response.status_code == 400


class TestEmailVerification:
    async def test_verification_signs_the_user_in(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        assert payload["user"]["emailVerified"] is True
        assert payload["user"]["status"] == "active"
        assert payload["accessToken"]
        assert payload["requiresOnboarding"] is True

    async def test_a_verification_token_cannot_be_reused(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        await client.post(
            "/v1/auth/register",
            json={
                "email": "once@example.com",
                "password": DEFAULT_PASSWORD,
                "displayName": "Once",
                "timezone": "UTC",
                "acceptedTerms": True,
            },
        )
        token = email_sender.token_from("verification")
        first = await client.post("/v1/auth/verify-email", json={"token": token})
        assert first.status_code == 200
        replay = await client.post("/v1/auth/verify-email", json={"token": token})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "invalid_token"

    async def test_rejects_a_fabricated_token(self, client: AsyncClient) -> None:
        response = await client.post("/v1/auth/verify-email", json={"token": "x" * 43})
        assert response.status_code == 401


class TestLogin:
    async def test_successful_login(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        await register_and_verify(client, email_sender)
        response = await client.post(
            "/v1/auth/login",
            json={"email": "lifter@example.com", "password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 200
        assert response.json()["accessToken"]
        assert response.json()["refreshToken"], "native clients receive the token in the body"

    @pytest.mark.parametrize(
        "email,password",
        [
            ("lifter@example.com", "the-wrong-password-entirely"),
            ("nobody@example.com", DEFAULT_PASSWORD),
        ],
        ids=["wrong password", "unknown email"],
    )
    async def test_failures_are_indistinguishable(
        self,
        client: AsyncClient,
        email_sender: CapturingEmailSender,
        email: str,
        password: str,
    ) -> None:
        """Wrong password and unknown email must return the same code and message."""
        await register_and_verify(client, email_sender)
        response = await client.post("/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
        assert response.json()["error"]["message"] == "Incorrect email or password."

    async def test_web_clients_receive_the_refresh_token_as_an_httponly_cookie(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        await register_and_verify(client, email_sender)
        response = await client.post(
            "/v1/auth/login",
            json={"email": "lifter@example.com", "password": DEFAULT_PASSWORD},
            headers={"X-Client-Version": "web/1.0"},
        )
        assert response.status_code == 200
        # Never in the body for a browser — that is what makes XSS unable to steal it.
        assert response.json()["refreshToken"] is None
        set_cookie = response.headers["set-cookie"]
        assert "coresync_refresh=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Path=/v1/auth" in set_cookie


class TestRefreshRotation:
    async def test_refresh_issues_a_new_pair(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        response = await client.post(
            "/v1/auth/refresh", json={"refreshToken": payload["refreshToken"]}
        )
        assert response.status_code == 200
        assert response.json()["refreshToken"] != payload["refreshToken"]

    async def test_replaying_a_rotated_token_kills_the_whole_family(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """The security property that makes rotation worth having.

        Without reuse detection a stolen refresh token is a permanent credential. With
        it, the first replay — by either party — ends every session in the chain.
        """
        payload = await register_and_verify(client, email_sender)
        original = payload["refreshToken"]

        rotated = await client.post("/v1/auth/refresh", json={"refreshToken": original})
        assert rotated.status_code == 200
        successor = rotated.json()["refreshToken"]

        replay = await client.post("/v1/auth/refresh", json={"refreshToken": original})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "token_reuse_detected"

        # The successor the legitimate client holds is dead too — it must re-authenticate.
        after = await client.post("/v1/auth/refresh", json={"refreshToken": successor})
        assert after.status_code == 401

    async def test_rejects_an_unknown_token(self, client: AsyncClient) -> None:
        response = await client.post("/v1/auth/refresh", json={"refreshToken": "y" * 43})
        assert response.status_code == 401


class TestLogout:
    async def test_logout_revokes_the_refresh_token(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        response = await client.post(
            "/v1/auth/logout",
            json={"refreshToken": payload["refreshToken"]},
            headers=auth_header(payload),
        )
        assert response.status_code == 200

        refused = await client.post(
            "/v1/auth/refresh", json={"refreshToken": payload["refreshToken"]}
        )
        assert refused.status_code == 401

    async def test_the_access_token_stops_working_immediately_after_logout(
        self, client: AsyncClient, email_sender: CapturingEmailSender, container
    ) -> None:
        """A JWT stays cryptographically valid after logout; the blocklist is what stops it."""
        payload = await register_and_verify(client, email_sender)
        await client.post(
            "/v1/auth/logout",
            json={"refreshToken": payload["refreshToken"]},
            headers=auth_header(payload),
        )
        assert len(container.revocation_store.revoked) == 1

        response = await client.get("/v1/users/me", headers=auth_header(payload))
        assert response.status_code == 401


class TestPasswordReset:
    async def test_forgot_password_always_returns_202(self, client: AsyncClient) -> None:
        """Identical for known and unknown addresses — otherwise it is an enumeration oracle."""
        known = await client.post("/v1/auth/password/forgot", json={"email": "lifter@example.com"})
        unknown = await client.post("/v1/auth/password/forgot", json={"email": "ghost@example.com"})
        assert known.status_code == unknown.status_code == 202
        assert known.json() == unknown.json()

    async def test_reset_changes_the_password_and_ends_every_session(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        await client.post("/v1/auth/password/forgot", json={"email": "lifter@example.com"})

        new_password = "a-brand-new-strong-passphrase-99"
        reset = await client.post(
            "/v1/auth/password/reset",
            json={"token": email_sender.token_from("password_reset"), "newPassword": new_password},
        )
        assert reset.status_code == 200

        # A reset often happens *because* of a compromise; leaving sessions alive would
        # make the whole flow theatre.
        stale = await client.post(
            "/v1/auth/refresh", json={"refreshToken": payload["refreshToken"]}
        )
        assert stale.status_code == 401

        assert (
            await client.post(
                "/v1/auth/login",
                json={"email": "lifter@example.com", "password": DEFAULT_PASSWORD},
            )
        ).status_code == 401
        assert (
            await client.post(
                "/v1/auth/login",
                json={"email": "lifter@example.com", "password": new_password},
            )
        ).status_code == 200

    async def test_a_reset_token_is_single_use(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        await register_and_verify(client, email_sender)
        await client.post("/v1/auth/password/forgot", json={"email": "lifter@example.com"})
        token = email_sender.token_from("password_reset")

        first = await client.post(
            "/v1/auth/password/reset",
            json={"token": token, "newPassword": "first-new-passphrase-2026"},
        )
        second = await client.post(
            "/v1/auth/password/reset",
            json={"token": token, "newPassword": "second-new-passphrase-2026"},
        )
        assert first.status_code == 200
        assert second.status_code == 401

    async def test_requesting_a_new_link_invalidates_the_previous_one(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        await register_and_verify(client, email_sender)
        await client.post("/v1/auth/password/forgot", json={"email": "lifter@example.com"})
        first_token = email_sender.token_from("password_reset")
        await client.post("/v1/auth/password/forgot", json={"email": "lifter@example.com"})

        stale = await client.post(
            "/v1/auth/password/reset",
            json={"token": first_token, "newPassword": "should-not-work-passphrase"},
        )
        assert stale.status_code == 401


class TestChangePassword:
    async def test_requires_the_current_password(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """Stops a stolen access token from being upgraded into account control."""
        payload = await register_and_verify(client, email_sender)
        response = await client.post(
            "/v1/auth/password/change",
            json={
                "currentPassword": "not-the-current-password",
                "newPassword": "a-different-strong-passphrase",
            },
            headers=auth_header(payload),
        )
        assert response.status_code == 401


class TestOAuth:
    async def test_google_sign_in_creates_an_active_account(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/oauth/google", json={"idToken": "valid-google-token"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["isNewUser"] is True
        # The provider already proved ownership, so there is nothing left to verify.
        assert body["user"]["emailVerified"] is True
        assert body["user"]["status"] == "active"

    async def test_signing_in_twice_reuses_the_same_account(self, client: AsyncClient) -> None:
        first = await client.post(
            "/v1/auth/oauth/google", json={"idToken": "valid-google-id-token"}
        )
        second = await client.post(
            "/v1/auth/oauth/google", json={"idToken": "valid-google-id-token"}
        )
        assert first.json()["user"]["id"] == second.json()["user"]["id"]
        assert second.json()["isNewUser"] is False

    async def test_rejects_an_invalid_id_token(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/oauth/google", json={"idToken": "invalid-google-id-token"}
        )
        assert response.status_code == 401

    async def test_links_to_an_existing_verified_account(
        self,
        client: AsyncClient,
        email_sender: CapturingEmailSender,
        google_verifier: FakeOidcVerifier,
    ) -> None:
        """Auto-linking is only safe when both sides assert a verified address."""
        await register_and_verify(client, email_sender, email="social@example.com")
        response = await client.post(
            "/v1/auth/oauth/google", json={"idToken": "valid-google-id-token"}
        )
        assert response.status_code == 200
        assert response.json()["isNewUser"] is False

    async def test_does_not_link_when_the_provider_email_is_unverified(
        self,
        client: AsyncClient,
        email_sender: CapturingEmailSender,
        google_verifier: FakeOidcVerifier,
    ) -> None:
        """Otherwise: register an unverified account with someone's address, then sign
        in through the provider and inherit theirs. Straightforward account takeover."""
        from coresync.application.common.ports import OidcIdentity

        await register_and_verify(client, email_sender, email="victim@example.com")
        google_verifier.identity = OidcIdentity(
            subject="attacker-subject",
            email="victim@example.com",
            email_verified=False,
            name="Attacker",
            provider="google",
        )
        first = await client.post(
            "/v1/auth/login", json={"email": "victim@example.com", "password": DEFAULT_PASSWORD}
        )
        victim_id = first.json()["user"]["id"]

        response = await client.post(
            "/v1/auth/oauth/google", json={"idToken": "valid-google-id-token"}
        )
        if response.status_code == 200:
            assert response.json()["user"]["id"] != victim_id


class TestOAuthAgainstAnUnverifiedAccount:
    """The branch docs/06 does not cover, and which used to return a 500.

    Auto-linking requires *both* sides to assert a verified address. When the provider
    verifies but the local account never did, linking is refused — that is the
    pre-hijacking attack, where somebody registers an account on your address, leaves it
    unverified, prepares it, and waits for you to sign in through Google and inherit it.

    Refusing was already correct. Falling through to `register` afterwards was not: the
    insert hit `uq_users_email_active` and the user saw a 500 with nothing actionable.
    """

    async def test_it_is_a_handled_conflict_not_a_crash(
        self,
        client: AsyncClient,
        email_sender: CapturingEmailSender,
        google_verifier: FakeOidcVerifier,
    ) -> None:
        email = "collides@example.com"
        registered = await client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": DEFAULT_PASSWORD,
                "displayName": "Never Verified",
                "timezone": "Europe/Athens",
                "acceptedTerms": True,
            },
        )
        assert registered.status_code == 201, registered.text
        # Deliberately not verifying — that is the whole condition under test.

        google_verifier.identity = OidcIdentity(
            subject="google-collision-subject",
            email=email,
            email_verified=True,
            name="Google User",
            provider="google",
        )

        response = await client.post(
            "/v1/auth/oauth/google", json={"idToken": "any-token-the-fake-accepts"}
        )

        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "unverified_account_exists"

    async def test_the_message_says_what_to_do(
        self,
        client: AsyncClient,
        email_sender: CapturingEmailSender,
        google_verifier: FakeOidcVerifier,
    ) -> None:
        """Naming the reason is safe here and nowhere else in the auth flow.

        Reaching this branch requires a provider-signed token for that exact address, so
        the caller has already proved they control it. Telling them an account exists on
        their own email leaks nothing.
        """
        email = "guidance@example.com"
        await client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": DEFAULT_PASSWORD,
                "displayName": "Never Verified",
                "timezone": "Europe/Athens",
                "acceptedTerms": True,
            },
        )
        google_verifier.identity = OidcIdentity(
            subject="google-guidance-subject",
            email=email,
            email_verified=True,
            name="Google User",
            provider="google",
        )

        response = await client.post("/v1/auth/oauth/google", json={"idToken": "a-token-long-enough-for-the-schema"})
        assert "password" in response.json()["error"]["message"].lower()

    async def test_a_verified_account_still_links(
        self,
        client: AsyncClient,
        email_sender: CapturingEmailSender,
        google_verifier: FakeOidcVerifier,
    ) -> None:
        """The happy path this fix must not have broken."""
        email = "verified@example.com"
        await register_and_verify(client, email_sender, email=email)

        google_verifier.identity = OidcIdentity(
            subject="google-verified-subject",
            email=email,
            email_verified=True,
            name="Google User",
            provider="google",
        )

        response = await client.post("/v1/auth/oauth/google", json={"idToken": "a-token-long-enough-for-the-schema"})
        assert response.status_code == 200, response.text
        assert response.json()["accessToken"]
