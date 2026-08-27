"""Notification use cases.

Publishing and dispatching are separate on purpose. Publishing runs inside the
transaction of whatever caused it — a PR being detected, an insight being written —
and only writes rows. Dispatching runs later, out of band, and is the only thing that
talks to a push or email provider.

That split is what makes delivery survive a crash: the notification is committed with
the event, so a process that dies before the push is sent has still recorded the fact
that it owes one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock
from coresync.core.errors import NotFoundError
from coresync.domain.notifications.entities import (
    Notification,
    NotificationCategory,
    NotificationChannel,
    NotificationPreferences,
    OutboxEntry,
)
from coresync.domain.notifications.services import channels_for, next_send_time

logger = structlog.get_logger(__name__)

DEFAULT_PAGE_LIMIT = 50
DISPATCH_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class NotificationDTO:
    id: UUID
    category: str
    title: str
    body: str
    deep_link: str | None
    data: dict[str, Any]
    read_at: datetime | None
    created_at: datetime | None

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


def notification_dto(notification: Notification) -> NotificationDTO:
    return NotificationDTO(
        id=notification.id,
        category=notification.category.value,
        title=notification.title,
        body=notification.body,
        deep_link=notification.deep_link,
        data=notification.data,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


class PublishNotificationUseCase:
    """Records a notification and queues its deliveries.

    Deliberately does **not** open its own transaction: it is called from inside one
    that is already recording the triggering event, and the atomicity of "the PR and
    the notification about it" is the guarantee that matters.
    """

    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def publish(
        self,
        *,
        user_id: UUID,
        category: NotificationCategory,
        title: str,
        body: str,
        deep_link: str | None = None,
        data: dict[str, Any] | None = None,
        timezone: str = "UTC",
    ) -> Notification | None:
        preferences = await self._uow.notification_preferences.get(user_id)
        if preferences is None:
            preferences = NotificationPreferences.defaults(user_id)

        devices = await self._uow.devices.list_for_user(user_id)
        has_push_token = any(getattr(device, "push_token", None) for device in devices)

        channels = channels_for(category, preferences, has_push_token=has_push_token)
        if not channels:
            # Fully opted out. Nothing is recorded at all: an in-app row the user has
            # asked not to receive is still an unread badge they did not ask for.
            logger.info("notification_suppressed", user_id=str(user_id), category=category.value)
            return None

        notification = Notification.create(
            user_id=user_id,
            category=category,
            title=title,
            body=body,
            deep_link=deep_link,
            data=data,
        )
        await self._uow.notifications.add(notification)

        now = self._clock.now()
        entries = [
            OutboxEntry.create(
                notification_id=notification.id,
                user_id=user_id,
                channel=channel,
                # In-app needs no scheduling: it makes no sound, and holding it back
                # would mean the list is missing an entry the user came looking for.
                scheduled_for=(
                    now
                    if channel is NotificationChannel.IN_APP
                    else next_send_time(now, preferences, timezone, category=category)
                ),
            )
            for channel in channels
        ]
        await self._uow.notification_outbox.add_many(entries)

        return notification


class _NothingToSendError(Exception):
    """No deliverable destination remained. Distinct from a delivery that failed."""


class DispatchOutboxUseCase:
    """Sends what is due.

    Runs as a scheduled job. Each entry is claimed with ``SKIP LOCKED`` so several
    dispatchers can run side by side without delivering the same push twice.
    """

    def __init__(
        self, *, uow: UnitOfWork, clock: Clock, senders: dict[NotificationChannel, Any]
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._senders = senders

    async def _send_push(self, sender: Any, notification: Notification, user_id: UUID) -> None:
        """Push needs the devices, which only the unit of work can supply.

        Handled here rather than inside the sender so the provider adapter never holds a
        database session — a transaction open across a call to a third party is how a
        slow provider becomes a database incident.
        """
        devices = await self._uow.devices.list_deliverable(user_id)
        tokens = [device.push_token for device in devices if device.push_token]
        if not tokens:
            raise _NothingToSendError("no active device with a push token")

        result = await sender.send_to_tokens(notification, tokens)

        # A token the provider has condemned is stopped here, so the next notification
        # does not spend an attempt on a device the app was deleted from.
        for token in result.dead_tokens:
            await self._uow.devices.deactivate_token(token)
            logger.info("push_device_deactivated", user_id=str(user_id))

        if not result.anything_delivered:
            # Nothing landed and nothing is retryable — every token was dead or rejected.
            raise _NothingToSendError("every device token was rejected")

    async def run(self, *, batch_size: int = DISPATCH_BATCH_SIZE) -> dict[str, int]:
        now = self._clock.now()
        counts = {"sent": 0, "failed": 0, "skipped": 0}

        async with self._uow:
            due = await self._uow.notification_outbox.claim_due(now=now, limit=batch_size)

            for entry in due:
                # In-app delivery is the row itself — there is nothing to send, so it
                # is marked done without touching a provider.
                if entry.channel is NotificationChannel.IN_APP:
                    entry.record_success(now)
                    counts["sent"] += 1
                    await self._uow.notification_outbox.update(entry)
                    continue

                sender = self._senders.get(entry.channel)
                if sender is None:
                    entry.skip(f"no sender configured for {entry.channel.value}")
                    counts["skipped"] += 1
                    await self._uow.notification_outbox.update(entry)
                    continue

                notification = await self._uow.notifications.get(
                    entry.notification_id, entry.user_id
                )
                if notification is None:
                    entry.skip("notification no longer exists")
                    counts["skipped"] += 1
                    await self._uow.notification_outbox.update(entry)
                    continue

                try:
                    if entry.channel is NotificationChannel.PUSH:
                        await self._send_push(sender, notification, entry.user_id)
                    else:
                        await sender.send(notification)
                except _NothingToSendError as reason:
                    # Every device went away between queueing and sending — uninstalled,
                    # or permission revoked. Retrying cannot succeed, so this is skipped
                    # rather than failed, which would burn attempts against nothing.
                    entry.skip(str(reason))
                    counts["skipped"] += 1
                    await self._uow.notification_outbox.update(entry)
                    continue
                except Exception as exc:
                    # One bad delivery must not abandon the batch — the remaining
                    # entries are unrelated and mostly fine.
                    entry.record_failure(str(exc), at=now)
                    counts["failed"] += 1
                    logger.warning(
                        "notification_delivery_failed",
                        channel=entry.channel.value,
                        attempts=entry.attempts,
                    )
                else:
                    entry.record_success(now)
                    counts["sent"] += 1

                await self._uow.notification_outbox.update(entry)

            await self._uow.commit()

        return counts


class ListNotificationsUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, user_id: UUID, *, limit: int = DEFAULT_PAGE_LIMIT, unread_only: bool = False
    ) -> tuple[list[NotificationDTO], int]:
        async with self._uow:
            items = await self._uow.notifications.list_for_user(
                user_id, limit=limit, unread_only=unread_only
            )
            unread = await self._uow.notifications.unread_count(user_id)
        return [notification_dto(n) for n in items], unread


class MarkNotificationReadUseCase:
    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, notification_id: UUID, user_id: UUID) -> None:
        async with self._uow:
            updated = await self._uow.notifications.mark_read(
                notification_id, user_id, self._clock.now()
            )
            if not updated:
                raise NotFoundError("That notification does not exist.")
            await self._uow.commit()

    async def mark_all(self, user_id: UUID) -> int:
        async with self._uow:
            count = await self._uow.notifications.mark_all_read(user_id, self._clock.now())
            await self._uow.commit()
        return count


class NotificationPreferencesUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def get(self, user_id: UUID) -> NotificationPreferences:
        async with self._uow:
            preferences = await self._uow.notification_preferences.get(user_id)
        return preferences or NotificationPreferences.defaults(user_id)

    async def update(
        self,
        user_id: UUID,
        *,
        enabled_categories: set[NotificationCategory] | None = None,
        push_enabled: bool | None = None,
        email_enabled: bool | None = None,
        quiet_hours_start: int | None = None,
        quiet_hours_end: int | None = None,
        clear_quiet_hours: bool = False,
    ) -> NotificationPreferences:
        async with self._uow:
            current = await self._uow.notification_preferences.get(user_id)
            preferences = current or NotificationPreferences.defaults(user_id)

            if enabled_categories is not None:
                preferences.enabled_categories = enabled_categories
            if push_enabled is not None:
                preferences.push_enabled = push_enabled
            if email_enabled is not None:
                preferences.email_enabled = email_enabled
            if clear_quiet_hours:
                preferences.quiet_hours_start = None
                preferences.quiet_hours_end = None
            else:
                if quiet_hours_start is not None:
                    preferences.quiet_hours_start = quiet_hours_start
                if quiet_hours_end is not None:
                    preferences.quiet_hours_end = quiet_hours_end

            await self._uow.notification_preferences.upsert(preferences)
            await self._uow.commit()

        return preferences
