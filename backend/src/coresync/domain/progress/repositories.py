"""Repository ports for the progress domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from coresync.domain.progress.entities import WeightLog
from coresync.domain.progress.measurements import BodyMeasurement, MeasurementSite
from coresync.domain.progress.photos import PhotoPose, ProgressPhoto, UploadIntent


class WeightLogRepository(Protocol):
    async def get_latest(self, user_id: UUID) -> WeightLog | None: ...

    async def get_for_date(self, user_id: UUID, on: date) -> WeightLog | None: ...

    async def list_range(self, user_id: UUID, start: date, end: date) -> list[WeightLog]: ...

    async def list_all(self, user_id: UUID) -> list[WeightLog]:
        """The whole series, oldest first.

        Needed because an EWMA trend is path-dependent: a backfilled weigh-in changes
        every value after it, so the recalculation cannot work from a window.
        """
        ...

    async def add(self, log: WeightLog) -> None: ...

    async def update(self, log: WeightLog) -> None: ...

    async def update_trends(self, logs: list[WeightLog]) -> None:
        """Persist recomputed trend values in one statement rather than N updates."""
        ...

    async def delete(self, log_id: UUID, user_id: UUID) -> None: ...


class BodyMeasurementRepository(Protocol):
    async def get(self, measurement_id: UUID, user_id: UUID) -> BodyMeasurement | None: ...

    async def get_latest(self, user_id: UUID) -> BodyMeasurement | None: ...

    async def get_for_date(self, user_id: UUID, on: date) -> BodyMeasurement | None: ...

    async def list_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[BodyMeasurement]: ...

    async def series_for_sites(
        self, user_id: UUID, sites: list[MeasurementSite], *, date_from: date, date_to: date
    ) -> dict[str, list[tuple[date, Decimal]]]:
        """Per-site time series for the charts, skipping days a site was not measured."""
        ...

    async def upsert(self, measurement: BodyMeasurement) -> None:
        """One measurement row per day.

        Re-measuring the same day corrects the entry rather than appending a second one,
        which keeps the per-site series single-valued and the charts unambiguous.
        """
        ...

    async def delete(self, measurement_id: UUID, user_id: UUID) -> None: ...


class ProgressPhotoRepository(Protocol):
    async def get(self, photo_id: UUID, user_id: UUID) -> ProgressPhoto | None: ...

    async def get_many(self, photo_ids: list[UUID], user_id: UUID) -> list[ProgressPhoto]: ...

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        pose: PhotoPose | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
    ) -> list[ProgressPhoto]: ...

    async def add(self, photo: ProgressPhoto) -> None: ...

    async def update(self, photo: ProgressPhoto) -> None: ...

    async def soft_delete(self, photo_id: UUID, user_id: UUID) -> None: ...

    async def count_for_day(self, user_id: UUID, on: date) -> int: ...


# ------------------------------------------------------------------ storage port
@dataclass(frozen=True, slots=True)
class StoredObject:
    path: str
    content_type: str
    size_bytes: int


class ObjectStoragePort(Protocol):
    """Private blob storage for progress photos.

    Bytes never pass through the API: the client is handed a credential scoped to one
    object and writes directly. Read access is likewise a short-lived signed URL rather
    than a public path, because a progress photo must never have a URL that outlives the
    session that asked for it (docs/11 §5).
    """

    async def create_upload_credential(
        self,
        *,
        path: str,
        expires_in_seconds: int,
        max_bytes: int,
        content_type: str | None = None,
    ) -> tuple[str, dict[str, str], datetime]:
        """A write-only credential for exactly this object: URL, form fields, expiry.

        A browser-form POST rather than a signed PUT, and the difference is not
        cosmetic. The size limit has to be a *condition of the policy* so that storage
        refuses an oversized body itself. Signing it into a PUT instead makes the exact
        content length part of the signature, which no client can satisfy — a browser
        sets ``Content-Length`` from the body and refuses to let script override it, so
        every upload fails with a signature mismatch.

        The fields are opaque and must be posted back verbatim alongside the file.
        """
        ...

    async def create_read_url(self, *, path: str, expires_in_seconds: int) -> tuple[str, datetime]:
        """A time-limited read URL, served as an attachment."""
        ...

    async def read_bytes(self, path: str) -> bytes | None: ...

    async def write_bytes(self, *, path: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, path: str) -> None: ...

    async def head(self, path: str) -> StoredObject | None:
        """Object metadata, or None if the client never completed the upload."""
        ...

    async def ensure_bucket(self) -> None:
        """Make sure the container exists.

        Called once at boot. A production deployment provisions its container out of
        band, so this is a no-op there and an implementation whose credential cannot
        create one must log rather than raise — being refused is the expected outcome
        for a correctly-scoped production key, not a failure to start.
        """
        ...


class ImageProcessorPort(Protocol):
    """Strips metadata and produces a thumbnail.

    Declared as a port because it is CPU-bound work that runs in a worker in production
    but must be callable inline in tests.
    """

    def process(self, data: bytes) -> ProcessedImage: ...


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    """The sanitised original plus a thumbnail, with the metadata check recorded."""

    image: bytes
    thumbnail: bytes
    width: int
    height: int
    content_type: str
    had_metadata: bool
    metadata_removed: bool


class UploadIntentFactory(Protocol):
    async def create(
        self, *, user_id: UUID, photo_id: UUID, extension: str, content_type: str
    ) -> UploadIntent: ...
