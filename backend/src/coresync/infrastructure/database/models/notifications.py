"""ORM models for notifications and the delivery outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from coresync.infrastructure.database.base import Base, TimestampMixin


class NotificationModel(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # An app route rather than a URL, so each platform resolves it natively.
    deep_link: Mapped[str | None] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "category IN ('workout_reminder','pr_celebration','streak_risk',"
            "'insight_ready','weekly_report','system')",
            name="category_valid",
        ),
        # The unread badge is read on every app open, so it gets its own partial index
        # rather than scanning a lifetime of read notifications.
        Index(
            "ix_notifications_user_unread",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("read_at IS NULL"),
        ),
        Index("ix_notifications_user_recent", "user_id", text("created_at DESC")),
    )


class NotificationOutboxModel(Base):
    """Pending deliveries.

    Written in the same transaction as the notification, which is what makes delivery
    survive a crash between "PR detected" and "push sent".
    """

    __tablename__ = "notification_outbox"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    notification_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("channel IN ('push','email','in_app')", name="channel_valid"),
        CheckConstraint(
            "status IN ('pending','sent','failed','skipped')", name="delivery_status_valid"
        ),
        # The dispatcher's only query: due, pending work, oldest first. Partial so the
        # index stays small as sent rows accumulate — they are the overwhelming
        # majority and the dispatcher never looks at them again.
        Index(
            "ix_outbox_due",
            "scheduled_for",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_outbox_notification", "notification_id"),
    )


class NotificationPreferencesModel(TimestampMixin, Base):
    """Per-user delivery rules. The PK *is* the FK, which enforces 0..1."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled_categories: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), nullable=False, server_default=text("'{}'::varchar[]")
    )
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Local wall-clock hours, not UTC offsets: "no pings after 22:00" must keep meaning
    # 22:00 where the user is, after travel and after the clocks change.
    quiet_hours_start: Mapped[int | None] = mapped_column(Integer)
    quiet_hours_end: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "quiet_hours_start IS NULL OR (quiet_hours_start >= 0 AND quiet_hours_start <= 23)",
            name="quiet_start_valid",
        ),
        CheckConstraint(
            "quiet_hours_end IS NULL OR (quiet_hours_end >= 0 AND quiet_hours_end <= 23)",
            name="quiet_end_valid",
        ),
    )
