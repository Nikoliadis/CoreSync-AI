"""ORM models for the identity domain.

These are persistence concerns — columns, constraints, indexes. They are deliberately
separate types from the domain entities; ``mappers.py`` translates between them.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from coresync.infrastructure.database.base import Base, TimestampMixin


class UserModel(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)  # NULL ⇒ social-only account
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("role IN ('user','moderator','admin')", name="role_valid"),
        CheckConstraint(
            "status IN ('pending','active','suspended','deleted')", name="status_valid"
        ),
        CheckConstraint("length(email) BETWEEN 3 AND 320", name="email_len"),
        # Partial unique index: a hard-deleted user's address can be reused, live ones
        # cannot collide.
        Index(
            "uq_users_email_active",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_users_status", "status", postgresql_where=text("deleted_at IS NULL")),
    )


class AuthIdentityModel(Base):
    __tablename__ = "auth_identities"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    # The OIDC `sub`. Stable forever for a given provider account.
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(CITEXT)
    raw_profile: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("provider IN ('google','apple')", name="provider_valid"),
        # Stops one Google account from claiming two CoreSync accounts.
        UniqueConstraint("provider", "provider_subject", name="uq_auth_identity"),
        Index("ix_auth_identities_user", "user_id"),
    )


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the token. The plaintext is never stored.
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    device_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_devices.id", ondelete="SET NULL")
    )
    # Rotation chain. Replaying a token that has a successor proves compromise.
    replaced_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(50))
    created_ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index(
            "ix_refresh_tokens_user_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_refresh_tokens_replaced_by", "replaced_by"),
    )


class SingleUseTokenModel(Base):
    """Email verification and password reset tokens."""

    __tablename__ = "single_use_tokens"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("purpose IN ('email_verification','password_reset')", name="purpose_valid"),
        Index(
            "ix_single_use_tokens_user_purpose",
            "user_id",
            "purpose",
            postgresql_where=text("used_at IS NULL"),
        ),
    )


class UserDeviceModel(TimestampMixin, Base):
    __tablename__ = "user_devices"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(120))
    push_token: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("platform IN ('ios','android','web')", name="platform_valid"),
        Index("ix_user_devices_user", "user_id"),
    )


class UserSettingsModel(TimestampMixin, Base):
    """Vertical partition of preferences. The PK *is* the FK, which enforces 0..1."""

    __tablename__ = "user_settings"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    unit_system: Mapped[str] = mapped_column(String(10), nullable=False, server_default="metric")
    theme: Mapped[str] = mapped_column(String(10), nullable=False, server_default="system")
    language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
    profile_visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="private"
    )
    # Off by default, and it stays off unless the user turns it on. Progress photos are
    # excluded from model improvement regardless of this flag (docs/10 §11).
    ai_training_opt_in: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    marketing_email_opt_in: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint("unit_system IN ('metric','imperial')", name="unit_system_valid"),
        CheckConstraint("theme IN ('system','light','dark')", name="theme_valid"),
        CheckConstraint(
            "profile_visibility IN ('private','followers','public')",
            name="profile_visibility_valid",
        ),
    )
