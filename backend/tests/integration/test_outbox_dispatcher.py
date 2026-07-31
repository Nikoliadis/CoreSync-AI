"""The notification outbox dispatcher, against a real database.

Worth integration-testing rather than mocking: the guarantees being asserted are
`SKIP LOCKED`, transactional visibility and retry state transitions, none of which a
fake repository can honestly reproduce.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coresync.application.notifications.use_cases import (
    DispatchOutboxUseCase,
    PublishNotificationUseCase,
)
from coresync.core.clock import FrozenClock
from coresync.core.ids import uuid7
from coresync.domain.notifications.entities import (
    DeliveryStatus,
    Notification,
    NotificationCategory,
    NotificationChannel,
    OutboxEntry,
)
from coresync.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class RecordingSender:
    """Captures what it was asked to send, and can be told to fail."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.sent: list[Notification] = []
        self.fail_with = fail_with

    async def send(self, notification: Notification) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(notification)


@pytest_asyncio.fixture
async def engine(postgres_url: str):
    engine = create_async_engine(postgres_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _make_user(session_factory: async_sessionmaker[AsyncSession]) -> str:
    """A minimal active user — notifications hang off a real foreign key."""
    user_id = uuid7()
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, role, status, timezone,"
                " email_verified_at, created_at, updated_at)"
                " VALUES (:id, :email, 'x', 'user', 'active', 'UTC',"
                " now(), now(), now())"
            ),
            {"id": user_id, "email": f"outbox-{user_id}@example.com"},
        )
        await session.commit()
    return str(user_id)


class TestDispatch:
    async def test_a_due_push_is_sent_and_marked(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        user_id = await _make_user(session_factory)
        clock = FrozenClock(NOW)
        sender = RecordingSender()

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            publisher = PublishNotificationUseCase(uow=uow, clock=clock)
            await publisher.publish(
                user_id=UUID(user_id),
                category=NotificationCategory.SYSTEM,
                title="Welcome",
                body="Glad you're here.",
            )
            await uow.commit()

        dispatcher = DispatchOutboxUseCase(
            uow=SqlAlchemyUnitOfWork(session_factory),
            clock=clock,
            senders={NotificationChannel.EMAIL: sender},
        )
        counts = await dispatcher.run()

        # System notices go to in-app and email; in-app needs no provider.
        assert counts["sent"] >= 1
        assert counts["failed"] == 0
        assert [n.title for n in sender.sent] == ["Welcome"]

    async def test_nothing_scheduled_for_later_is_picked_up(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Quiet hours defer by moving `scheduled_for`; the dispatcher must respect it."""
        user_id = await _make_user(session_factory)
        clock = FrozenClock(NOW)

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            notification = Notification.create(
                user_id=UUID(user_id),
                category=NotificationCategory.PR_CELEBRATION,
                title="New PR",
                body="102.5 kg.",
            )
            await uow.notifications.add(notification)

            await uow.notification_outbox.add_many(
                [
                    OutboxEntry.create(
                        notification_id=notification.id,
                        user_id=notification.user_id,
                        channel=NotificationChannel.PUSH,
                        scheduled_for=NOW + timedelta(hours=6),
                    )
                ]
            )
            await uow.commit()

        sender = RecordingSender()
        dispatcher = DispatchOutboxUseCase(
            uow=SqlAlchemyUnitOfWork(session_factory),
            clock=clock,
            senders={NotificationChannel.PUSH: sender},
        )
        counts = await dispatcher.run()

        assert sender.sent == []
        assert counts["sent"] == 0

    async def test_a_failure_leaves_the_entry_pending_for_a_retry(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        user_id = await _make_user(session_factory)
        clock = FrozenClock(NOW)

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            notification = Notification.create(
                user_id=UUID(user_id),
                category=NotificationCategory.SYSTEM,
                title="Notice",
                body="Something happened.",
            )
            await uow.notifications.add(notification)

            await uow.notification_outbox.add_many(
                [
                    OutboxEntry.create(
                        notification_id=notification.id,
                        user_id=notification.user_id,
                        channel=NotificationChannel.EMAIL,
                        scheduled_for=NOW - timedelta(minutes=1),
                    )
                ]
            )
            await uow.commit()

        dispatcher = DispatchOutboxUseCase(
            uow=SqlAlchemyUnitOfWork(session_factory),
            clock=clock,
            senders={
                NotificationChannel.EMAIL: RecordingSender(fail_with=RuntimeError("smtp down"))
            },
        )
        counts = await dispatcher.run()

        assert counts["failed"] == 1

        async with session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT status, attempts, last_error FROM notification_outbox"
                        " WHERE user_id = :uid"
                    ),
                    {"uid": user_id},
                )
            ).one()
        # Still pending, so the next run tries again — a single SMTP blip must not
        # permanently lose the notification.
        assert row[0] == DeliveryStatus.PENDING.value
        assert row[1] == 1
        assert "smtp down" in row[2]

    async def test_it_gives_up_after_three_attempts(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """A queue that retries forever is a queue that never drains."""
        user_id = await _make_user(session_factory)
        clock = FrozenClock(NOW)

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            notification = Notification.create(
                user_id=UUID(user_id),
                category=NotificationCategory.SYSTEM,
                title="Notice",
                body="Something happened.",
            )
            await uow.notifications.add(notification)

            await uow.notification_outbox.add_many(
                [
                    OutboxEntry.create(
                        notification_id=notification.id,
                        user_id=notification.user_id,
                        channel=NotificationChannel.EMAIL,
                        scheduled_for=NOW - timedelta(minutes=1),
                    )
                ]
            )
            await uow.commit()

        for _ in range(3):
            await DispatchOutboxUseCase(
                uow=SqlAlchemyUnitOfWork(session_factory),
                clock=clock,
                senders={
                    NotificationChannel.EMAIL: RecordingSender(fail_with=RuntimeError("nope"))
                },
            ).run()

        async with session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT status, attempts FROM notification_outbox WHERE user_id = :uid"),
                    {"uid": user_id},
                )
            ).one()
        assert row[0] == DeliveryStatus.FAILED.value
        assert row[1] == 3

    async def test_an_unconfigured_channel_is_skipped_not_failed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """A missing provider is a deployment gap, not a delivery failure."""
        user_id = await _make_user(session_factory)
        clock = FrozenClock(NOW)

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            notification = Notification.create(
                user_id=UUID(user_id),
                category=NotificationCategory.SYSTEM,
                title="Notice",
                body="No sender for this channel.",
            )
            await uow.notifications.add(notification)

            await uow.notification_outbox.add_many(
                [
                    OutboxEntry.create(
                        notification_id=notification.id,
                        user_id=notification.user_id,
                        channel=NotificationChannel.PUSH,
                        scheduled_for=NOW - timedelta(minutes=1),
                    )
                ]
            )
            await uow.commit()

        counts = await DispatchOutboxUseCase(
            uow=SqlAlchemyUnitOfWork(session_factory), clock=clock, senders={}
        ).run()

        assert counts["skipped"] == 1
        assert counts["failed"] == 0

    async def test_a_second_run_does_not_resend(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """The property the outbox exists for: at-most-once per entry."""
        user_id = await _make_user(session_factory)
        clock = FrozenClock(NOW)
        sender = RecordingSender()

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await PublishNotificationUseCase(uow=uow, clock=clock).publish(
                user_id=UUID(user_id),
                category=NotificationCategory.SYSTEM,
                title="Once only",
                body="Should not repeat.",
            )
            await uow.commit()

        for _ in range(3):
            await DispatchOutboxUseCase(
                uow=SqlAlchemyUnitOfWork(session_factory),
                clock=clock,
                senders={NotificationChannel.EMAIL: sender},
            ).run()

        assert len(sender.sent) == 1
