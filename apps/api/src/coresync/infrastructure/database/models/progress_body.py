"""ORM models for body measurements and progress photos.

Kept separate from ``progress.py`` (which holds the Phase 1 weight log) so the two can
be read independently: measurements and photos are Phase 4 additions with very different
access patterns and, for photos, much stricter handling.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from coresync.infrastructure.database.base import Base, SoftDeleteMixin, TimestampMixin

# Every site shares the same column type and plausibility bounds.
_SITE_COLUMNS = (
    "neck_cm",
    "chest_cm",
    "waist_cm",
    "hips_cm",
    "left_arm_cm",
    "right_arm_cm",
    "left_thigh_cm",
    "right_thigh_cm",
    "left_calf_cm",
    "right_calf_cm",
)


def _site_column() -> Mapped[Decimal | None]:
    return mapped_column(Numeric(6, 2))


class BodyMeasurementModel(TimestampMixin, Base):
    """Ten sites on one wide row (docs/03 §8).

    Every site is nullable because people measure what they track, and a row with only a
    waist reading is a legitimate entry rather than a broken one.
    """

    __tablename__ = "body_measurements"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)

    neck_cm: Mapped[Decimal | None] = _site_column()
    chest_cm: Mapped[Decimal | None] = _site_column()
    waist_cm: Mapped[Decimal | None] = _site_column()
    hips_cm: Mapped[Decimal | None] = _site_column()
    left_arm_cm: Mapped[Decimal | None] = _site_column()
    right_arm_cm: Mapped[Decimal | None] = _site_column()
    left_thigh_cm: Mapped[Decimal | None] = _site_column()
    right_thigh_cm: Mapped[Decimal | None] = _site_column()
    left_calf_cm: Mapped[Decimal | None] = _site_column()
    right_calf_cm: Mapped[Decimal | None] = _site_column()

    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # One row per day: re-measuring corrects the entry rather than appending a second,
        # which keeps every per-site series single-valued and the charts unambiguous.
        UniqueConstraint("user_id", "local_date", name="uq_body_measurement_per_day"),
        # A row that records nothing is indistinguishable from a mistake.
        CheckConstraint(
            " OR ".join(f"{column} IS NOT NULL" for column in _SITE_COLUMNS),
            name="at_least_one_site",
        ),
        # Wide bounds: these catch a transposed digit or inches-for-centimetres, not
        # body shapes.
        CheckConstraint(
            " AND ".join(
                f"({column} IS NULL OR ({column} > 0 AND {column} <= 300))"
                for column in _SITE_COLUMNS
            ),
            name="sites_in_range",
        ),
        Index("ix_body_measurements_user_date", "user_id", text("local_date DESC")),
    )


class ProgressPhotoModel(SoftDeleteMixin, TimestampMixin, Base):
    """Metadata only — the bytes live in a private container.

    The strictest table in the schema. ``visibility`` has no public value, and
    ``processing_status`` is a security boundary: a photo that has not been through the
    metadata strip must never have a read URL issued for it (docs/11 §5).
    """

    __tablename__ = "progress_photos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    pose: Mapped[str] = mapped_column(String(10), nullable=False)
    blob_path: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    bytes_size: Mapped[int | None] = mapped_column(Integer)
    weight_at_capture_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    visibility: Mapped[str] = mapped_column(String(12), nullable=False, server_default="private")
    processing_status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="pending"
    )
    exif_stripped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("pose IN ('front','side','back','custom')", name="pose_valid"),
        # Private is the only default, and there is deliberately no 'public' value: a
        # progress photo has no product reason to be world-readable, and offering the
        # value is how it eventually gets set.
        CheckConstraint("visibility IN ('private','shared_link')", name="visibility_valid"),
        CheckConstraint(
            "processing_status IN ('pending','processing','ready','failed')",
            name="processing_status_valid",
        ),
        # A photo cannot be 'ready' without a recorded metadata strip. This is the
        # constraint that makes `is_readable` a guarantee rather than a convention.
        CheckConstraint(
            "processing_status <> 'ready' OR exif_stripped_at IS NOT NULL",
            name="ready_implies_exif_stripped",
        ),
        CheckConstraint(
            "bytes_size IS NULL OR (bytes_size > 0 AND bytes_size <= 15728640)",
            name="bytes_within_upload_limit",
        ),
        Index(
            "ix_progress_photos_user_date",
            "user_id",
            text("local_date DESC"),
            "pose",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Uniqueness on the object key: two rows pointing at one blob would make deletion
        # ambiguous, and a deleted photo whose bytes survive is a privacy incident.
        Index("uq_progress_photos_blob_path", "blob_path", unique=True),
    )
