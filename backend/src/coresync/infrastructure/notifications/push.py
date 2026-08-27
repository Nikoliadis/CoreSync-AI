"""Expo push delivery.

Expo's push service is used rather than APNs and FCM directly, because it is what an Expo
app's tokens are issued by and it fans out to both. No provider credential is required for
unauthenticated sends, and where an access token *is* configured it lives in server
settings and never reaches the app — the client only ever holds its own device token,
which is a delivery address rather than a secret.

The important behaviour here is what happens when a send fails, because most push failures
are not transient:

- ``DeviceNotRegistered`` means the app was uninstalled or permission was revoked. Retrying
  is pointless forever. The token is reported back so the caller can deactivate it.
- ``MessageTooBig`` / ``InvalidCredentials`` are our bugs or our configuration, and retrying
  changes nothing.
- A network error or a 5xx is genuinely transient and worth another attempt.

Distinguishing those is the difference between a queue that drains and one that grinds
against a wall forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from coresync.core.logging import get_logger
from coresync.domain.notifications.entities import Notification

logger = get_logger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

#: Expo accepts at most 100 messages per request.
MAX_BATCH = 100

_TIMEOUT = 15.0

#: Errors that mean "never send to this token again".
_DEAD_TOKEN_ERRORS = frozenset({"DeviceNotRegistered"})

#: Errors that will not improve on a retry, but do not condemn the token either.
_PERMANENT_ERRORS = frozenset({"MessageTooBig", "MessageRateExceeded", "InvalidCredentials"})


class PushDeliveryError(Exception):
    """Raised when a send failed in a way that is worth retrying."""


@dataclass(slots=True)
class PushResult:
    """What happened, per token."""

    delivered: int = 0
    #: Tokens the provider says are dead. The caller deactivates these.
    dead_tokens: list[str] = field(default_factory=list)
    #: Failures that are not worth retrying but do not condemn the token.
    permanent_failures: list[str] = field(default_factory=list)

    @property
    def anything_delivered(self) -> bool:
        return self.delivered > 0


def _message(notification: Notification, token: str) -> dict[str, Any]:
    return {
        "to": token,
        "title": notification.title,
        "body": notification.body,
        # Carried through so the app can route the tap without another request. The deep
        # link is the whole reason a notification is worth tapping.
        "data": {
            "notificationId": str(notification.id),
            "category": notification.category.value,
            "deepLink": notification.deep_link,
            **(notification.data or {}),
        },
        "sound": "default",
        # Collapses an older unread notification of the same kind rather than stacking
        # five streak warnings on a lock screen.
        "channelId": notification.category.value,
    }


class ExpoPushSender:
    """Sends to every device a user has, in one request.

    Stateless with respect to the database on purpose: it is handed the tokens and reports
    what happened, and the caller — which owns the unit of work — decides what to write.
    Giving a provider adapter its own database session is how a transaction ends up open
    across a network call to a third party.
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        client: httpx.AsyncClient | None = None,
        url: str = EXPO_PUSH_URL,
    ) -> None:
        self._access_token = access_token
        self._client = client
        self._url = url

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }
        if self._access_token:
            # Server-side only. This never appears in a client build.
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def send_to_tokens(self, notification: Notification, tokens: list[str]) -> PushResult:
        if not tokens:
            return PushResult()

        result = PushResult()
        for start in range(0, len(tokens), MAX_BATCH):
            chunk = tokens[start : start + MAX_BATCH]
            await self._send_chunk(notification, chunk, result)
        return result

    async def _send_chunk(
        self, notification: Notification, tokens: list[str], result: PushResult
    ) -> None:
        payload = [_message(notification, token) for token in tokens]

        try:
            if self._client is not None:
                response = await self._client.post(
                    self._url, json=payload, headers=self._headers(), timeout=_TIMEOUT
                )
            else:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    response = await client.post(self._url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            # Transient by nature. Raised so the outbox retries on its own schedule.
            raise PushDeliveryError(f"push transport failed: {exc}") from exc

        if response.status_code >= 500:
            raise PushDeliveryError(f"expo returned {response.status_code}")
        if response.status_code >= 400:
            # 4xx is our request being wrong. Retrying an identical bad request is waste.
            logger.warning(
                "push_request_rejected",
                status=response.status_code,
                body=response.text[:200],
            )
            result.permanent_failures.extend(tokens)
            return

        try:
            body = response.json()
        except ValueError as exc:
            raise PushDeliveryError("expo returned a non-JSON body") from exc

        tickets = body.get("data")
        if not isinstance(tickets, list):
            raise PushDeliveryError("expo response had no ticket list")

        for token, ticket in zip(tokens, tickets, strict=False):
            if not isinstance(ticket, dict):
                result.permanent_failures.append(token)
                continue

            if ticket.get("status") == "ok":
                result.delivered += 1
                continue

            error = (ticket.get("details") or {}).get("error")
            if error in _DEAD_TOKEN_ERRORS:
                # The app is gone from this device. Recorded so the caller stops sending.
                result.dead_tokens.append(token)
                logger.info("push_token_dead", error=error)
            elif error in _PERMANENT_ERRORS:
                result.permanent_failures.append(token)
                logger.warning("push_permanent_failure", error=error)
            else:
                # Unknown failures are treated as retryable: a provider that invents a
                # new error code should not silently swallow somebody's notifications.
                raise PushDeliveryError(f"push failed: {ticket.get('message') or error}")


class NullPushSender:
    """Accepts everything and delivers nothing.

    For environments with no provider configured. Distinct from having *no* sender
    registered, which makes the dispatcher skip the channel — this one exists so tests
    can exercise the full path without reaching the network.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[Notification, list[str]]] = []

    async def send_to_tokens(self, notification: Notification, tokens: list[str]) -> PushResult:
        self.sent.append((notification, list(tokens)))
        return PushResult(delivered=len(tokens))
