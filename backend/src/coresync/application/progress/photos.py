"""Progress-photo use cases.

The shape of this feature is dictated by one rule from docs/11 §5: a progress photo must
not be readable until its metadata has been stripped. Everything below follows from it.

The flow is three steps, and it is three rather than one on purpose:

1. ``RequestPhotoUploadUseCase`` writes a ``pending`` row and hands back a credential
   scoped to exactly one object. The bytes go straight to storage; the API never holds
   them.
2. ``FinalizePhotoUseCase`` is called once the upload lands. It reads the object back,
   re-encodes it without metadata, writes the sanitised image and a thumbnail, and only
   then marks the row ready.
3. ``ListPhotosUseCase`` mints short-lived read URLs — and only for rows that made it
   through step 2.

A failure at step 2 leaves the row ``failed`` and unreadable, which is the outcome that
matters: the fallback is "this photo never appears", never "this photo appears with its
original EXIF".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.progress.dto import PhotoComparisonDTO, PhotoDTO, UploadIntentDTO
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import ConflictError, NotFoundError, ValidationError
from coresync.core.logging import get_logger
from coresync.domain.progress.photos import (
    ALLOWED_CONTENT_TYPES,
    MAX_UPLOAD_BYTES,
    PhotoComparison,
    PhotoPose,
    ProcessingStatus,
    ProgressPhoto,
    blob_path_for,
    thumbnail_path_for,
)
from coresync.domain.progress.repositories import ImageProcessorPort, ObjectStoragePort

logger = get_logger(__name__)

#: A cap per day, not per account. Someone photographing three poses morning and evening
#: is normal; forty in an afternoon is a script, and every one of them costs storage that
#: is never reclaimed because the rows are soft-deleted.
MAX_PHOTOS_PER_DAY = 12

#: How far back the timeline reaches by default.
DEFAULT_WINDOW_DAYS = 365

_EXTENSION_FOR_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
    "image/webp": "webp",
}


def photo_dto(
    photo: ProgressPhoto,
    *,
    url: str | None = None,
    thumbnail_url: str | None = None,
    url_expires_at: datetime | None = None,
) -> PhotoDTO:
    return PhotoDTO(
        id=photo.id,
        local_date=photo.local_date,
        pose=photo.pose.value,
        processing_status=photo.processing_status.value,
        is_ready=photo.is_readable,
        url=url,
        thumbnail_url=thumbnail_url,
        url_expires_at=url_expires_at,
        width=photo.width,
        height=photo.height,
        weight_at_capture_kg=photo.weight_at_capture_kg,
        note=photo.note,
    )


async def signed_photo_dto(
    photo: ProgressPhoto, storage: ObjectStoragePort, ttl_seconds: int
) -> PhotoDTO:
    """A photo with read URLs, or without them if it is not readable yet.

    The single gate for handing out a URL, shared by the list and the comparison so
    there is one place where the rule lives. ``is_readable`` is false unless processing
    finished *and* the metadata strip was recorded, so an un-stripped photo cannot be
    given a URL even if some other part of the system marked it ready by mistake.
    """
    if not photo.is_readable:
        return photo_dto(photo)

    url, expires_at = await storage.create_read_url(
        path=photo.blob_path, expires_in_seconds=ttl_seconds
    )
    thumbnail_url = None
    if photo.thumbnail_path:
        thumbnail_url, _ = await storage.create_read_url(
            path=photo.thumbnail_path, expires_in_seconds=ttl_seconds
        )
    return photo_dto(photo, url=url, thumbnail_url=thumbnail_url, url_expires_at=expires_at)


# ------------------------------------------------------------------------ upload
@dataclass(frozen=True, slots=True)
class RequestUploadCommand:
    user_id: UUID
    content_type: str
    pose: str = "front"
    local_date: date | None = None
    note: str | None = None


class RequestPhotoUploadUseCase:
    """Reserves a row and issues a write-only credential for one object.

    The row is written *before* the bytes exist, so a client that uploads and then loses
    its connection leaves something to find rather than an orphaned object with no owner.
    The row is ``pending``, which is unreadable, so the reservation is not visible as a
    photo until it has been through processing.
    """

    def __init__(self, uow: UnitOfWork, storage: ObjectStoragePort, clock: Clock) -> None:
        self._uow = uow
        self._storage = storage
        self._clock = clock

    async def execute(self, cmd: RequestUploadCommand, *, ttl_seconds: int) -> UploadIntentDTO:
        content_type = cmd.content_type.lower().strip()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValidationError(
                f"Unsupported image type: {cmd.content_type}.",
                details=[
                    {
                        "field": "contentType",
                        "code": "unsupported_type",
                        "message": f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}.",
                    }
                ],
            )

        try:
            pose = PhotoPose(cmd.pose)
        except ValueError as exc:
            raise ValidationError(f"Unknown pose: {cmd.pose}.") from exc

        async with self._uow:
            user = await self._uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise NotFoundError("user", cmd.user_id)

            today = local_date_for(self._clock.now(), user.timezone)
            on = cmd.local_date or today
            if on > today:
                raise ValidationError("You cannot add a photo dated in the future.")

            taken_today = await self._uow.photos.count_for_day(cmd.user_id, on)
            if taken_today >= MAX_PHOTOS_PER_DAY:
                raise ConflictError(
                    f"That is {MAX_PHOTOS_PER_DAY} photos for one day, which is the limit."
                )

            # Snapshotted now so a comparison later can show the weight either side
            # without a temporal join — and so editing a weight log afterwards does not
            # silently rewrite what a photo was taken at.
            weight = await self._uow.weights.get_for_date(cmd.user_id, on)

            photo = ProgressPhoto.create(
                user_id=cmd.user_id,
                local_date=on,
                pose=pose,
                blob_path="",
                weight_at_capture_kg=weight.weight_kg if weight else None,
                note=cmd.note,
            )
            photo.blob_path = blob_path_for(
                user_id=cmd.user_id,
                photo_id=photo.id,
                extension=_EXTENSION_FOR_TYPE[content_type],
            )

            await self._uow.photos.add(photo)
            await self._uow.commit()

        url, fields, expires_at = await self._storage.create_upload_credential(
            path=photo.blob_path,
            expires_in_seconds=ttl_seconds,
            max_bytes=MAX_UPLOAD_BYTES,
            content_type=content_type,
        )
        return UploadIntentDTO(
            photo_id=photo.id,
            upload_url=url,
            fields=fields,
            expires_at=expires_at,
            max_bytes=MAX_UPLOAD_BYTES,
            required_content_type=content_type,
        )


class FinalizePhotoUseCase:
    """Strips the metadata, then — and only then — makes the photo readable.

    Runs in a worker in production and inline in tests, which is why the image processor
    is a port. Idempotent: calling it twice on a ready photo is a no-op rather than a
    second re-encode, because a retried Celery task and an impatient client both do
    exactly that.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        storage: ObjectStoragePort,
        processor: ImageProcessorPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._processor = processor
        self._clock = clock

    async def execute(self, *, photo_id: UUID, user_id: UUID, ttl_seconds: int) -> PhotoDTO:
        async with self._uow:
            photo = await self._uow.photos.get(photo_id, user_id)
            if photo is None:
                raise NotFoundError("progress photo", photo_id)

            if photo.processing_status is ProcessingStatus.READY:
                return await signed_photo_dto(photo, self._storage, ttl_seconds)

            stored = await self._storage.head(photo.blob_path)
            if stored is None:
                # The credential was issued but nothing was written. Not an error the
                # user caused — their upload failed — so it says so plainly.
                raise ConflictError("The upload did not finish. Try adding the photo again.")

            if stored.size_bytes > MAX_UPLOAD_BYTES:
                await self._fail(photo, reason="too_large")
                raise ValidationError("That image is larger than 15 MB.")

            photo.begin_processing()
            await self._uow.photos.update(photo)
            await self._uow.commit()

        raw = await self._storage.read_bytes(photo.blob_path)
        if raw is None:  # pragma: no cover - lost between head and get
            await self._mark_failed(photo_id, user_id)
            raise ConflictError("The upload did not finish. Try adding the photo again.")

        try:
            # Off the event loop. Decoding and re-encoding a 15 MB photo is hundreds of
            # milliseconds of CPU, and doing it inline would stall every other request
            # this process is serving. Pillow releases the GIL for the heavy parts, so a
            # thread is genuinely parallel here rather than just tidier.
            processed = await asyncio.to_thread(self._processor.process, raw)
        except Exception as exc:
            # Anything at all: a corrupt file, an unsupported codec, a metadata check
            # that did not come back clean. The photo stays unreadable in every case.
            logger.warning("photo_processing_failed", photo_id=str(photo_id), error=str(exc))
            await self._mark_failed(photo_id, user_id)
            raise ValidationError("That image could not be processed.") from exc

        thumbnail_path = thumbnail_path_for(photo.blob_path)
        # The sanitised image overwrites the original at the same key, so the bytes that
        # carried the EXIF stop existing rather than lingering beside the clean copy.
        await self._storage.write_bytes(
            path=photo.blob_path, data=processed.image, content_type=processed.content_type
        )
        await self._storage.write_bytes(
            path=thumbnail_path, data=processed.thumbnail, content_type=processed.content_type
        )

        async with self._uow:
            current = await self._uow.photos.get(photo_id, user_id)
            if current is None:  # pragma: no cover - deleted mid-processing
                raise NotFoundError("progress photo", photo_id)
            current.mark_ready(
                at=self._clock.now(),
                width=processed.width,
                height=processed.height,
                bytes_size=len(processed.image),
                thumbnail_path=thumbnail_path,
            )
            await self._uow.photos.update(current)
            await self._uow.commit()

        logger.info(
            "photo_ready",
            photo_id=str(photo_id),
            had_metadata=processed.had_metadata,
            bytes_size=len(processed.image),
        )
        # Returned with URLs, because the caller has just uploaded this photo and is
        # about to show it. Making them list again to see what they just added would
        # be a round trip for nothing.
        return await signed_photo_dto(current, self._storage, ttl_seconds)

    async def _fail(self, photo: ProgressPhoto, *, reason: str) -> None:
        photo.mark_failed()
        await self._uow.photos.update(photo)
        await self._uow.commit()
        logger.warning("photo_rejected", photo_id=str(photo.id), reason=reason)

    async def _mark_failed(self, photo_id: UUID, user_id: UUID) -> None:
        async with self._uow:
            photo = await self._uow.photos.get(photo_id, user_id)
            if photo is None:  # pragma: no cover
                return
            photo.mark_failed()
            await self._uow.photos.update(photo)
            await self._uow.commit()


# -------------------------------------------------------------------- reading
@dataclass(frozen=True, slots=True)
class PhotoListQuery:
    user_id: UUID
    pose: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: int = 100


class ListPhotosUseCase:
    """The timeline, with a signed URL per photo.

    URLs are minted per request rather than stored, so a response body that ends up in a
    log or a cache stops being useful within minutes. Photos still processing are listed
    — the client shows them as pending — but carry no URL at all.
    """

    def __init__(self, uow: UnitOfWork, storage: ObjectStoragePort) -> None:
        self._uow = uow
        self._storage = storage

    async def execute(self, query: PhotoListQuery, *, ttl_seconds: int) -> list[PhotoDTO]:
        pose = PhotoPose(query.pose) if query.pose else None

        async with self._uow:
            photos = await self._uow.photos.list_for_user(
                query.user_id,
                pose=pose,
                date_from=query.date_from,
                date_to=query.date_to,
                limit=min(query.limit, 200),
            )

        return [await signed_photo_dto(photo, self._storage, ttl_seconds) for photo in photos]


class ComparePhotosUseCase:
    """Two photos, with the numbers between them.

    Refuses a comparison where either photo is not ready, rather than returning one side.
    A half-rendered comparison is the case where a client is most likely to fall back to
    showing the raw blob path.
    """

    def __init__(self, uow: UnitOfWork, storage: ObjectStoragePort) -> None:
        self._uow = uow
        self._storage = storage

    async def execute(
        self, *, user_id: UUID, first_id: UUID, second_id: UUID, ttl_seconds: int
    ) -> PhotoComparisonDTO:
        if first_id == second_id:
            raise ValidationError("Pick two different photos.")

        async with self._uow:
            found = await self._uow.photos.get_many([first_id, second_id], user_id)

        by_id = {photo.id: photo for photo in found}
        missing = [pid for pid in (first_id, second_id) if pid not in by_id]
        if missing:
            raise NotFoundError("progress photo", missing[0])

        first, second = by_id[first_id], by_id[second_id]
        if not (first.is_readable and second.is_readable):
            raise ConflictError("One of those photos is still being processed.")

        # Ordered by date rather than by argument, so the slider always runs older to
        # newer no matter which one the user tapped first.
        earlier, later = sorted((first, second), key=lambda photo: photo.local_date)
        comparison = PhotoComparison(earlier=earlier, later=later)

        return PhotoComparisonDTO(
            earlier=await signed_photo_dto(earlier, self._storage, ttl_seconds),
            later=await signed_photo_dto(later, self._storage, ttl_seconds),
            days_between=comparison.days_between,
            weight_delta_kg=comparison.weight_delta_kg,
            poses_match=comparison.poses_match,
        )


class DeletePhotoUseCase:
    """Soft-deletes the row and hard-deletes the bytes.

    Deliberately asymmetric. The row is kept for the audit trail the rest of the schema
    assumes, but the image itself is removed from storage immediately: "delete my photo"
    means the file is gone, and a soft delete that leaves the object retrievable by
    anyone who kept a signed URL would not be that.
    """

    def __init__(self, uow: UnitOfWork, storage: ObjectStoragePort) -> None:
        self._uow = uow
        self._storage = storage

    async def execute(self, *, photo_id: UUID, user_id: UUID) -> None:
        async with self._uow:
            photo = await self._uow.photos.get(photo_id, user_id)
            if photo is None:
                raise NotFoundError("progress photo", photo_id)
            await self._uow.photos.soft_delete(photo_id, user_id)
            await self._uow.commit()

        # After the commit: a storage failure must not leave a row the user was told was
        # deleted. An orphaned object is a cleanup job; an undeletable photo is a bug the
        # user experiences.
        await self._storage.delete(photo.blob_path)
        if photo.thumbnail_path:
            await self._storage.delete(photo.thumbnail_path)


__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "MAX_PHOTOS_PER_DAY",
    "ComparePhotosUseCase",
    "DeletePhotoUseCase",
    "FinalizePhotoUseCase",
    "ListPhotosUseCase",
    "PhotoListQuery",
    "RequestPhotoUploadUseCase",
    "RequestUploadCommand",
    "photo_dto",
    "signed_photo_dto",
]
