"""Repository ports for the identity domain.

Declared here — in the domain — and implemented in ``infrastructure``. That inversion
is what lets the domain stay free of SQLAlchemy and what makes these substitutable with
in-memory fakes in unit tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from coresync.domain.identity.entities import (
    AuthIdentity,
    AuthProvider,
    RefreshToken,
    SingleUseToken,
    TokenPurpose,
    User,
    UserDevice,
)


class UserRepository(Protocol):
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def email_exists(self, email: str) -> bool: ...

    async def add(self, user: User) -> None: ...

    async def update(self, user: User) -> None: ...

    async def list_due_for_erasure(self, *, cutoff: datetime, limit: int) -> list[UUID]:
        """Accounts soft-deleted before ``cutoff`` and not yet erased.

        The cutoff is the user's protection and this query is the only thing enforcing
        it, so it belongs in the predicate rather than in a filter afterwards.
        """
        ...

    async def erase(self, user_id: UUID, *, at: datetime) -> None:
        """Strip personal data, keep the anonymised row and derived aggregates.

        Idempotent: an account already erased is left alone, so a job that fails midway
        is safe to run again.
        """
        ...


class AuthIdentityRepository(Protocol):
    async def get_by_provider_subject(
        self, provider: AuthProvider, subject: str
    ) -> AuthIdentity | None: ...

    async def list_for_user(self, user_id: UUID) -> list[AuthIdentity]: ...

    async def add(self, identity: AuthIdentity) -> None: ...

    async def delete(self, identity_id: UUID, user_id: UUID) -> None: ...


class RefreshTokenRepository(Protocol):
    async def get_by_hash(self, token_hash: bytes) -> RefreshToken | None: ...

    async def add(self, token: RefreshToken) -> None: ...

    async def update(self, token: RefreshToken) -> None: ...

    async def revoke_family(self, token_id: UUID, now: datetime, reason: str) -> int:
        """Revoke an entire rotation chain, in both directions from ``token_id``.

        Called when a rotated token is replayed. Returns the number revoked, which is
        logged as a security event.
        """
        ...

    async def revoke_all_for_user(self, user_id: UUID, now: datetime, reason: str) -> int: ...

    async def list_active_for_user(self, user_id: UUID, now: datetime) -> list[RefreshToken]: ...


class SingleUseTokenRepository(Protocol):
    async def get_by_hash(
        self, token_hash: bytes, purpose: TokenPurpose
    ) -> SingleUseToken | None: ...

    async def add(self, token: SingleUseToken) -> None: ...

    async def update(self, token: SingleUseToken) -> None: ...

    async def invalidate_outstanding(
        self, user_id: UUID, purpose: TokenPurpose, now: datetime
    ) -> None:
        """Consume any unused tokens of this purpose.

        Requesting a new reset link must invalidate the previous one — otherwise every
        link ever emailed stays live until it expires.
        """
        ...


class UserDeviceRepository(Protocol):
    async def get(self, device_id: UUID, user_id: UUID) -> UserDevice | None: ...

    async def list_for_user(self, user_id: UUID) -> list[UserDevice]:
        """Every registered device. Used to decide whether a push is deliverable."""
        ...

    async def get_by_push_token(self, token: str) -> UserDevice | None:
        """Whoever currently holds this token, regardless of user.

        Needed because a token follows the *installation*, not the account: signing in as
        somebody else on the same phone must move the token rather than leave it pointing
        at the previous user, who would otherwise keep receiving their notifications.
        """
        ...

    async def list_deliverable(self, user_id: UUID) -> list[UserDevice]:
        """Active devices holding a token. What the dispatcher actually sends to."""
        ...

    async def add(self, device: UserDevice) -> None: ...

    async def update(self, device: UserDevice) -> None: ...

    async def remove(self, device_id: UUID, user_id: UUID) -> bool:
        """Delete one device. Returns whether it existed and belonged to the user."""
        ...

    async def deactivate_token(self, token: str) -> None:
        """Stop sending to a token the provider has rejected."""
        ...

    async def touch(self, device_id: UUID, now: datetime) -> None: ...
