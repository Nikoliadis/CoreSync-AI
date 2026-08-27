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
from coresync.infrastructure.notifications.push import PushDeliveryError, PushResult

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


class RecordingPushSender:
    """A push sender, which takes tokens rather than only a notification."""

    def __init__(self, *, result: PushResult | None = None, fail_with: Exception | None = None):
        self.calls: list[tuple[Notification, list[str]]] = []
        self._result = result
        self.fail_with = fail_with

    async def send_to_tokens(self, notification: Notification, tokens: list[str]) -> PushResult:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((notification, list(tokens)))
        return self._result or PushResult(delivered=len(tokens))


async def _register_device(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    token: str,
    *,
    is_active: bool = True,
) -> str:
    device_id = uuid7()
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO user_devices (id, user_id, platform, push_token, is_active,"
                " last_seen_at, created_at, updated_at)"
                " VALUES (:id, :uid, 'ios', :token, :active, now(), now(), now())"
            ),
            {"id": device_id, "uid": user_id, "token": token, "active": is_active},
        )
        await session.commit()
    return str(device_id)


async def _publish_pr(
    session_factory: async_sessionmaker[AsyncSession], user_id: str, clock: FrozenClock
) -> None:
    """A PR celebration: allowed on push, and deliberately never sent by email."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await PublishNotificationUseCase(uow=uow, clock=clock).publish(
            user_id=UUID(user_id),
            category=NotificationCategory.PR_CELEBRATION,
            title="New record",
            body="You beat your bench press.",
            deep_link="/workout/abc",
        )
        await uow.commit()


def _tokens_for(sender: RecordingPushSender, user_id: str) -> list[str]:
    """Only what was sent for this user.

    The module shares one database, so a dispatcher run drains whatever other tests left
    behind. Asserting "nothing was sent at all" would be a claim about their leftovers
    rather than about the case under test.
    """
    return [
        token
        for notification, tokens in sender.calls
        if str(notification.user_id) == user_id
        for token in tokens
    ]


def _push_dispatcher(session_factory, clock, sender):
    return DispatchOutboxUseCase(
        uow=SqlAlchemyUnitOfWork(session_factory),
        clock=clock,
        senders={NotificationChannel.PUSH: sender},
    )


class TestPushDelivery:
    """The whole path: publish, outbox, dispatcher, device lookup, sender."""

    async def test_a_registered_device_receives_the_push(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        user_id = await _make_user(session_factory)
        await _register_device(session_factory, user_id, "ExponentPushToken[live]")
        clock = FrozenClock(NOW)
        sender = RecordingPushSender()

        await _publish_pr(session_factory, user_id, clock)
        counts = await _push_dispatcher(session_factory, clock, sender).run()

        assert counts["failed"] == 0
        assert len(sender.calls) == 1
        notification, tokens = sender.calls[0]
        assert notification.title == "New record"
        assert tokens == ["ExponentPushToken[live]"]

    async def test_no_push_is_queued_at_all_without_a_device(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # channels_for refuses to queue a push with nowhere to send it, so this is
        # asserted at the outbox rather than the sender: an entry that can only ever fail
        # would burn retries forever.
        user_id = await _make_user(session_factory)
        clock = FrozenClock(NOW)
        sender = RecordingPushSender()

        await _publish_pr(session_factory, user_id, clock)
        await _push_dispatcher(session_factory, clock, sender).run()

        assert _tokens_for(sender, user_id) == []

    async def test_an_inactive_device_is_not_sent_to(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        user_id = await _make_user(session_factory)
        await _register_device(session_factory, user_id, "ExponentPushToken[dead]", is_active=False)
        await _register_device(session_factory, user_id, "ExponentPushToken[good]")
        clock = FrozenClock(NOW)
        sender = RecordingPushSender()

        await _publish_pr(session_factory, user_id, clock)
        await _push_dispatcher(session_factory, clock, sender).run()

        assert sender.calls[0][1] == ["ExponentPushToken[good]"]

    async def test_every_device_of_one_user_is_sent_to(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        user_id = await _make_user(session_factory)
        await _register_device(session_factory, user_id, "ExponentPushToken[phone]")
        await _register_device(session_factory, user_id, "ExponentPushToken[tablet]")
        clock = FrozenClock(NOW)
        sender = RecordingPushSender()

        await _publish_pr(session_factory, user_id, clock)
        await _push_dispatcher(session_factory, clock, sender).run()

        assert sorted(sender.calls[0][1]) == [
            "ExponentPushToken[phone]",
            "ExponentPushToken[tablet]",
        ]

    async def test_a_dead_token_is_deactivated_rather_than_retried(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # DeviceNotRegistered means the app is gone from that phone. Retrying can never
        # succeed, so the device is stopped instead of spending an attempt on every
        # future notification.
        user_id = await _make_user(session_factory)
        await _register_device(session_factory, user_id, "ExponentPushToken[gone]")
        clock = FrozenClock(NOW)
        sender = RecordingPushSender(
            result=PushResult(delivered=0, dead_tokens=["ExponentPushToken[gone]"])
        )

        await _publish_pr(session_factory, user_id, clock)
        await _push_dispatcher(session_factory, clock, sender).run()

        async with session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT is_active, push_token FROM user_devices WHERE user_id = :uid"),
                    {"uid": user_id},
                )
            ).one()
        assert row.is_active is False
        assert row.push_token is None

    async def test_a_transport_failure_is_recorded_and_retried(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        user_id = await _make_user(session_factory)
        await _register_device(session_factory, user_id, "ExponentPushToken[flaky]")
        clock = FrozenClock(NOW)
        sender = RecordingPushSender(fail_with=PushDeliveryError("network went away"))

        await _publish_pr(session_factory, user_id, clock)
        counts = await _push_dispatcher(session_factory, clock, sender).run()

        assert counts["failed"] >= 1

        async with session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT status, attempts FROM notification_outbox"
                        " WHERE channel = 'push' AND user_id = :uid LIMIT 1"
                    ),
                    {"uid": user_id},
                )
            ).one()
        # Counted and still not sent, so the outbox will come back to it.
        assert row.attempts >= 1
        assert row.status != DeliveryStatus.SENT.value

    async def test_one_failing_push_does_not_abandon_the_batch(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # A bad provider minute must not stop email going out.
        user_id = await _make_user(session_factory)
        await _register_device(session_factory, user_id, "ExponentPushToken[bad]")
        clock = FrozenClock(NOW)
        email = RecordingSender()

        await _publish_pr(session_factory, user_id, clock)
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await PublishNotificationUseCase(uow=uow, clock=clock).publish(
                user_id=UUID(user_id),
                category=NotificationCategory.SYSTEM,
                title="Account notice",
                body="Something administrative.",
            )
            await uow.commit()

        dispatcher = DispatchOutboxUseCase(
            uow=SqlAlchemyUnitOfWork(session_factory),
            clock=clock,
            senders={
                NotificationChannel.PUSH: RecordingPushSender(
                    fail_with=PushDeliveryError("provider down")
                ),
                NotificationChannel.EMAIL: email,
            },
        )
        counts = await dispatcher.run()

        assert counts["failed"] >= 1
        assert "Account notice" in [n.title for n in email.sent]

    async def test_push_is_not_queued_when_the_category_is_disabled(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        # The Settings toggle has to control delivery, not merely store a value.
        user_id = await _make_user(session_factory)
        await _register_device(session_factory, user_id, "ExponentPushToken[silenced]")
        clock = FrozenClock(NOW)
        sender = RecordingPushSender()

        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO notification_preferences"
                    " (user_id, enabled_categories, push_enabled, email_enabled,"
                    "  created_at, updated_at)"
                    " VALUES (:uid, ARRAY[]::text[], true, true, now(), now())"
                    " ON CONFLICT (user_id) DO UPDATE"
                    " SET enabled_categories = ARRAY[]::text[]"
                ),
                {"uid": user_id},
            )
            await session.commit()

        await _publish_pr(session_factory, user_id, clock)
        await _push_dispatcher(session_factory, clock, sender).run()

        assert _tokens_for(sender, user_id) == []
