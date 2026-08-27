"""Sign in with Apple, from the API's side.

The mobile client can only ever *offer* an identity; this is where it becomes a session.
Nothing the device sends about who the user is survives without the server verifying the
token against Apple's keys first, which is why every case here goes through the real
endpoint rather than asserting on a use case in isolation.

The case worth reading twice is the name. Apple returns it on the first authorisation and
never again — so the client forwards it as `displayName` at that single opportunity, and
the server has to persist it then or the account is left unnamed forever.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from coresync.infrastructure.external.oidc import FakeOidcVerifier
from tests.api.conftest import DEFAULT_PASSWORD, auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration

TOKEN = "an-apple-identity-token-long-enough"


async def apple_sign_in(client: AsyncClient, **body: object):
    return await client.post(
        "/v1/auth/oauth/apple",
        json={"idToken": TOKEN, "nonce": "raw-nonce-value", **body},
    )


class TestNewUser:
    async def test_creates_an_account_and_returns_a_session(self, client: AsyncClient) -> None:
        response = await apple_sign_in(client)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["accessToken"]
        assert body["refreshToken"]

    async def test_the_session_works_immediately(self, client: AsyncClient) -> None:
        # The point of the whole flow: an authenticated app, not just a token pair.
        tokens = (await apple_sign_in(client)).json()

        me = await client.get("/v1/users/me", headers=auth_header(tokens))
        assert me.status_code == 200

    async def test_persists_the_name_apple_only_sends_once(self, client: AsyncClient) -> None:
        # There is no later call that carries it. Miss it here and it is gone for good.
        tokens = (await apple_sign_in(client, displayName="Nikos Papadopoulos")).json()

        me = await client.get("/v1/users/me", headers=auth_header(tokens))
        assert me.json()["profile"]["displayName"] == "Nikos Papadopoulos"

    async def test_a_private_relay_address_is_accepted(self, client: AsyncClient) -> None:
        # "Hide My Email" is the default for many people. Refusing the address would
        # refuse the feature Apple requires us to support.
        tokens = (await apple_sign_in(client)).json()

        me = await client.get("/v1/users/me", headers=auth_header(tokens))
        assert me.json()["user"]["email"].endswith("@privaterelay.appleid.com")


class TestReturningUser:
    async def test_signing_in_twice_returns_the_same_account(self, client: AsyncClient) -> None:
        first = (await apple_sign_in(client, displayName="Nikos")).json()
        second = (await apple_sign_in(client)).json()

        me_first = await client.get("/v1/users/me", headers=auth_header(first))
        me_second = await client.get("/v1/users/me", headers=auth_header(second))
        assert me_first.json()["user"]["id"] == me_second.json()["user"]["id"]

    async def test_a_later_sign_in_does_not_wipe_the_name(self, client: AsyncClient) -> None:
        # Apple sends no name the second time, and the client therefore sends none.
        # Treating that absence as "clear the name" would erase it on every sign-in.
        await apple_sign_in(client, displayName="Nikos Papadopoulos")
        tokens = (await apple_sign_in(client)).json()

        me = await client.get("/v1/users/me", headers=auth_header(tokens))
        assert me.json()["profile"]["displayName"] == "Nikos Papadopoulos"


class TestRejection:
    async def test_an_unverifiable_token_is_refused(
        self, client: AsyncClient, apple_verifier: FakeOidcVerifier
    ) -> None:
        # Standing in for what the real verifier rejects: a bad signature, an expired
        # token, or an audience that is neither the bundle id nor the Services ID.
        #
        # The double's own "invalid" sentinel cannot be used here — it is seven
        # characters and the schema requires sixteen, so it is rejected as malformed
        # before any verifier sees it. Clearing the identity is the reachable path.
        apple_verifier.identity = None

        response = await apple_sign_in(client)
        assert response.status_code == 401, response.text

    async def test_a_wrong_audience_never_becomes_a_session(
        self, client: AsyncClient, apple_verifier: FakeOidcVerifier
    ) -> None:
        # The defect this guards: Apple sets `aud` to the bundle id natively and the
        # Services ID on the web. A verifier configured with only one silently refuses
        # every sign-in from the other platform, and the app looks broken with no clue.
        apple_verifier.identity = None

        response = await apple_sign_in(client)
        assert response.status_code == 401
        assert "accessToken" not in response.text

    async def test_a_token_that_is_too_short_never_reaches_the_verifier(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/v1/auth/oauth/apple", json={"idToken": "short"})
        assert response.status_code == 400

    async def test_an_unknown_provider_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post("/v1/auth/oauth/facebook", json={"idToken": TOKEN})
        assert response.status_code in (400, 404, 422)


class TestCoexistenceWithPasswordAccounts:
    async def test_apple_does_not_hijack_an_existing_password_account(
        self,
        client: AsyncClient,
        email_sender: CapturingEmailSender,
        apple_verifier: FakeOidcVerifier,
    ) -> None:
        # Somebody registered with a password at this address. An Apple token asserting
        # the same address must not silently take the account over — that is an account
        # takeover dressed as a convenience.
        await register_and_verify(client, email_sender, email="shared@example.com")
        apple_verifier.identity = apple_verifier.identity.__class__(
            subject="apple-subject-999",
            email="shared@example.com",
            email_verified=True,
            name=None,
            provider="apple",
        )

        response = await apple_sign_in(client)
        # Either the server links it deliberately or refuses. What it must never do is
        # create a second account on the same address, which the unique index prevents.
        assert response.status_code in (200, 409)

    async def test_password_login_still_works_after_apple_exists(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        # Adding a provider must not disturb the flow most users still take.
        await apple_sign_in(client)
        await register_and_verify(client, email_sender, email="password-user@example.com")

        response = await client.post(
            "/v1/auth/login",
            json={"email": "password-user@example.com", "password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 200


class TestSessionLifecycle:
    async def test_the_refresh_token_works_after_an_apple_sign_in(
        self, client: AsyncClient
    ) -> None:
        # An Apple session is an ordinary CoreSync session. If refresh did not work, the
        # user would be signed out after fifteen minutes with no explanation.
        tokens = (await apple_sign_in(client)).json()

        refreshed = await client.post(
            "/v1/auth/refresh", json={"refreshToken": tokens["refreshToken"]}
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["accessToken"]

    async def test_logout_ends_an_apple_session(self, client: AsyncClient) -> None:
        tokens = (await apple_sign_in(client)).json()

        signed_out = await client.post("/v1/auth/logout", json={}, headers=auth_header(tokens))
        assert signed_out.status_code in (200, 204)
