"""SQLAlchemy repositories for notifications."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.notifications.entities import (
    DeliveryStatus,
    Notification,
    NotificationCategory,
    NotificationChannel,
    NotificationPreferences,
    OutboxEntry,
)
from coresync.infrastructure.database.models.notifications import (
    NotificationModel,
    NotificationOutboxModel,
    NotificationPreferencesModel,
)


def _to_entity(model: NotificationModel) -> Notification:
    return Notification(
        id=model.id,
        user_id=model.user_id,
        category=NotificationCategory(model.category),
        title=model.title,
        body=model.body,
        deep_link=model.deep_link,
        data=model.data,
        read_at=model.read_at,
        created_at=model.created_at,
    )


def _outbox_to_entity(model: NotificationOutboxModel) -> OutboxEntry:
    return OutboxEntry(
        id=model.id,
        notification_id=model.notification_id,
        user_id=model.user_id,
        channel=NotificationChannel(model.channel),
        scheduled_for=model.scheduled_for,
        status=DeliveryStatus(model.status),
        attempts=model.attempts,
        last_error=model.last_error,
        sent_at=model.sent_at,
    )


class SqlAlchemyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, notification: Notification) -> None:
        self._session.add(
            NotificationModel(
                id=notification.id,
                user_id=notification.user_id,
                category=notification.category.value,
                title=notification.title,
                body=notification.body,
                deep_link=notification.deep_link,
                data=notification.data,
                read_at=notification.read_at,
            )
        )
        await self._session.flush()

    async def get(self, notification_id: UUID, user_id: UUID) -> Notification | None:
        stmt = select(NotificationModel).where(
            NotificationModel.id == notification_id,
            NotificationModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(model) if model else None

    async def list_for_user(
        self, user_id: UUID, *, limit: int, unread_only: bool = False
    ) -> list[Notification]:
        stmt = select(NotificationModel).where(NotificationModel.user_id == user_id)
        if unread_only:
            stmt = stmt.where(NotificationModel.read_at.is_(None))
        stmt = stmt.order_by(NotificationModel.created_at.desc()).limit(limit)
        return [_to_entity(m) for m in (await self._session.execute(stmt)).scalars()]

    async def unread_count(self, user_id: UUID) -> int:
        stmt = select(func.count(NotificationModel.id)).where(
            NotificationModel.user_id == user_id,
            NotificationModel.read_at.is_(None),
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def mark_read(self, notification_id: UUID, user_id: UUID, at: datetime) -> bool:
        # `read_at IS NULL` in the predicate makes this idempotent at the SQL level:
        # a second tap updates nothing and the original timestamp stands.
        stmt = (
            update(NotificationModel)
            .where(
                NotificationModel.id == notification_id,
                NotificationModel.user_id == user_id,
                NotificationModel.read_at.is_(None),
            )
            .values(read_at=at)
        )
        result = await self._session.execute(stmt)
        if result.rowcount:
            return True
        # Nothing updated: either it does not exist, is not theirs, or was already
        # read. Only the last of those is a success.
        return await self.get(notification_id, user_id) is not None

    async def mark_all_read(self, user_id: UUID, at: datetime) -> int:
        stmt = (
            update(NotificationModel)
            .where(
                NotificationModel.user_id == user_id,
                NotificationModel.read_at.is_(None),
            )
            .values(read_at=at)
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, entries: Sequence[OutboxEntry]) -> None:
        if not entries:
            return
        self._session.add_all(
            [
                NotificationOutboxModel(
                    id=entry.id,
                    notification_id=entry.notification_id,
                    user_id=entry.user_id,
                    channel=entry.channel.value,
                    scheduled_for=entry.scheduled_for,
                    status=entry.status.value,
                    attempts=entry.attempts,
                    last_error=entry.last_error,
                    sent_at=entry.sent_at,
                )
                for entry in entries
            ]
        )
        await self._session.flush()

    async def claim_due(self, *, now: datetime, limit: int) -> list[OutboxEntry]:
        """Lock a batch so a second dispatcher cannot pick up the same rows.

        ``SKIP LOCKED`` rather than plain ``FOR UPDATE``: a second worker should take
        the *next* batch immediately rather than block behind the first one. Without
        the lock entirely, two workers deliver the same push and the user gets it
        twice — which is precisely what the outbox exists to prevent.
        """
        stmt = (
            select(NotificationOutboxModel)
            .where(
                NotificationOutboxModel.status == DeliveryStatus.PENDING.value,
                NotificationOutboxModel.scheduled_for <= now,
            )
            .order_by(NotificationOutboxModel.scheduled_for)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        models = list((await self._session.execute(stmt)).scalars())
        return [_outbox_to_entity(m) for m in models]

    async def update(self, entry: OutboxEntry) -> None:
        stmt = (
            update(NotificationOutboxModel)
            .where(NotificationOutboxModel.id == entry.id)
            .values(
                status=entry.status.value,
                attempts=entry.attempts,
                last_error=entry.last_error,
                sent_at=entry.sent_at,
                scheduled_for=entry.scheduled_for,
            )
        )
        await self._session.execute(stmt)


class SqlAlchemyNotificationPreferencesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> NotificationPreferences | None:
        stmt = select(NotificationPreferencesModel).where(
            NotificationPreferencesModel.user_id == user_id
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        return NotificationPreferences(
            user_id=model.user_id,
            enabled_categories={NotificationCategory(c) for c in model.enabled_categories},
            push_enabled=model.push_enabled,
            email_enabled=model.email_enabled,
            quiet_hours_start=model.quiet_hours_start,
            quiet_hours_end=model.quiet_hours_end,
        )

    async def upsert(self, preferences: NotificationPreferences) -> None:
        values = {
            "user_id": preferences.user_id,
            "enabled_categories": sorted(c.value for c in preferences.enabled_categories),
            "push_enabled": preferences.push_enabled,
            "email_enabled": preferences.email_enabled,
            "quiet_hours_start": preferences.quiet_hours_start,
            "quiet_hours_end": preferences.quiet_hours_end,
        }
        stmt = (
            pg_insert(NotificationPreferencesModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[NotificationPreferencesModel.user_id],
                set_={k: v for k, v in values.items() if k != "user_id"},
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
