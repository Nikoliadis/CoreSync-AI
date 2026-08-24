"""The Celery application and its beat schedule.

    celery -A coresync.infrastructure.worker.app worker --loglevel=info
    celery -A coresync.infrastructure.worker.app beat   --loglevel=info

Everything scheduled here is work the application layer already knows how to do. The
worker's whole job is to call it on a clock — no business rules live in a task, because a
rule that only runs inside a worker is a rule nobody can test without one.

Two of these have been written and unreachable for a while: the notification outbox has a
dispatcher with `FOR UPDATE SKIP LOCKED` and nothing calling it, and account erasure has
a use case whose own docstring says it "runs as a separate scheduled job" that did not
exist. A feature that cannot run is indistinguishable from a feature nobody built.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from celery import Celery
from celery.schedules import crontab

from coresync.core.config import Settings, get_settings
from coresync.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


def build_celery(settings: Settings | None = None) -> Celery:
    resolved = settings or get_settings()

    app = Celery("coresync", broker=resolved.broker_url, backend=resolved.result_backend)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        # Acknowledge after the task returns, not before it starts. A worker killed
        # mid-dispatch must leave its batch to be picked up again rather than swallowed
        # — the outbox already tolerates redelivery, and losing a batch silently does
        # not.
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # A task that hangs on a provider must not hold its slot forever.
        task_soft_time_limit=270,
        task_time_limit=300,
        result_expires=3600,
        beat_schedule={
            "dispatch-notification-outbox": {
                "task": "coresync.notifications.dispatch_outbox",
                "schedule": float(resolved.outbox_dispatch_seconds),
                # Skip a run rather than pile up if the worker was down. The next tick
                # drains everything due anyway, because the outbox is a queue and not a
                # sequence of moments.
                "options": {"expires": float(resolved.outbox_dispatch_seconds)},
            },
            "erase-expired-accounts": {
                "task": "coresync.privacy.erase_expired_accounts",
                "schedule": crontab(hour=resolved.erasure_sweep_hour_utc, minute=0),
            },
        },
    )
    app.autodiscover_tasks(["coresync.infrastructure.worker"], related_name="tasks")
    return app


celery_app = build_celery()


def run_async[T](factory: Callable[[Settings], Awaitable[T]]) -> T:
    """Run one async unit of work inside a synchronous Celery task.

    A fresh event loop and a fresh database engine per task. Sharing either across
    tasks in a prefork worker is how you get a connection bound to a loop that has
    already closed — the failure surfaces much later, as an unrelated timeout.
    """
    configure_logging()
    settings = get_settings()
    return asyncio.run(factory(settings))


__all__ = ["build_celery", "celery_app", "run_async"]
