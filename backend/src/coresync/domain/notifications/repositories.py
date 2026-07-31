"""Repository ports for notifications."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from coresync.domain.notifications.entities import (
    Notification,
    NotificationPreferences,
    OutboxEntry,
)


class NotificationRepository(Protocol):
    async def add(self, notification: Notification) -> None: ...

    async def get(self, notification_id: UUID, user_id: UUID) -> Notification | None:
        """``user_id`` is a predicate, not a check afterwards — omitting it is an IDOR."""
        ...

    async def list_for_user(
        self, user_id: UUID, *, limit: int, unread_only: bool = False
    ) -> list[Notification]: ...

    async def unread_count(self, user_id: UUID) -> int: ...

    async def mark_read(self, notification_id: UUID, user_id: UUID, at: datetime) -> bool:
        """Returns whether a row was actually updated, so the caller can 404 honestly."""
        ...

    async def mark_all_read(self, user_id: UUID, at: datetime) -> int: ...


class OutboxRepository(Protocol):
    async def add_many(self, entries: Sequence[OutboxEntry]) -> None: ...

    async def claim_due(self, *, now: datetime, limit: int) -> list[OutboxEntry]:
        """Take a batch of due work, locking it against other dispatchers.

        Implementations must use ``FOR UPDATE SKIP LOCKED``. Without it, two workers
        select the same rows and the user gets the notification twice — the failure
        mode an outbox exists to prevent.
        """
        ...

    async def update(self, entry: OutboxEntry) -> None: ...


class NotificationPreferencesRepository(Protocol):
    async def get(self, user_id: UUID) -> NotificationPreferences | None: ...

    async def upsert(self, preferences: NotificationPreferences) -> None: ...
