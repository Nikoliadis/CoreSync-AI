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

    async def add(self, device: UserDevice) -> None: ...

    async def touch(self, device_id: UUID, now: datetime) -> None: ...
