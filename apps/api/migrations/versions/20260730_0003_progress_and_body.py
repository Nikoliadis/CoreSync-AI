"""Body measurements and progress photos (Phase 4).

Weight logs already exist from 0001, so this migration adds the two tables Phase 4
needs. Hand-written, like the others: the constraints below are the point of the
migration, and autogenerate emits none of them.

Revision ID: 0003_progress_body
Revises: 0002_catalog_workouts
Created: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_progress_body"
down_revision: str | None = "0002_catalog_workouts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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

_TIMESTAMPED = ("body_measurements", "progress_photos")


def upgrade() -> None:
    op.create_table(
        "body_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        *[sa.Column(column, sa.Numeric(6, 2), nullable=True) for column in _SITE_COLUMNS],
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_body_measurements"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_body_measurements_user_id_users", ondelete="CASCADE"
        ),
        # One row per day. Re-measuring corrects the entry rather than appending a second,
        # which keeps every per-site series single-valued.
        sa.UniqueConstraint("user_id", "local_date", name="uq_body_measurement_per_day"),
        sa.CheckConstraint(
            " OR ".join(f"{column} IS NOT NULL" for column in _SITE_COLUMNS),
            name="at_least_one_site",
        ),
        sa.CheckConstraint(
            " AND ".join(
                f"({column} IS NULL OR ({column} > 0 AND {column} <= 300))"
                for column in _SITE_COLUMNS
            ),
            name="sites_in_range",
        ),
    )
    op.create_index(
        "ix_body_measurements_user_date",
        "body_measurements",
        ["user_id", sa.text("local_date DESC")],
    )

    op.create_table(
        "progress_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("pose", sa.String(10), nullable=False),
        sa.Column("blob_path", sa.Text(), nullable=False),
        sa.Column("thumbnail_path", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("bytes_size", sa.Integer(), nullable=True),
        sa.Column("weight_at_capture_kg", sa.Numeric(6, 2), nullable=True),
        sa.Column("visibility", sa.String(12), server_default="private", nullable=False),
        sa.Column("processing_status", sa.String(12), server_default="pending", nullable=False),
        sa.Column("exif_stripped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_progress_photos"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_progress_photos_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint("pose IN ('front','side','back','custom')", name="pose_valid"),
        # No 'public' value exists. A progress photo has no product reason to be
        # world-readable, and offering the value is how it eventually gets set.
        sa.CheckConstraint("visibility IN ('private','shared_link')", name="visibility_valid"),
        sa.CheckConstraint(
            "processing_status IN ('pending','processing','ready','failed')",
            name="processing_status_valid",
        ),
        # A photo cannot be 'ready' without a recorded metadata strip. This is what makes
        # "no read URL before EXIF removal" a guarantee rather than a convention: photos
        # routinely carry the GPS coordinates of the user's home.
        sa.CheckConstraint(
            "processing_status <> 'ready' OR exif_stripped_at IS NOT NULL",
            name="ready_implies_exif_stripped",
        ),
        sa.CheckConstraint(
            "bytes_size IS NULL OR (bytes_size > 0 AND bytes_size <= 15728640)",
            name="bytes_within_upload_limit",
        ),
    )
    op.create_index(
        "ix_progress_photos_user_date",
        "progress_photos",
        ["user_id", sa.text("local_date DESC"), "pose"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Two rows pointing at one blob would make deletion ambiguous, and a deleted photo
    # whose bytes survive is a privacy incident.
    op.create_index("uq_progress_photos_blob_path", "progress_photos", ["blob_path"], unique=True)

    for table in _TIMESTAMPED:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in _TIMESTAMPED:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.drop_table("progress_photos")
    op.drop_table("body_measurements")
