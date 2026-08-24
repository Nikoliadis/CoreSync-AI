"""Identity domain entities.

Plain Python. No ORM, no framework, no I/O — so the rules below are testable in
microseconds and survive a change of persistence technology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from coresync.core.ids import uuid7


class UserRole(StrEnum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    # Soft-deleted, still inside the grace period, still recoverable by the user.
    DELETED = "deleted"
    # Erasure has run. The row is an anonymous shell kept so derived aggregates stay
    # meaningful; it is never recoverable and never counted as a user.
    ERASED = "erased"


class AuthProvider(StrEnum):
    GOOGLE = "google"
    APPLE = "apple"


@dataclass(slots=True)
class User:
    id: UUID
    email: str
    password_hash: str | None
    role: UserRole
    status: UserStatus
    timezone: str
    email_verified_at: datetime | None = None
    last_login_at: datetime | None = None
    failed_login_count: int = 0
    locked_until: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None

    # -------------------------------------------------------------- construction
    @classmethod
    def register(
        cls,
        *,
        email: str,
        password_hash: str | None,
        timezone: str,
        now: datetime,
        email_verified: bool = False,
    ) -> User:
        """Create a new account.

        ``email_verified`` is True only for social sign-up, where the provider has
        already proven ownership of the address.
        """
        return cls(
            id=uuid7(),
            email=email.strip().lower(),
            password_hash=password_hash,
            role=UserRole.USER,
            # Social sign-ups skip the pending state — there is nothing left to verify.
            status=UserStatus.ACTIVE if email_verified else UserStatus.PENDING,
            timezone=timezone,
            email_verified_at=now if email_verified else None,
            created_at=now,
        )

    # ------------------------------------------------------------------ queries
    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def can_authenticate(self) -> bool:
        return not self.is_deleted and self.status in (UserStatus.PENDING, UserStatus.ACTIVE)

    def is_locked_at(self, now: datetime) -> bool:
        return self.locked_until is not None and self.locked_until > now

    def lock_seconds_remaining(self, now: datetime) -> int:
        if self.locked_until is None or self.locked_until <= now:
            return 0
        return int((self.locked_until - now).total_seconds())

    # ------------------------------------------------------------------ commands
    def record_failed_login(self, now: datetime, *, max_attempts: int, lockout: timedelta) -> None:
        """Count a failed attempt and lock the account once the threshold is crossed.

        The lock is time-bounded rather than permanent: a permanent lock on failed
        attempts is itself a denial-of-service vector against any known address.
        """
        self.failed_login_count += 1
        if self.failed_login_count >= max_attempts:
            self.locked_until = now + lockout
            self.failed_login_count = 0

    def record_successful_login(self, now: datetime) -> None:
        self.failed_login_count = 0
        self.locked_until = None
        self.last_login_at = now

    def verify_email(self, now: datetime) -> None:
        if self.email_verified_at is None:
            self.email_verified_at = now
        if self.status is UserStatus.PENDING:
            self.status = UserStatus.ACTIVE

    def change_password(self, password_hash: str) -> None:
        self.password_hash = password_hash

    def schedule_deletion(self, now: datetime) -> None:
        """Soft-delete with a grace period. Hard erasure is a separate, later job."""
        self.deleted_at = now
        self.status = UserStatus.DELETED

    @property
    def is_erased(self) -> bool:
        return self.status is UserStatus.ERASED

    def cancel_deletion(self) -> None:
        self.deleted_at = None
        self.status = UserStatus.ACTIVE if self.is_email_verified else UserStatus.PENDING


@dataclass(slots=True)
class AuthIdentity:
    """A link between a CoreSync account and an external identity provider."""

    id: UUID
    user_id: UUID
    provider: AuthProvider
    provider_subject: str
    provider_email: str | None
    linked_at: datetime

    @classmethod
    def link(
        cls,
        *,
        user_id: UUID,
        provider: AuthProvider,
        subject: str,
        email: str | None,
        now: datetime,
    ) -> AuthIdentity:
        return cls(
            id=uuid7(),
            user_id=user_id,
            provider=provider,
            provider_subject=subject,
            provider_email=email.lower() if email else None,
            linked_at=now,
        )


@dataclass(slots=True)
class RefreshToken:
    """One row per active session per device.

    ``replaced_by`` chains rotations together. Presenting a token that has already been
    rotated proves the chain is compromised, and the whole family is revoked — this is
    the mechanism that makes a stolen refresh token useless rather than permanent.
    """

    id: UUID
    user_id: UUID
    token_hash: bytes
    expires_at: datetime
    device_id: UUID | None = None
    replaced_by: UUID | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    created_ip: str | None = None
    user_agent: str | None = None
    created_at: datetime | None = None

    @classmethod
    def issue(
        cls,
        *,
        user_id: UUID,
        token_hash: bytes,
        ttl: timedelta,
        now: datetime,
        device_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> RefreshToken:
        return cls(
            id=uuid7(),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=now + ttl,
            device_id=device_id,
            created_ip=ip,
            user_agent=user_agent,
            created_at=now,
        )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired_at(self, now: datetime) -> bool:
        return self.expires_at <= now

    def is_usable_at(self, now: datetime) -> bool:
        return not self.is_revoked and not self.is_expired_at(now)

    def rotate_to(self, successor: RefreshToken, now: datetime) -> None:
        self.revoked_at = now
        self.revoked_reason = "rotated"
        self.replaced_by = successor.id

    def revoke(self, now: datetime, reason: str) -> None:
        if self.revoked_at is None:
            self.revoked_at = now
            self.revoked_reason = reason


class TokenPurpose(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # noqa: S105 — an enum label, not a secret


@dataclass(slots=True)
class SingleUseToken:
    """Email verification and password reset share a shape: hashed, expiring, one-shot."""

    id: UUID
    user_id: UUID
    purpose: TokenPurpose
    token_hash: bytes
    expires_at: datetime
    used_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        purpose: TokenPurpose,
        token_hash: bytes,
        ttl: timedelta,
        now: datetime,
    ) -> SingleUseToken:
        return cls(
            id=uuid7(),
            user_id=user_id,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=now + ttl,
            created_at=now,
        )

    def is_usable_at(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now

    def consume(self, now: datetime) -> None:
        self.used_at = now


@dataclass(slots=True)
class UserDevice:
    id: UUID
    user_id: UUID
    platform: str
    device_name: str | None = None
    push_token: str | None = None
    last_seen_at: datetime | None = None
    fields_: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls, *, user_id: UUID, platform: str, device_name: str | None, now: datetime
    ) -> UserDevice:
        return cls(
            id=uuid7(),
            user_id=user_id,
            platform=platform,
            device_name=device_name,
            last_seen_at=now,
        )
