"""Application-level ports.

Sending email, revoking a token and verifying an OIDC assertion are orchestration
concerns rather than domain rules, so their contracts live here. Implementations are in
``infrastructure``; tests substitute fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID


class EmailSender(Protocol):
    async def send_verification(self, *, to: str, name: str, verify_url: str) -> None: ...

    async def send_password_reset(self, *, to: str, name: str, reset_url: str) -> None: ...

    async def send_password_changed(self, *, to: str, name: str) -> None: ...

    async def send_account_exists_notice(self, *, to: str, sign_in_url: str) -> None:
        """Sent when someone attempts to register an address that already has an account.

        The registration endpoint returns an identical response either way, so this
        email is the only signal — and it goes to the address owner, not the caller.
        """
        ...


class TokenRevocationStore(Protocol):
    """Immediate revocation for access tokens that are still cryptographically valid.

    A JWT stays valid until it expires, so logout would otherwise leave a usable
    credential in an attacker's hands for up to the access-token TTL. Entries are held
    only until the token's natural expiry, so the store stays small.
    """

    async def revoke(self, jti: UUID, ttl: timedelta) -> None: ...

    async def is_revoked(self, jti: UUID) -> bool: ...


class BreachedPasswordChecker(Protocol):
    async def is_breached(self, password: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class OidcIdentity:
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    provider: str


class OidcVerifier(Protocol):
    """Verifies a provider ID token server-side.

    Always server-side: trusting a client-reported verification result would let anyone
    sign in as anyone with a crafted request.
    """

    async def verify(self, id_token: str, *, nonce: str | None = None) -> OidcIdentity: ...


class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window: timedelta) -> tuple[bool, int]:
        """Register an attempt. Returns ``(allowed, seconds_until_reset)``.

        **An implementation that cannot reach its counter store must allow the request**
        rather than raise. Rate limiting is fairness, not authorisation: refusing every
        request because the counter store is unreachable converts a degraded dependency
        into a total outage. Readiness reports the store separately, so the lost limiting
        is visible to alerting instead of silent.
        """
        ...

    async def reset(self, key: str) -> None:
        """Clear a counter. Best-effort — failure must not fail the caller's operation."""
        ...


@dataclass(frozen=True, slots=True)
class ExternalFood:
    """A product from an outside catalogue, before it becomes a row of ours."""

    barcode: str
    name: str
    brand: str | None
    calories_per_100g: Decimal
    protein_per_100g: Decimal
    carbs_per_100g: Decimal
    fat_per_100g: Decimal
    alcohol_per_100g: Decimal
    is_liquid: bool
    serving_grams: Decimal | None = None


class ExternalFoodLookup(Protocol):
    """Somewhere to ask when a scanned barcode is not in our catalogue.

    Returns ``None`` for a miss *and* for an outage: a scan that cannot be resolved is
    "we don't have that yet", never an error page. The caller cannot tell the difference
    and should not need to.
    """

    async def by_barcode(self, barcode: str) -> ExternalFood | None: ...
