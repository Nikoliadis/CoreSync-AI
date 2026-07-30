"""ORM models for the progress domain (Phase 1 subset: weight logs)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from coresync.infrastructure.database.base import Base, TimestampMixin


class WeightLogModel(TimestampMixin, Base):
    __tablename__ = "weight_logs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    body_fat_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    measurement_context: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="unspecified"
    )
    trend_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # One weigh-in per day. Multiple daily weights are noise, and they corrupt the
        # EWMA trend that everything downstream reasons about.
        UniqueConstraint("user_id", "local_date", name="uq_weight_per_day"),
        CheckConstraint("weight_kg > 0 AND weight_kg <= 1000", name="weight_range"),
        CheckConstraint(
            "body_fat_pct IS NULL OR (body_fat_pct >= 0 AND body_fat_pct <= 100)",
            name="body_fat_range",
        ),
        CheckConstraint(
            "measurement_context IN "
            "('morning_fasted','morning','evening','post_workout','unspecified')",
            name="context_valid",
        ),
        CheckConstraint(
            "source IN ('manual','healthkit','google_fit','smart_scale','onboarding')",
            name="source_valid",
        ),
        Index("ix_weight_logs_user_date", "user_id", "local_date"),
    )
