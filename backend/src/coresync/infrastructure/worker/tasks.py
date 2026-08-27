"""Scheduled tasks.

Each one is a thin adapter: build the dependencies, call an application use case, log
what happened. No business rules here — a rule that only runs inside a worker is a rule
nobody can test without starting one.
"""

from __future__ import annotations

from typing import Any

from coresync.application.notifications.use_cases import DispatchOutboxUseCase
from coresync.application.privacy.erasure import EraseExpiredAccountsUseCase
from coresync.core.clock import SystemClock
from coresync.core.config import Settings
from coresync.core.logging import get_logger
from coresync.domain.notifications.entities import NotificationChannel
from coresync.infrastructure.database.session import Database
from coresync.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from coresync.infrastructure.worker.app import celery_app, run_async

logger = get_logger(__name__)


def _senders(settings: Settings) -> dict[NotificationChannel, Any]:
    """The delivery channels this deployment can actually reach.

    A channel with no sender is *skipped* by the dispatcher rather than retried, so an
    unconfigured push provider costs one log line per notification instead of a queue
    that grows forever against a wall.
    """
    from coresync.infrastructure.notifications.email import (
        ConsoleEmailSender,
        SmtpEmailSender,
    )
    from coresync.infrastructure.notifications.push import ExpoPushSender

    # Keyed on environment, matching the API's composition root: `smtp_host` defaults
    # to "localhost" and is therefore always truthy, so branching on it would silently
    # pick SMTP everywhere including tests.
    email = ConsoleEmailSender() if settings.environment == "test" else SmtpEmailSender(settings)
    senders: dict[NotificationChannel, Any] = {NotificationChannel.EMAIL: email}

    # Registered only when configured. An unregistered channel is *skipped* by the
    # dispatcher, which is the right outcome for a deployment with no push provider —
    # registering a sender that always fails would burn retries against nothing.
    if settings.push_enabled:
        senders[NotificationChannel.PUSH] = ExpoPushSender(
            access_token=settings.expo_access_token or None
        )

    return senders


@celery_app.task(
    name="coresync.notifications.dispatch_outbox",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def dispatch_outbox(self: Any) -> dict[str, int]:
    """Drain whatever is due.

    Safe to run concurrently: entries are claimed with ``FOR UPDATE SKIP LOCKED``, so a
    second worker picks up different rows rather than the same ones. That is the whole
    reason the outbox exists — without it, two dispatchers deliver the same push twice.

    Retries only on infrastructure failure. A delivery that fails is recorded against
    its own entry and retried on its own schedule; re-running the whole batch because
    one provider had a bad minute would multiply the damage.
    """

    async def _run(settings: Settings) -> dict[str, int]:
        database = Database(settings)
        try:
            use_case = DispatchOutboxUseCase(
                uow=SqlAlchemyUnitOfWork(database.session_factory),
                clock=SystemClock(),
                senders=_senders(settings),
            )
            return await use_case.run()
        finally:
            await database.dispose()

    try:
        counts = run_async(_run)
    except Exception as exc:
        logger.warning("outbox_dispatch_failed", error=str(exc))
        raise self.retry(exc=exc) from exc

    # Only worth a line when something moved. A task on a sixty-second timer that logs
    # "sent 0" all night buries the runs that matter.
    if any(counts.values()):
        logger.info("outbox_dispatched", **counts)
    return counts


@celery_app.task(name="coresync.privacy.erase_expired_accounts", bind=True, max_retries=0)
def erase_expired_accounts(self: Any) -> dict[str, object]:
    """Erase accounts whose thirty-day grace period has run out.

    No retries. Erasure is irreversible and per-account transactional: a failure is
    already logged against the account that failed, and the accounts that succeeded are
    done. Re-running the whole sweep on a schedule is the retry — tomorrow's run picks
    up whatever today's could not, because an erased account is never selected twice.
    """

    async def _run(settings: Settings) -> dict[str, object]:
        database = Database(settings)
        try:
            use_case = EraseExpiredAccountsUseCase(
                uow=SqlAlchemyUnitOfWork(database.session_factory), clock=SystemClock()
            )
            report = await use_case.execute()
            return report.as_dict()
        finally:
            await database.dispose()

    return run_async(_run)
