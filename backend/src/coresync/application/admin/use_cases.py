"""Admin read use cases.

Read-only by design. An admin panel that can mutate user data needs an audit trail of
who changed what *before* it needs the feature, and shipping the mutations first is
exactly how that gets skipped (docs/11).
"""

from __future__ import annotations

from datetime import timedelta

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock, local_date_for
from coresync.domain.admin.repositories import AdminUserRow, PlatformStats

STATS_WINDOW_DAYS = 7
COST_WINDOW_DAYS = 30
MAX_PAGE = 100


class GetPlatformStatsUseCase:
    """The operational dashboard: how many people, and how much they cost to serve."""

    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self) -> PlatformStats:
        # UTC rather than a user's timezone: these are platform-wide figures, and
        # "today" for an operator is not any particular user's day.
        today = local_date_for(self._clock.now(), "UTC")
        async with self._uow:
            return await self._uow.admin.platform_stats(
                since=today - timedelta(days=STATS_WINDOW_DAYS),
                cost_since=today - timedelta(days=COST_WINDOW_DAYS),
            )


class ListUsersUseCase:
    """A paginated user list for support.

    Identity and status only. Nothing here exposes training data, weight, photos or
    coaching conversations — support does not need them, and a panel that shows them is
    a breach waiting for a bored employee.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, *, query: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[AdminUserRow], int]:
        async with self._uow:
            return await self._uow.admin.list_users(
                query=query, limit=min(limit, MAX_PAGE), offset=max(offset, 0)
            )
