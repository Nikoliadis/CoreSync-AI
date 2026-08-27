"""The Expo push adapter, and above all how it classifies failure.

Most push failures are not transient, and treating them as though they were is how an
outbox grinds against a wall forever. The three outcomes this has to keep apart:

- the token is dead and must never be sent to again
- the request was wrong and will be just as wrong next time
- the network had a bad moment and another attempt is worth it

Getting the first one wrong is the expensive mistake: every future notification for that
user spends an attempt on a phone the app was deleted from.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest

from coresync.core.ids import uuid7
from coresync.domain.notifications.entities import Notification, NotificationCategory
from coresync.infrastructure.notifications.push import (
    ExpoPushSender,
    PushDeliveryError,
    _message,
)


def notification(**overrides: Any) -> Notification:
    return Notification(
        id=uuid7(),
        user_id=UUID(int=1),
        category=NotificationCategory.PR_CELEBRATION,
        title="New record",
        body="You beat your bench press.",
        deep_link="/workout/abc",
        data={},
        **overrides,
    )


def responder(payload: Any, status_code: int = 200):
    """An httpx client whose every request returns this payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status_code, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestMessageShape:
    def test_carries_the_deep_link_so_a_tap_can_route(self) -> None:
        # Without this the app has to fetch the notification before it knows where to go,
        # which is a network round trip during the one interaction that must feel instant.
        message = _message(notification(), "ExponentPushToken[x]")

        assert message["data"]["deepLink"] == "/workout/abc"
        assert message["data"]["category"] == "pr_celebration"

    def test_addresses_exactly_one_token(self) -> None:
        message = _message(notification(), "ExponentPushToken[x]")
        assert message["to"] == "ExponentPushToken[x]"

    def test_groups_by_category_so_lock_screens_do_not_stack(self) -> None:
        message = _message(notification(), "ExponentPushToken[x]")
        assert message["channelId"] == "pr_celebration"


class TestDelivery:
    async def test_counts_a_successful_ticket(self) -> None:
        async with responder({"data": [{"status": "ok"}]}) as client:
            sender = ExpoPushSender(client=client)
            result = await sender.send_to_tokens(notification(), ["ExponentPushToken[a]"])

        assert result.delivered == 1
        assert result.dead_tokens == []

    async def test_sends_nothing_for_an_empty_token_list(self) -> None:
        sender = ExpoPushSender(client=responder({"data": []}))
        result = await sender.send_to_tokens(notification(), [])

        assert result.delivered == 0

    async def test_reports_a_dead_token_rather_than_raising(self) -> None:
        # DeviceNotRegistered is permanent. Raising would make the outbox retry it, and
        # it would fail identically every time until the attempts ran out.
        body = {
            "data": [
                {"status": "error", "message": "gone", "details": {"error": "DeviceNotRegistered"}}
            ]
        }
        async with responder(body) as client:
            result = await ExpoPushSender(client=client).send_to_tokens(
                notification(), ["ExponentPushToken[gone]"]
            )

        assert result.dead_tokens == ["ExponentPushToken[gone]"]
        assert result.delivered == 0

    async def test_separates_dead_tokens_from_healthy_ones_in_one_batch(self) -> None:
        body = {
            "data": [
                {"status": "ok"},
                {"status": "error", "details": {"error": "DeviceNotRegistered"}},
            ]
        }
        async with responder(body) as client:
            result = await ExpoPushSender(client=client).send_to_tokens(
                notification(), ["ExponentPushToken[good]", "ExponentPushToken[gone]"]
            )

        assert result.delivered == 1
        assert result.dead_tokens == ["ExponentPushToken[gone]"]

    async def test_a_permanent_error_does_not_condemn_the_token(self) -> None:
        # MessageTooBig is our bug, not the device's. Deactivating the device would
        # punish the user for something we did.
        body = {"data": [{"status": "error", "details": {"error": "MessageTooBig"}}]}
        async with responder(body) as client:
            result = await ExpoPushSender(client=client).send_to_tokens(
                notification(), ["ExponentPushToken[a]"]
            )

        assert result.dead_tokens == []
        assert result.permanent_failures == ["ExponentPushToken[a]"]


class TestRetryClassification:
    async def test_a_transport_error_is_retryable(self) -> None:
        async with responder(httpx.ConnectError("no route")) as client:
            with pytest.raises(PushDeliveryError):
                await ExpoPushSender(client=client).send_to_tokens(
                    notification(), ["ExponentPushToken[a]"]
                )

    async def test_a_server_error_is_retryable(self) -> None:
        async with responder({}, status_code=503) as client:
            with pytest.raises(PushDeliveryError):
                await ExpoPushSender(client=client).send_to_tokens(
                    notification(), ["ExponentPushToken[a]"]
                )

    async def test_a_client_error_is_not_retryable(self) -> None:
        # A 4xx means the request was wrong. Sending the identical request again is waste.
        async with responder({"errors": [{"code": "BAD"}]}, status_code=400) as client:
            result = await ExpoPushSender(client=client).send_to_tokens(
                notification(), ["ExponentPushToken[a]"]
            )

        assert result.permanent_failures == ["ExponentPushToken[a]"]
        assert result.delivered == 0

    async def test_an_unrecognised_error_is_treated_as_retryable(self) -> None:
        # A provider that invents a new error code must not silently swallow somebody's
        # notification. Better to retry and eventually surface it than to drop it.
        body = {"data": [{"status": "error", "details": {"error": "SomethingNew"}}]}
        async with responder(body) as client:
            with pytest.raises(PushDeliveryError):
                await ExpoPushSender(client=client).send_to_tokens(
                    notification(), ["ExponentPushToken[a]"]
                )

    async def test_a_malformed_response_is_retryable(self) -> None:
        async with responder({"unexpected": True}) as client:
            with pytest.raises(PushDeliveryError):
                await ExpoPushSender(client=client).send_to_tokens(
                    notification(), ["ExponentPushToken[a]"]
                )


class TestCredentials:
    async def test_no_authorization_header_without_an_access_token(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return httpx.Response(200, json={"data": [{"status": "ok"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await ExpoPushSender(client=client).send_to_tokens(
                notification(), ["ExponentPushToken[a]"]
            )

        assert "authorization" not in seen

    async def test_the_access_token_is_sent_server_side_only(self) -> None:
        # It lives in server settings and reaches the provider. It must never be part of
        # anything the client is given, which is why it is a constructor argument here
        # rather than something the message carries.
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return httpx.Response(200, json={"data": [{"status": "ok"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await ExpoPushSender(client=client, access_token="secret-value").send_to_tokens(
                notification(), ["ExponentPushToken[a]"]
            )

        assert seen["authorization"] == "Bearer secret-value"
