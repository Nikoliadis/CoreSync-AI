"""Statistics and the dashboard bundle.

Everything here reads the incrementally maintained aggregates rather than raw sets and
sessions. That is the whole reason those tables exist: a dashboard should be a handful of
indexed lookups, not a scan over a lifetime of training (docs/03 §9).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from coresync.application.catalog.dto import PersonalRecordDTO
from coresync.application.catalog.use_cases import record_dto
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.progress.dto import (
    DashboardDTO,
    FrequencyBucketDTO,
    MuscleVolumeBucketDTO,
    PeriodTotalsDTO,
    StreakDTO,
)
from coresync.application.progress.measurements import measurement_dto
from coresync.application.progress.weight import GetWeightSeriesUseCase, WeightSeriesQuery
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError, ValidationError
from coresync.domain.workout.entities import PersonalRecord
from coresync.domain.workout.repositories import CalendarDay, MuscleVolumeDay

_ZERO = Decimal("0")
MAX_WINDOW_DAYS = 730
RECENT_RECORD_LIMIT = 5


class Granularity(StrEnum):
    WEEK = "week"
    MONTH = "month"


def _week_start(on: date) -> date:
    """Monday. ISO weeks, so a "week" means the same thing everywhere in the product."""
    return on - timedelta(days=on.weekday())


def _month_start(on: date) -> date:
    return on.replace(day=1)


def _bucket_start(on: date, granularity: Granularity) -> date:
    return _week_start(on) if granularity is Granularity.WEEK else _month_start(on)


def _bucket_end(start: date, granularity: Granularity) -> date:
    if granularity is Granularity.WEEK:
        return start + timedelta(days=6)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


@dataclass(frozen=True, slots=True)
class StatsQuery:
    user_id: UUID
    date_from: date | None = None
    date_to: date | None = None
    granularity: str = "week"


class _WindowResolver:
    """Shared window handling, so every stats endpoint agrees on what "no dates" means."""

    DEFAULT_DAYS = 90

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def resolve(
        self, user_id: UUID, date_from: date | None, date_to: date | None
    ) -> tuple[date, date, date]:
        user = await self._uow.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user", user_id)
        today = local_date_for(self._clock.now(), user.timezone)
        end = date_to or today
        start = date_from or (end - timedelta(days=self.DEFAULT_DAYS))
        if (end - start).days > MAX_WINDOW_DAYS:
            raise ValidationError(f"Ask for at most {MAX_WINDOW_DAYS} days at a time.")
        return start, end, today


class GetVolumeByMuscleGroupUseCase:
    """Tonnage per muscle group, bucketed by week or month.

    Bucketed server-side because the client would otherwise download a year of daily
    jsonb splits to draw twelve bars.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._window = _WindowResolver(uow, clock)

    async def execute(self, query: StatsQuery) -> list[MuscleVolumeBucketDTO]:
        granularity = Granularity(query.granularity)
        async with self._uow:
            start, end, _ = await self._window.resolve(
                query.user_id, query.date_from, query.date_to
            )
            days = await self._uow.summaries.muscle_volume_range(
                query.user_id, date_from=start, date_to=end
            )
        return self._bucket(days, granularity)

    @staticmethod
    def _bucket(
        days: list[MuscleVolumeDay], granularity: Granularity
    ) -> list[MuscleVolumeBucketDTO]:
        grouped: dict[date, list[MuscleVolumeDay]] = {}
        for day in days:
            grouped.setdefault(_bucket_start(day.local_date, granularity), []).append(day)

        buckets: list[MuscleVolumeBucketDTO] = []
        for start in sorted(grouped):
            split: dict[str, Decimal] = {}
            sets = 0
            for day in grouped[start]:
                sets += day.total_sets
                for group, volume in day.volume_by_muscle_group.items():
                    split[group] = split.get(group, _ZERO) + volume
            buckets.append(
                MuscleVolumeBucketDTO(
                    period_start=start,
                    period_end=_bucket_end(start, granularity),
                    volume_by_muscle_group={
                        group: value.quantize(Decimal("0.01")) for group, value in split.items()
                    },
                    total_volume_kg=sum(split.values(), _ZERO).quantize(Decimal("0.01")),
                    total_sets=sets,
                )
            )
        return buckets


class GetFrequencyUseCase:
    """Workouts per week or month, straight from the daily aggregate."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._window = _WindowResolver(uow, clock)

    async def execute(self, query: StatsQuery) -> list[FrequencyBucketDTO]:
        granularity = Granularity(query.granularity)
        async with self._uow:
            start, end, _ = await self._window.resolve(
                query.user_id, query.date_from, query.date_to
            )
            days = await self._uow.summaries.range(query.user_id, date_from=start, date_to=end)

        grouped: dict[date, list[CalendarDay]] = {}
        for day in days:
            grouped.setdefault(_bucket_start(day.local_date, granularity), []).append(day)

        return [
            FrequencyBucketDTO(
                period_start=bucket_start,
                period_end=_bucket_end(bucket_start, granularity),
                workout_count=sum(d.workout_count for d in entries),
                total_volume_kg=sum((d.total_volume_kg for d in entries), _ZERO),
                duration_seconds=sum(d.duration_seconds for d in entries),
            )
            for bucket_start, entries in sorted(grouped.items())
        ]


class ListAllRecordsUseCase:
    """Every current personal record, with the exercise names resolved."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> list[PersonalRecordDTO]:
        async with self._uow:
            records = await self._uow.records.list_current(user_id)
            names = {
                e.id: e.name
                for e in await self._uow.exercises.get_many(
                    [r.exercise_id for r in records], user_id
                )
            }
        return [record_dto(r, exercise_name=names.get(r.exercise_id)) for r in records]


class GetDashboardUseCase:
    """One call, everything the dashboard paints on open.

    Bundled deliberately: each tile is meaningless alone, and a dashboard that fills in
    over five sequential requests reads as broken.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        weight_series: GetWeightSeriesUseCase,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._weight_series = weight_series
        self._clock = clock

    async def execute(self, user_id: UUID) -> DashboardDTO:
        # The weight series opens its own unit of work, so it runs before this one to
        # avoid nesting two sessions over the same connection.
        weight = await self._weight_series.execute(
            WeightSeriesQuery(user_id=user_id, include_projection=True)
        )

        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            today = local_date_for(self._clock.now(), user.timezone)

            this_week_start = _week_start(today)
            last_week_start = this_week_start - timedelta(days=7)

            days = await self._uow.summaries.range(
                user_id, date_from=last_week_start, date_to=today
            )
            streak = await self._uow.streaks.get(user_id)
            latest_measurement = await self._uow.measurements.get_latest(user_id)
            records = await self._uow.records.list_current(user_id)
            recent = sorted(records, key=lambda r: r.achieved_on, reverse=True)[
                :RECENT_RECORD_LIMIT
            ]
            names = {
                e.id: e.name
                for e in await self._uow.exercises.get_many(
                    [r.exercise_id for r in recent], user_id
                )
            }

        return DashboardDTO(
            today=today,
            weight=weight,
            workout_streak=StreakDTO(
                current=streak.workout_current if streak else 0,
                longest=streak.workout_longest if streak else 0,
                last_date=streak.workout_last_date if streak else None,
            ),
            this_week=self._totals(days, records, this_week_start, today),
            last_week=self._totals(
                days, records, last_week_start, this_week_start - timedelta(days=1)
            ),
            latest_measurement=(
                measurement_dto(latest_measurement) if latest_measurement else None
            ),
            recent_records=[record_dto(r, exercise_name=names.get(r.exercise_id)) for r in recent],
            # Nutrition adherence needs the nutrition domain, which does not exist yet.
            # Reported as null rather than zeroes so the client can show "not tracked"
            # instead of claiming the user ate nothing all week.
            nutrition=None,
        )

    @staticmethod
    def _totals(
        days: list[CalendarDay],
        records: list[PersonalRecord],
        start: date,
        end: date,
    ) -> PeriodTotalsDTO:
        window = [d for d in days if start <= d.local_date <= end]
        return PeriodTotalsDTO(
            workout_count=sum(d.workout_count for d in window),
            total_volume_kg=sum((d.total_volume_kg for d in window), _ZERO),
            total_sets=sum(d.total_sets for d in window),
            duration_seconds=sum(d.duration_seconds for d in window),
            # Counted from the records themselves rather than the aggregate's pr_count,
            # because a record superseded later in the window would still be counted there.
            pr_count=sum(1 for r in records if start <= r.achieved_on <= end),
        )
