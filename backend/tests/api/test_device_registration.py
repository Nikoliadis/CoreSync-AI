"""Registering a device for push, and the authorization around it.

A push token is a delivery address for an *installation*, not for an account, and almost
every rule worth testing here follows from that. The one that matters most is
reassignment: when somebody signs into a different account on the same phone, the token
has to move. Leaving it attached to the previous user means their notifications — their
weight, their coach insights — arrive on a screen someone else is holding.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration


@pytest.fixture
async def headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender))


@pytest.fixture
async def other_headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    # A distinct address: the helper defaults to one, and two users sharing it would
    # collide on the unique email index.
    return auth_header(
        await register_and_verify(client, email_sender, email="second-lifter@example.com")
    )


def token(suffix: str = "") -> str:
    return f"ExponentPushToken[{uuid4().hex}{suffix}]"


async def register(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    push_token: str,
    platform: str = "ios",
    name: str | None = None,
):
    return await client.post(
        "/v1/users/me/devices",
        json={"platform": platform, "pushToken": push_token, "deviceName": name},
        headers=headers,
    )


class TestRegistration:
    async def test_registers_a_device(self, client: AsyncClient, headers: dict[str, str]) -> None:
        response = await register(client, headers, push_token=token(), name="Nikos iPhone")

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["platform"] == "ios"
        assert body["isActive"] is True
        assert body["hasPushToken"] is True

    async def test_never_returns_the_token_itself(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        # Listing devices is for recognising them. Echoing the delivery address back over
        # the wire earns nothing and widens where it can leak from.
        value = token()
        await register(client, headers, push_token=value)

        listed = await client.get("/v1/users/me/devices", headers=headers)
        assert value not in listed.text

    async def test_re_registering_the_same_token_updates_rather_than_duplicates(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        # The app re-registers on every launch. Without this it accumulates one device
        # per launch and every notification is delivered a dozen times.
        value = token()
        await register(client, headers, push_token=value, name="First")
        await register(client, headers, push_token=value, name="Second")

        listed = await client.get("/v1/users/me/devices", headers=headers)
        assert len(listed.json()) == 1
        assert listed.json()[0]["deviceName"] == "Second"

    async def test_supports_several_devices_for_one_user(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        await register(client, headers, push_token=token(), platform="ios", name="Phone")
        await register(client, headers, push_token=token(), platform="android", name="Tablet")

        listed = await client.get("/v1/users/me/devices", headers=headers)
        assert len(listed.json()) == 2

    async def test_a_token_moves_when_another_account_claims_it(
        self, client: AsyncClient, headers: dict[str, str], other_headers: dict[str, str]
    ) -> None:
        # The privacy case. Same phone, different account: the first user must stop
        # receiving notifications on it immediately.
        value = token()
        await register(client, headers, push_token=value)
        assert await register(client, other_headers, push_token=value) is not None

        first = await client.get("/v1/users/me/devices", headers=headers)
        assert all(device["hasPushToken"] is False for device in first.json()), (
            "the previous owner must no longer hold a deliverable token"
        )

        second = await client.get("/v1/users/me/devices", headers=other_headers)
        assert any(device["hasPushToken"] for device in second.json())

    async def test_rejects_an_unknown_platform(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await register(client, headers, push_token=token(), platform="blackberry")
        assert response.status_code == 400

    async def test_rejects_an_empty_token(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await register(client, headers, push_token="")
        assert response.status_code == 400

    async def test_rejects_an_absurdly_long_token(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await register(client, headers, push_token="x" * 600)
        assert response.status_code == 400

    async def test_registration_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/users/me/devices",
            json={"platform": "ios", "pushToken": token()},
        )
        assert response.status_code == 401


class TestUnregistration:
    async def test_removes_a_device_by_id(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        created = await register(client, headers, push_token=token())
        device_id = created.json()["id"]

        response = await client.delete(f"/v1/users/me/devices/{device_id}", headers=headers)
        assert response.status_code == 204

        listed = await client.get("/v1/users/me/devices", headers=headers)
        assert listed.json() == []

    async def test_cannot_remove_another_users_device(
        self, client: AsyncClient, headers: dict[str, str], other_headers: dict[str, str]
    ) -> None:
        created = await register(client, headers, push_token=token())
        device_id = created.json()["id"]

        response = await client.delete(f"/v1/users/me/devices/{device_id}", headers=other_headers)
        # 404 rather than 403: a different answer would confirm the device exists.
        assert response.status_code == 404

        still_there = await client.get("/v1/users/me/devices", headers=headers)
        assert len(still_there.json()) == 1

    async def test_removes_by_token_for_sign_out(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        value = token()
        await register(client, headers, push_token=value)

        response = await client.post(
            "/v1/users/me/devices/unregister", json={"pushToken": value}, headers=headers
        )
        assert response.status_code == 204

        listed = await client.get("/v1/users/me/devices", headers=headers)
        assert listed.json() == []

    async def test_unregistering_an_unknown_token_is_silent(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        # Sign-out must not fail because the token was already gone.
        response = await client.post(
            "/v1/users/me/devices/unregister", json={"pushToken": token()}, headers=headers
        )
        assert response.status_code == 204

    async def test_cannot_unregister_another_users_token(
        self, client: AsyncClient, headers: dict[str, str], other_headers: dict[str, str]
    ) -> None:
        value = token()
        await register(client, headers, push_token=value)

        response = await client.post(
            "/v1/users/me/devices/unregister", json={"pushToken": value}, headers=other_headers
        )
        assert response.status_code == 204, "silent, but it must not have removed anything"

        listed = await client.get("/v1/users/me/devices", headers=headers)
        assert len(listed.json()) == 1

    async def test_listing_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/users/me/devices")).status_code == 401
