"""Progress photos.

The most sensitive data in the system. Intimate images, routinely carrying GPS
coordinates of the user's home in their EXIF (docs/11 §5). The rules encoded here:

- Bytes never pass through the API. The client uploads directly to a private container
  using a write-only, single-blob, short-lived credential.
- ``private`` is the only default, and the schema treats anything else as a deliberate,
  explicit act.
- A photo is not readable until processing has stripped its metadata. ``pending`` and
  ``ready`` are therefore a security boundary, not just a progress indicator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from coresync.core.ids import uuid7


class PhotoPose(StrEnum):
    FRONT = "front"
    SIDE = "side"
    BACK = "back"
    CUSTOM = "custom"


class PhotoVisibility(StrEnum):
    """No public option exists.

    Deliberately not a superset of the session visibility enum: there is no product
    reason for a progress photo to be world-readable, and offering the value is how it
    eventually gets set.
    """

    PRIVATE = "private"
    SHARED_LINK = "shared_link"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


# 15 MB, matching the limit the upload credential itself enforces (docs/11 §5).
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/heic", "image/webp"})


@dataclass(slots=True)
class ProgressPhoto:
    """Metadata only. The bytes live in a private container."""

    id: UUID
    user_id: UUID
    local_date: date
    pose: PhotoPose
    blob_path: str
    thumbnail_path: str | None = None
    width: int | None = None
    height: int | None = None
    bytes_size: int | None = None
    # Snapshotted so a comparison can show "78.2 kg -> 75.6 kg" without a temporal join.
    weight_at_capture_kg: Decimal | None = None
    visibility: PhotoVisibility = PhotoVisibility.PRIVATE
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    exif_stripped_at: datetime | None = None
    note: str | None = None
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        pose: PhotoPose,
        blob_path: str,
        weight_at_capture_kg: Decimal | None = None,
        note: str | None = None,
        photo_id: UUID | None = None,
    ) -> ProgressPhoto:
        return cls(
            id=photo_id or uuid7(),
            user_id=user_id,
            local_date=local_date,
            pose=pose,
            blob_path=blob_path,
            weight_at_capture_kg=weight_at_capture_kg,
            note=note,
        )

    @property
    def is_readable(self) -> bool:
        """Whether a read URL may be issued.

        A photo that has not been through processing still carries its original EXIF, so
        handing out a URL for it would leak the location it was taken.
        """
        return (
            self.processing_status is ProcessingStatus.READY and self.exif_stripped_at is not None
        )

    def begin_processing(self) -> None:
        self.processing_status = ProcessingStatus.PROCESSING

    def mark_ready(
        self,
        *,
        at: datetime,
        width: int,
        height: int,
        bytes_size: int,
        thumbnail_path: str,
    ) -> None:
        self.processing_status = ProcessingStatus.READY
        self.exif_stripped_at = at
        self.width = width
        self.height = height
        self.bytes_size = bytes_size
        self.thumbnail_path = thumbnail_path

    def mark_failed(self) -> None:
        self.processing_status = ProcessingStatus.FAILED

    def is_owned_by(self, user_id: UUID) -> bool:
        return self.user_id == user_id


@dataclass(frozen=True, slots=True)
class PhotoComparison:
    """Two photos side by side, with the deltas the user actually wants to read."""

    earlier: ProgressPhoto
    later: ProgressPhoto

    @property
    def days_between(self) -> int:
        return (self.later.local_date - self.earlier.local_date).days

    @property
    def weight_delta_kg(self) -> Decimal | None:
        if self.earlier.weight_at_capture_kg is None or self.later.weight_at_capture_kg is None:
            return None
        return self.later.weight_at_capture_kg - self.earlier.weight_at_capture_kg

    @property
    def poses_match(self) -> bool:
        """Comparing a front shot to a back shot tells the user nothing."""
        return self.earlier.pose is self.later.pose


@dataclass(frozen=True, slots=True)
class UploadIntent:
    """A write-only credential for exactly one blob.

    Scoped this narrowly because a broader credential leaking would expose every user's
    photos, and the client only ever needs to write the one file it just captured.
    """

    photo_id: UUID
    blob_path: str
    upload_url: str
    #: Opaque policy fields, posted back verbatim with the file. They carry the signature
    #: and the size limit, which is what makes storage — rather than us, afterwards —
    #: the thing that refuses an oversized upload.
    fields: dict[str, str]
    expires_at: datetime
    max_bytes: int = MAX_UPLOAD_BYTES
    required_content_type: str | None = None


def blob_path_for(*, user_id: UUID, photo_id: UUID, extension: str) -> str:
    """Deterministic, user-partitioned object key.

    The user id leads so a storage-level prefix policy can scope access per user, and so
    an accidental listing cannot enumerate across accounts.
    """
    safe = extension.lower().lstrip(".")
    if safe not in {"jpg", "jpeg", "png", "heic", "webp"}:
        raise ValueError(f"unsupported image extension: {extension}")
    return f"progress-photos/{user_id}/{photo_id}.{safe}"


def thumbnail_path_for(blob_path: str) -> str:
    base, _, _ = blob_path.rpartition(".")
    return f"{base}_thumb.jpg"
