"""Rolling up a day's diary, and the streak that falls out of it.

The diary computes a day's totals from raw entries on every read, which is right for the
day you are looking at and wrong for everything else. A dashboard drawing thirty days
would run thirty aggregations, and "how many days in a row have I logged" is a question
about days, not entries.

So the summary is written whenever a day changes, and read whenever a range is needed.
It is derived data: losing the table entirely costs nothing but a rebuild, which is why
:class:`RebuildNutritionSummariesUseCase` exists and why nothing reads a summary to
decide what to write into one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError
from coresync.domain.nutrition.services import NutritionStreak, nutrition_streak, summarise_day

# How far back a rebuild reaches by default. A year covers every chart the product draws
# and keeps a rebuild bounded on an account with years of history.
DEFAULT_REBUILD_DAYS = 365


@dataclass(frozen=True, slots=True)
class DailySummary:
    local_date: date
    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    alcohol_g: Decimal
    water_ml: Decimal
    entry_count: int
    target_calories: Decimal | None = None
    target_protein_g: Decimal | None = None


async def refresh_day(uow: UnitOfWork, user_id: UUID, on: date) -> DailySummary:
    """Recompute one day and write it, inside a transaction the caller already opened.

    Called from every path that changes a day, in the same transaction as the change
    itself. That is the whole guarantee: there is no window in which the entries and
    their summary disagree, and no queue to fall behind.

    A full recompute rather than an increment. An increment has to be right about every
    path that can change a day — log, edit, delete, copy, recipe, water — and being
    wrong on any one of them leaves a total that drifts from the entries it claims to
    summarise, silently and forever.
    """
    entries = await uow.diary.entries_for_day(user_id, on)
    water = await uow.water.logs_for_day(user_id, on)
    totals = summarise_day(entries, water)
    target = await uow.targets.get_effective_on(user_id, on)

    summary = DailySummary(
        local_date=on,
        calories=totals.macros.calories,
        protein_g=totals.macros.protein_g,
        carbs_g=totals.macros.carbs_g,
        fat_g=totals.macros.fat_g,
        alcohol_g=totals.macros.alcohol_g,
        water_ml=totals.water_ml,
        entry_count=len(entries),
        target_calories=target.calories if target else None,
        target_protein_g=target.protein_g if target else None,
    )
    await uow.nutrition_summaries.upsert(user_id, summary)
    return summary


class RecalculateDaySummaryUseCase:
    """Rewrite one day's summary from its entries.

    Always a full recompute of that day rather than an increment. An increment has to be
    right about every path that changes a day — log, edit, delete, copy, recipe — and
    being wrong on any one of them leaves a total that drifts from the entries it claims
    to summarise, silently and permanently.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, on: date) -> DailySummary:
        async with self._uow:
            summary = await refresh_day(self._uow, user_id, on)
            await self._uow.commit()
        return summary


class GetNutritionStreakUseCase:
    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, user_id: UUID) -> NutritionStreak:
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            today = local_date_for(self._clock.now(), user.timezone)

            days = await self._uow.nutrition_summaries.logged_days(
                user_id, since=today - timedelta(days=DEFAULT_REBUILD_DAYS)
            )
            streak = nutrition_streak(days, today=today)
            await self._uow.streaks.set_nutrition(
                user_id,
                current=streak.current,
                longest=streak.longest,
                last_date=streak.last_date,
            )
            await self._uow.commit()
        return streak


class GetNutritionHistoryUseCase:
    """A range of days, read straight from the summaries."""

    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self, user_id: UUID, *, days: int = 30, ending: date | None = None
    ) -> list[DailySummary]:
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            last = ending or local_date_for(self._clock.now(), user.timezone)
            return await self._uow.nutrition_summaries.range(
                user_id, date_from=last - timedelta(days=days - 1), date_to=last
            )


class RebuildNutritionSummariesUseCase:
    """Recompute every day that has any diary or water activity.

    The summary table is derived, so this is the repair tool: run it after a bulk import,
    a bug fix, or a restore, and the table is correct again without anyone reasoning
    about which days were affected.
    """

    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, user_id: UUID, *, days: int = DEFAULT_REBUILD_DAYS) -> int:
        recalculate = RecalculateDaySummaryUseCase(uow=self._uow)
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            # The user's local day, never the server's: a rebuild run at 01:00 UTC
            # would otherwise pick a different window for a user in Athens.
            today = local_date_for(self._clock.now(), user.timezone)
            touched = await self._uow.nutrition_summaries.days_with_activity(
                user_id, since=today - timedelta(days=days)
            )
        for day in touched:
            await recalculate.execute(user_id, day)
        return len(touched)
