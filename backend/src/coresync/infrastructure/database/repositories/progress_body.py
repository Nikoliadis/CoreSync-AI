"""SQLAlchemy repositories for body measurements and progress photos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.progress.measurements import BodyMeasurement, MeasurementSite
from coresync.domain.progress.photos import (
    PhotoPose,
    PhotoVisibility,
    ProcessingStatus,
    ProgressPhoto,
)
from coresync.infrastructure.database.models.progress_body import (
    BodyMeasurementModel,
    ProgressPhotoModel,
)


def _column_for(site: MeasurementSite) -> str:
    return f"{site.value}_cm"


def _measurement_to_entity(model: BodyMeasurementModel) -> BodyMeasurement:
    sites: dict[MeasurementSite, Decimal] = {}
    for site in MeasurementSite:
        value = getattr(model, _column_for(site))
        if value is not None:
            sites[site] = value
    return BodyMeasurement(
        id=model.id,
        user_id=model.user_id,
        local_date=model.local_date,
        sites=sites,
        note=model.note,
    )


class SqlAlchemyBodyMeasurementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, measurement_id: UUID, user_id: UUID) -> BodyMeasurement | None:
        stmt = select(BodyMeasurementModel).where(
            BodyMeasurementModel.id == measurement_id,
            BodyMeasurementModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _measurement_to_entity(model) if model else None

    async def get_latest(self, user_id: UUID) -> BodyMeasurement | None:
        stmt = (
            select(BodyMeasurementModel)
            .where(BodyMeasurementModel.user_id == user_id)
            .order_by(BodyMeasurementModel.local_date.desc())
            .limit(1)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _measurement_to_entity(model) if model else None

    async def get_for_date(self, user_id: UUID, on: date) -> BodyMeasurement | None:
        stmt = select(BodyMeasurementModel).where(
            BodyMeasurementModel.user_id == user_id,
            BodyMeasurementModel.local_date == on,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _measurement_to_entity(model) if model else None

    async def list_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[BodyMeasurement]:
        stmt = (
            select(BodyMeasurementModel)
            .where(
                BodyMeasurementModel.user_id == user_id,
                BodyMeasurementModel.local_date >= date_from,
                BodyMeasurementModel.local_date <= date_to,
            )
            .order_by(BodyMeasurementModel.local_date)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_measurement_to_entity(m) for m in rows]

    async def series_for_sites(
        self,
        user_id: UUID,
        sites: list[MeasurementSite],
        *,
        date_from: date,
        date_to: date,
    ) -> dict[str, list[tuple[date, Decimal]]]:
        """Per-site series, skipping days a site was not measured.

        Selecting only the requested columns rather than whole rows: a year of ten-site
        history is a lot of nulls to ship to draw one chart.
        """
        if not sites:
            return {}
        columns = [getattr(BodyMeasurementModel, _column_for(site)) for site in sites]
        stmt = (
            select(BodyMeasurementModel.local_date, *columns)
            .where(
                BodyMeasurementModel.user_id == user_id,
                BodyMeasurementModel.local_date >= date_from,
                BodyMeasurementModel.local_date <= date_to,
            )
            .order_by(BodyMeasurementModel.local_date)
        )
        series: dict[str, list[tuple[date, Decimal]]] = {site.value: [] for site in sites}
        for row in (await self._session.execute(stmt)).all():
            on = row[0]
            for offset, site in enumerate(sites, start=1):
                value = row[offset]
                if value is not None:
                    series[site.value].append((on, value))
        return {site: points for site, points in series.items() if points}

    async def upsert(self, measurement: BodyMeasurement) -> None:
        """One row per day, so re-measuring corrects rather than appends.

        Only the sites present in the payload are written; a site omitted this time keeps
        whatever was recorded before, because "I did not measure my calves today" is not
        the same statement as "my calves are now unknown".
        """
        values: dict[str, object] = {
            "id": measurement.id,
            "user_id": measurement.user_id,
            "local_date": measurement.local_date,
            "note": measurement.note,
        }
        for site, value in measurement.sites.items():
            values[_column_for(site)] = value

        stmt = pg_insert(BodyMeasurementModel).values(**values)
        updatable = {
            key: stmt.excluded[key] for key in values if key not in ("id", "user_id", "local_date")
        }
        stmt = stmt.on_conflict_do_update(index_elements=["user_id", "local_date"], set_=updatable)
        await self._session.execute(stmt)
        await self._session.flush()

    async def delete(self, measurement_id: UUID, user_id: UUID) -> None:
        stmt = select(BodyMeasurementModel).where(
            BodyMeasurementModel.id == measurement_id,
            BodyMeasurementModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()


def _photo_to_entity(model: ProgressPhotoModel) -> ProgressPhoto:
    return ProgressPhoto(
        id=model.id,
        user_id=model.user_id,
        local_date=model.local_date,
        pose=PhotoPose(model.pose),
        blob_path=model.blob_path,
        thumbnail_path=model.thumbnail_path,
        width=model.width,
        height=model.height,
        bytes_size=model.bytes_size,
        weight_at_capture_kg=model.weight_at_capture_kg,
        visibility=PhotoVisibility(model.visibility),
        processing_status=ProcessingStatus(model.processing_status),
        exif_stripped_at=model.exif_stripped_at,
        note=model.note,
        created_at=model.created_at,
    )


class SqlAlchemyProgressPhotoRepository:
    """Every read is scoped to the owner.

    Access to another user's progress photo is a critical, page-immediately incident
    (docs/11 §7), so there is no method here that can return one.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, photo_id: UUID, user_id: UUID) -> ProgressPhoto | None:
        stmt = select(ProgressPhotoModel).where(
            ProgressPhotoModel.id == photo_id,
            ProgressPhotoModel.user_id == user_id,
            ProgressPhotoModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _photo_to_entity(model) if model else None

    async def get_many(self, photo_ids: list[UUID], user_id: UUID) -> list[ProgressPhoto]:
        if not photo_ids:
            return []
        stmt = select(ProgressPhotoModel).where(
            ProgressPhotoModel.id.in_(photo_ids),
            ProgressPhotoModel.user_id == user_id,
            ProgressPhotoModel.deleted_at.is_(None),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_photo_to_entity(m) for m in rows]

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        pose: PhotoPose | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
    ) -> list[ProgressPhoto]:
        stmt = select(ProgressPhotoModel).where(
            ProgressPhotoModel.user_id == user_id,
            ProgressPhotoModel.deleted_at.is_(None),
        )
        if pose is not None:
            stmt = stmt.where(ProgressPhotoModel.pose == pose.value)
        if date_from is not None:
            stmt = stmt.where(ProgressPhotoModel.local_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(ProgressPhotoModel.local_date <= date_to)
        stmt = stmt.order_by(ProgressPhotoModel.local_date.desc()).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_photo_to_entity(m) for m in rows]

    async def add(self, photo: ProgressPhoto) -> None:
        self._session.add(
            ProgressPhotoModel(
                id=photo.id,
                user_id=photo.user_id,
                local_date=photo.local_date,
                pose=photo.pose.value,
                blob_path=photo.blob_path,
                thumbnail_path=photo.thumbnail_path,
                width=photo.width,
                height=photo.height,
                bytes_size=photo.bytes_size,
                weight_at_capture_kg=photo.weight_at_capture_kg,
                visibility=photo.visibility.value,
                processing_status=photo.processing_status.value,
                exif_stripped_at=photo.exif_stripped_at,
                note=photo.note,
            )
        )
        await self._session.flush()

    async def update(self, photo: ProgressPhoto) -> None:
        model = await self._session.get(ProgressPhotoModel, photo.id)
        if model is None or model.user_id != photo.user_id:
            raise ValueError(f"progress photo {photo.id} does not exist for this user")
        model.pose = photo.pose.value
        model.thumbnail_path = photo.thumbnail_path
        model.width = photo.width
        model.height = photo.height
        model.bytes_size = photo.bytes_size
        model.weight_at_capture_kg = photo.weight_at_capture_kg
        model.visibility = photo.visibility.value
        model.processing_status = photo.processing_status.value
        model.exif_stripped_at = photo.exif_stripped_at
        model.note = photo.note
        await self._session.flush()

    async def soft_delete(self, photo_id: UUID, user_id: UUID) -> None:
        """Marks the row deleted; the caller is responsible for removing the bytes.

        Deliberately not a hard delete — the erasure job needs the blob paths to clean up
        storage, and a row removed here would orphan the objects it pointed at.
        """
        await self._session.execute(
            update(ProgressPhotoModel)
            .where(
                ProgressPhotoModel.id == photo_id,
                ProgressPhotoModel.user_id == user_id,
            )
            .values(deleted_at=func.now())
        )
        await self._session.flush()

    async def count_for_day(self, user_id: UUID, on: date) -> int:
        stmt = select(func.count(ProgressPhotoModel.id)).where(
            ProgressPhotoModel.user_id == user_id,
            ProgressPhotoModel.local_date == on,
            ProgressPhotoModel.deleted_at.is_(None),
        )
        return int((await self._session.execute(stmt)).scalar_one())
