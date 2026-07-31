"""Notification entities.

Two tables' worth of concepts kept deliberately separate: **what happened** (a
``Notification``) and **the attempt to tell someone about it** (an ``OutboxEntry``).

Conflating them is the usual mistake. A single event can go to three channels with
different schedules and different failure modes; if delivery state lives on the
notification row, a failed push retries the email too, and "mark as read" starts
racing with the dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from coresync.core.ids import uuid7


class NotificationCategory(StrEnum):
    """What the notification is about.

    Categories exist so users can silence one kind without silencing all of them.
    Someone who wants PR celebrations but not weekly reports must be able to say so,
    or they turn the lot off (docs/15 Phase 6).
    """

    WORKOUT_REMINDER = "workout_reminder"
    PR_CELEBRATION = "pr_celebration"
    STREAK_RISK = "streak_risk"
    INSIGHT_READY = "insight_ready"
    WEEKLY_REPORT = "weekly_report"
    SYSTEM = "system"


class NotificationChannel(StrEnum):
    PUSH = "push"
    EMAIL = "email"
    IN_APP = "in_app"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    # Skipped rather than failed: the user opted out, or the device token vanished.
    # Distinguishing them keeps a preference change out of the failure metrics.
    SKIPPED = "skipped"


# Categories a user may never silence. Kept minimal on purpose — an unsilenceable
# marketing category is how an app earns a system-level notification block.
UNSILENCEABLE: frozenset[NotificationCategory] = frozenset({NotificationCategory.SYSTEM})


@dataclass(slots=True)
class Notification:
    """Something worth telling the user about."""

    id: UUID
    user_id: UUID
    category: NotificationCategory
    title: str
    body: str
    # Where tapping it should land. Stored as an app route rather than a URL so web,
    # iOS and Android resolve it themselves.
    deep_link: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        category: NotificationCategory,
        title: str,
        body: str,
        deep_link: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        return cls(
            id=uuid7(),
            user_id=user_id,
            category=category,
            title=title,
            body=body,
            deep_link=deep_link,
            data=data or {},
        )

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self, at: datetime) -> None:
        # Idempotent: the first read is the one that counts, and a second tap must not
        # move the timestamp.
        if self.read_at is None:
            self.read_at = at


@dataclass(slots=True)
class OutboxEntry:
    """One delivery attempt, on one channel.

    Written in the same transaction as the notification itself. That is the whole
    point of an outbox: if the process dies between "PR detected" and "push sent",
    the row is already committed and the dispatcher picks it up. The alternative —
    firing the push inline — loses the notification on any crash, and duplicates it
    on any retry of the surrounding operation.
    """

    id: UUID
    notification_id: UUID
    user_id: UUID
    channel: NotificationChannel
    scheduled_for: datetime
    status: DeliveryStatus = DeliveryStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    sent_at: datetime | None = None

    # Three tries then stop. A token that has been invalid twice will be invalid the
    # third time, and an outbox that retries forever is a queue that never drains.
    MAX_ATTEMPTS: int = 3

    @classmethod
    def create(
        cls,
        *,
        notification_id: UUID,
        user_id: UUID,
        channel: NotificationChannel,
        scheduled_for: datetime,
    ) -> OutboxEntry:
        return cls(
            id=uuid7(),
            notification_id=notification_id,
            user_id=user_id,
            channel=channel,
            scheduled_for=scheduled_for,
        )

    @property
    def is_exhausted(self) -> bool:
        return self.attempts >= self.MAX_ATTEMPTS

    def record_success(self, at: datetime) -> None:
        self.status = DeliveryStatus.SENT
        self.sent_at = at
        self.attempts += 1
        self.last_error = None

    def record_failure(self, error: str, *, at: datetime) -> None:
        self.attempts += 1
        # The message is truncated because provider errors can be enormous, and an
        # outbox row is not the right place to store a stack trace.
        self.last_error = error[:500]
        self.status = DeliveryStatus.FAILED if self.is_exhausted else DeliveryStatus.PENDING
        if self.status == DeliveryStatus.PENDING:
            self.scheduled_for = at

    def skip(self, reason: str) -> None:
        self.status = DeliveryStatus.SKIPPED
        self.last_error = reason[:500]


@dataclass(slots=True)
class NotificationPreferences:
    """Per-user delivery rules.

    Quiet hours are stored as local wall-clock times, not UTC offsets. A user who sets
    "no pings after 22:00" means 22:00 where they are, and expects that to still hold
    after they fly somewhere else or the clocks change.
    """

    user_id: UUID
    enabled_categories: set[NotificationCategory] = field(
        default_factory=lambda: set(NotificationCategory)
    )
    push_enabled: bool = True
    email_enabled: bool = True
    quiet_hours_start: int | None = 22
    quiet_hours_end: int | None = 7

    @classmethod
    def defaults(cls, user_id: UUID) -> NotificationPreferences:
        return cls(user_id=user_id)

    def allows(self, category: NotificationCategory, channel: NotificationChannel) -> bool:
        if category in UNSILENCEABLE:
            return True
        if category not in self.enabled_categories:
            return False
        if channel is NotificationChannel.PUSH:
            return self.push_enabled
        if channel is NotificationChannel.EMAIL:
            return self.email_enabled
        # In-app is always allowed for an enabled category: it makes no sound and the
        # user only sees it by opening the screen that lists it.
        return True

    @property
    def has_quiet_hours(self) -> bool:
        return (
            self.quiet_hours_start is not None
            and self.quiet_hours_end is not None
            and self.quiet_hours_start != self.quiet_hours_end
        )
