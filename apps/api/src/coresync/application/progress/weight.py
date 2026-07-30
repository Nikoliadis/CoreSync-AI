"""Weight logging and the EWMA trend.

The one thing that makes this more than CRUD: the trend is path-dependent. Inserting,
editing or deleting a weigh-in changes every trend value after it, so each write is
followed by a recalculation of the whole series. A window would leave the chart bent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.progress.dto import (
    GoalProjectionDTO,
    WeightLogDTO,
    WeightPointDTO,
    WeightSeriesDTO,
)
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError, ValidationError
from coresync.core.logging import get_logger
from coresync.domain.progress.entities import (
    MeasurementContext,
    WeightLog,
    WeightSource,
)
from coresync.domain.progress.services import GoalProjector, WeightTrendCalculator

logger = get_logger(__name__)

MIN_WEIGHT_KG = Decimal("20")
MAX_WEIGHT_KG = Decimal("500")
DEFAULT_WINDOW_DAYS = 90
MAX_WINDOW_DAYS = 1825  # five years


def _log_dto(log: WeightLog) -> WeightLogDTO:
    return WeightLogDTO(
        id=log.id,
        local_date=log.local_date,
        weight_kg=log.weight_kg,
        trend_weight_kg=log.trend_weight_kg,
        body_fat_pct=log.body_fat_pct,
        measurement_context=log.measurement_context.value,
        source=log.source.value,
        note=log.note,
    )


@dataclass(frozen=True, slots=True)
class LogWeightCommand:
    user_id: UUID
    weight_kg: Decimal
    local_date: date | None = None
    body_fat_pct: Decimal | None = None
    measurement_context: str = "unspecified"
    source: str = "manual"
    note: str | None = None


class LogWeightUseCase:
    """Upserts on the day, then recalculates the trend series.

    One weigh-in per day is a schema constraint: multiple daily weights are noise, not
    signal, and they corrupt the EWMA. Re-logging corrects the day.
    """

    def __init__(self, uow: UnitOfWork, calculator: WeightTrendCalculator, clock: Clock) -> None:
        self._uow = uow
        self._calculator = calculator
        self._clock = clock

    async def execute(self, cmd: LogWeightCommand) -> WeightLogDTO:
        if not MIN_WEIGHT_KG <= cmd.weight_kg <= MAX_WEIGHT_KG:
            raise ValidationError(
                f"A weight of {cmd.weight_kg} kg is implausible — check the units.",
                details=[
                    {
                        "field": "weightKg",
                        "code": "out_of_range",
                        "message": f"Expected between {MIN_WEIGHT_KG} and {MAX_WEIGHT_KG} kg.",
                    }
                ],
            )
        if cmd.body_fat_pct is not None and not (Decimal(0) < cmd.body_fat_pct < Decimal(75)):
            raise ValidationError("That body-fat percentage is implausible.")

        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise NotFoundError("user", cmd.user_id)
            on = cmd.local_date or local_date_for(now, user.timezone)
            if on > local_date_for(now, user.timezone):
                raise ValidationError("You cannot log a weigh-in in the future.")

            existing = await self._uow.weights.get_for_date(cmd.user_id, on)
            if existing is not None:
                existing.weight_kg = cmd.weight_kg
                existing.body_fat_pct = cmd.body_fat_pct
                existing.measurement_context = MeasurementContext(cmd.measurement_context)
                existing.note = cmd.note
                await self._uow.weights.update(existing)
                stored = existing
            else:
                stored = WeightLog.create(
                    user_id=cmd.user_id,
                    local_date=on,
                    weight_kg=cmd.weight_kg,
                    body_fat_pct=cmd.body_fat_pct,
                    source=WeightSource(cmd.source),
                    context=MeasurementContext(cmd.measurement_context),
                    note=cmd.note,
                )
                await self._uow.weights.add(stored)

            recalculated = await self._recalculate(cmd.user_id)
            await self._uow.commit()

        # Return the freshly trended row rather than the pre-recalculation one, so the
        # client's optimistic update matches what the chart will show.
        trended = next((log for log in recalculated if log.id == stored.id), stored)
        return _log_dto(trended)

    async def _recalculate(self, user_id: UUID) -> list[WeightLog]:
        series = await self._uow.weights.list_all(user_id)
        recalculated = self._calculator.recalculate(series)
        await self._uow.weights.update_trends(recalculated)
        return recalculated


@dataclass(frozen=True, slots=True)
class WeightSeriesQuery:
    user_id: UUID
    date_from: date | None = None
    date_to: date | None = None
    include_projection: bool = True


class GetWeightSeriesUseCase:
    """The chart payload: raw dots, trend line, and the goal projection."""

    def __init__(
        self,
        uow: UnitOfWork,
        calculator: WeightTrendCalculator,
        projector: GoalProjector,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._calculator = calculator
        self._projector = projector
        self._clock = clock

    async def execute(self, query: WeightSeriesQuery) -> WeightSeriesDTO:
        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(query.user_id)
            if user is None:
                raise NotFoundError("user", query.user_id)
            today = local_date_for(now, user.timezone)
            end = query.date_to or today
            start = query.date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
            if (end - start).days > MAX_WINDOW_DAYS:
                raise ValidationError(f"Ask for at most {MAX_WINDOW_DAYS} days at a time.")

            # The trend is computed over the whole history, then sliced to the window:
            # starting the EWMA at the window edge would show a trend that snaps to the
            # first visible reading rather than continuing from what came before.
            full_series = await self._uow.weights.list_all(query.user_id)
            trend = self._calculator.build(full_series)

            goal = (
                await self._uow.goals.get_current(query.user_id)
                if query.include_projection
                else None
            )

        windowed = [p for p in trend.points if start <= p.local_date <= end]
        projection = None
        if (
            goal is not None
            and goal.target_weight_kg is not None
            and trend.latest_trend_kg is not None
            and trend.weekly_rate_kg is not None
        ):
            projected = self._projector.project(
                current_trend_kg=trend.latest_trend_kg,
                target_weight_kg=goal.target_weight_kg,
                weekly_rate_kg=trend.weekly_rate_kg,
                today=today,
            )
            if projected is not None:
                projection = GoalProjectionDTO(
                    target_weight_kg=projected.target_weight_kg,
                    weekly_rate_kg=projected.weekly_rate_kg,
                    weeks_remaining=projected.weeks_remaining,
                    projected_date=projected.projected_date,
                    is_moving_away=projected.is_moving_away,
                )

        return WeightSeriesDTO(
            points=[
                WeightPointDTO(
                    local_date=point.local_date,
                    weight_kg=point.weight_kg,
                    trend_kg=point.trend_kg,
                )
                for point in windowed
            ],
            latest_weight_kg=trend.latest_weight_kg,
            latest_trend_kg=trend.latest_trend_kg,
            change_kg=trend.change_kg,
            weekly_rate_kg=trend.weekly_rate_kg,
            projection=projection,
        )


class DeleteWeightLogUseCase:
    def __init__(self, uow: UnitOfWork, calculator: WeightTrendCalculator) -> None:
        self._uow = uow
        self._calculator = calculator

    async def execute(self, user_id: UUID, log_id: UUID) -> None:
        async with self._uow:
            await self._uow.weights.delete(log_id, user_id)
            # Removing a point mid-series changes every trend value after it.
            series = await self._uow.weights.list_all(user_id)
            await self._uow.weights.update_trends(self._calculator.recalculate(series))
            await self._uow.commit()
