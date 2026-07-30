"""Body-measurement use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.progress.dto import (
    MeasurementDTO,
    MeasurementSeriesDTO,
    SiteTrendDTO,
)
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError, ValidationError
from coresync.domain.progress.measurements import BodyMeasurement, MeasurementSite
from coresync.domain.progress.services import MeasurementTrendCalculator

DEFAULT_WINDOW_DAYS = 180
MAX_WINDOW_DAYS = 1825


def measurement_dto(measurement: BodyMeasurement) -> MeasurementDTO:
    return MeasurementDTO(
        id=measurement.id,
        local_date=measurement.local_date,
        sites={site.value: value for site, value in measurement.sites.items()},
        note=measurement.note,
        waist_to_hip_ratio=measurement.waist_to_hip_ratio(),
    )


def _parse_sites(raw: dict[str, Decimal | None]) -> dict[MeasurementSite, Decimal]:
    parsed: dict[MeasurementSite, Decimal] = {}
    unknown: list[str] = []
    for key, value in raw.items():
        if value is None:
            continue
        try:
            parsed[MeasurementSite(key)] = value
        except ValueError:
            unknown.append(key)
    if unknown:
        raise ValidationError(
            f"Unknown measurement sites: {', '.join(sorted(unknown))}.",
            details=[
                {
                    "field": "sites",
                    "code": "unknown_site",
                    "message": f"Valid sites: {', '.join(s.value for s in MeasurementSite)}.",
                }
            ],
        )
    return parsed


@dataclass(frozen=True, slots=True)
class LogMeasurementCommand:
    user_id: UUID
    sites: dict[str, Decimal | None]
    local_date: date | None = None
    note: str | None = None


class LogMeasurementUseCase:
    """Upserts the day's row.

    Only the sites in the payload are written. Omitting calves means "I did not measure
    them today", which is not the same as "my calves are now unknown" — so the previous
    reading stands.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, cmd: LogMeasurementCommand) -> MeasurementDTO:
        sites = _parse_sites(cmd.sites)
        now = self._clock.now()

        async with self._uow:
            user = await self._uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise NotFoundError("user", cmd.user_id)
            today = local_date_for(now, user.timezone)
            on = cmd.local_date or today
            if on > today:
                raise ValidationError("You cannot record a measurement in the future.")

            existing = await self._uow.measurements.get_for_date(cmd.user_id, on)
            if existing is not None:
                merged = dict(existing.sites)
                merged.update(sites)
                try:
                    measurement = BodyMeasurement.create(
                        user_id=cmd.user_id,
                        local_date=on,
                        sites=merged,
                        note=cmd.note if cmd.note is not None else existing.note,
                    )
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                # Keep the original row id so the upsert targets the same entry.
                measurement.id = existing.id
            else:
                try:
                    measurement = BodyMeasurement.create(
                        user_id=cmd.user_id, local_date=on, sites=sites, note=cmd.note
                    )
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc

            await self._uow.measurements.upsert(measurement)
            await self._uow.commit()

        return measurement_dto(measurement)


@dataclass(frozen=True, slots=True)
class MeasurementHistoryQuery:
    user_id: UUID
    date_from: date | None = None
    date_to: date | None = None


class ListMeasurementsUseCase:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, query: MeasurementHistoryQuery) -> list[MeasurementDTO]:
        async with self._uow:
            user = await self._uow.users.get_by_id(query.user_id)
            today = local_date_for(self._clock.now(), user.timezone if user else "UTC")
            end = query.date_to or today
            start = query.date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
            if (end - start).days > MAX_WINDOW_DAYS:
                raise ValidationError(f"Ask for at most {MAX_WINDOW_DAYS} days at a time.")
            rows = await self._uow.measurements.list_range(
                query.user_id, date_from=start, date_to=end
            )
        return [measurement_dto(m) for m in rows]


@dataclass(frozen=True, slots=True)
class MeasurementSeriesQuery:
    user_id: UUID
    sites: tuple[str, ...] = field(default_factory=tuple)
    date_from: date | None = None
    date_to: date | None = None


class GetMeasurementSeriesUseCase:
    """Per-site chart series. Defaults to every site when none is named."""

    def __init__(
        self, uow: UnitOfWork, calculator: MeasurementTrendCalculator, clock: Clock
    ) -> None:
        self._uow = uow
        self._calculator = calculator
        self._clock = clock

    async def execute(self, query: MeasurementSeriesQuery) -> MeasurementSeriesDTO:
        sites = [MeasurementSite(s) for s in query.sites] if query.sites else list(MeasurementSite)
        async with self._uow:
            user = await self._uow.users.get_by_id(query.user_id)
            today = local_date_for(self._clock.now(), user.timezone if user else "UTC")
            end = query.date_to or today
            start = query.date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
            raw = await self._uow.measurements.series_for_sites(
                query.user_id, sites, date_from=start, date_to=end
            )

        return MeasurementSeriesDTO(
            trends=[
                SiteTrendDTO(
                    site=trend.site,
                    first_value_cm=trend.first_value,
                    latest_value_cm=trend.latest_value,
                    change_cm=trend.change_cm,
                    points=trend.points,
                )
                for trend in self._calculator.build(raw)
            ]
        )


class DeleteMeasurementUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, measurement_id: UUID) -> None:
        async with self._uow:
            if await self._uow.measurements.get(measurement_id, user_id) is None:
                raise NotFoundError("measurement", measurement_id)
            await self._uow.measurements.delete(measurement_id, user_id)
            await self._uow.commit()
