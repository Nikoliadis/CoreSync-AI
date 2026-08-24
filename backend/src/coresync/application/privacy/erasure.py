"""Hard erasure of accounts past their grace period.

Deletion is a two-stage process. `ScheduleAccountDeletionUseCase` starts a thirty-day
clock and the user can still change their mind; this is what happens when that clock runs
out, and it is not reversible.

Erasure anonymises rather than dropping the row. Everything personal goes — email, name,
date of birth, weigh-ins, measurements, photos, diary, workouts, coaching transcripts —
while the account row survives with a scrubbed identity, along with the derived daily
aggregates. That keeps platform statistics truthful about what happened instead of
rewriting history every time somebody leaves, and it means a bug in the scrub is
correctable where a `DELETE` would not be.

Two rules this module exists to enforce:

* Nothing is erased before its deadline. The window is the user's protection and the
  query is the only thing enforcing it.
* An already-erased account is never touched again. Re-running must be free, because a
  scheduled job that is unsafe to re-run is a job nobody dares restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock
from coresync.core.logging import get_logger

logger = get_logger(__name__)

# Matches the promise made when deletion is scheduled. Changing it changes a commitment
# already given to every user with a pending deletion, so it lives here as a named
# constant rather than inline in a query.
GRACE_PERIOD_DAYS = 30

# A cap per run. Erasure is not urgent and a sweep that locks thousands of rows at once
# is a sweep that competes with live traffic; whatever is left waits for tomorrow.
MAX_PER_RUN = 200


@dataclass(frozen=True, slots=True)
class ErasureReport:
    considered: int = 0
    erased: int = 0
    failed: int = 0
    user_ids: list[UUID] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {"considered": self.considered, "erased": self.erased, "failed": self.failed}


class EraseExpiredAccountsUseCase:
    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, *, limit: int = MAX_PER_RUN) -> ErasureReport:
        now = self._clock.now()
        cutoff = now - timedelta(days=GRACE_PERIOD_DAYS)

        async with self._uow:
            due = await self._uow.users.list_due_for_erasure(cutoff=cutoff, limit=limit)

        erased: list[UUID] = []
        failed = 0
        for user_id in due:
            try:
                # One transaction per account. A failure on one must not roll back the
                # accounts already erased in this sweep — erasure is a promise kept per
                # user, not per batch.
                async with self._uow:
                    await self._uow.users.erase(user_id, at=now)
                    await self._uow.commit()
            except Exception as exc:
                failed += 1
                # Never log the identity being erased beyond its id: writing an email
                # address into the log of the job that deletes it would be absurd.
                logger.warning("account_erasure_failed", user_id=str(user_id), error=str(exc))
            else:
                erased.append(user_id)
                logger.info("account_erased", user_id=str(user_id))

        report = ErasureReport(
            considered=len(due), erased=len(erased), failed=failed, user_ids=erased
        )
        if report.considered:
            logger.info("erasure_sweep_finished", cutoff=cutoff.isoformat(), **report.as_dict())
        return report


def erasure_deadline(deleted_at: datetime) -> datetime:
    """When an account scheduled at ``deleted_at`` becomes eligible for erasure."""
    return deleted_at + timedelta(days=GRACE_PERIOD_DAYS)
