"""SQLAlchemy implementation of the weight-log repository."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.progress.entities import (
    MeasurementContext,
    WeightLog,
    WeightSource,
)
from coresync.infrastructure.database.models.progress import WeightLogModel


def _to_entity(model: WeightLogModel) -> WeightLog:
    return WeightLog(
        id=model.id,
        user_id=model.user_id,
        local_date=model.local_date,
        weight_kg=model.weight_kg,
        body_fat_pct=model.body_fat_pct,
        measurement_context=MeasurementContext(model.measurement_context),
        trend_weight_kg=model.trend_weight_kg,
        source=WeightSource(model.source),
        note=model.note,
    )


def _to_model(entity: WeightLog) -> WeightLogModel:
    return WeightLogModel(
        id=entity.id,
        user_id=entity.user_id,
        local_date=entity.local_date,
        weight_kg=entity.weight_kg,
        body_fat_pct=entity.body_fat_pct,
        measurement_context=entity.measurement_context.value,
        trend_weight_kg=entity.trend_weight_kg,
        source=entity.source.value,
        note=entity.note,
    )


class SqlAlchemyWeightLogRepository:
    EWMA_SMOOTHING = Decimal("0.1")

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(self, user_id: UUID) -> WeightLog | None:
        stmt = (
            select(WeightLogModel)
            .where(WeightLogModel.user_id == user_id)
            .order_by(WeightLogModel.local_date.desc())
            .limit(1)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(model) if model else None

    async def get_for_date(self, user_id: UUID, on: date) -> WeightLog | None:
        stmt = select(WeightLogModel).where(
            WeightLogModel.user_id == user_id,
            WeightLogModel.local_date == on,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(model) if model else None

    async def list_range(self, user_id: UUID, start: date, end: date) -> list[WeightLog]:
        stmt = (
            select(WeightLogModel)
            .where(
                WeightLogModel.user_id == user_id,
                WeightLogModel.local_date >= start,
                WeightLogModel.local_date <= end,
            )
            .order_by(WeightLogModel.local_date)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(m) for m in rows]

    async def list_all(self, user_id: UUID) -> list[WeightLog]:
        """The whole series, oldest first.

        An EWMA trend is path-dependent, so a weigh-in backfilled into the middle of the
        series changes every value after it. Recalculation therefore cannot work from a
        window — it needs the lot.
        """
        stmt = (
            select(WeightLogModel)
            .where(WeightLogModel.user_id == user_id)
            .order_by(WeightLogModel.local_date)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(m) for m in rows]

    async def add(self, log: WeightLog) -> None:
        # Seeds the trend from the most recent entry, which is correct for the common
        # append case. A backfill is corrected by the caller recalculating the series.
        previous = await self.get_latest(log.user_id)
        log.apply_trend(previous.trend_weight_kg if previous else None, self.EWMA_SMOOTHING)
        self._session.add(_to_model(log))
        await self._session.flush()

    async def update_trends(self, logs: list[WeightLog]) -> None:
        """Persist recomputed trend values in one statement rather than N updates."""
        if not logs:
            return
        await self._session.execute(
            update(WeightLogModel),
            [{"id": log.id, "trend_weight_kg": log.trend_weight_kg} for log in logs],
        )
        await self._session.flush()

    async def update(self, log: WeightLog) -> None:
        model = await self._session.get(WeightLogModel, log.id)
        if model is None or model.user_id != log.user_id:
            raise ValueError(f"weight log {log.id} does not exist for this user")
        model.weight_kg = log.weight_kg
        model.body_fat_pct = log.body_fat_pct
        model.measurement_context = log.measurement_context.value
        model.trend_weight_kg = log.trend_weight_kg
        model.note = log.note
        await self._session.flush()

    async def delete(self, log_id: UUID, user_id: UUID) -> None:
        stmt = select(WeightLogModel).where(
            WeightLogModel.id == log_id,
            WeightLogModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()
