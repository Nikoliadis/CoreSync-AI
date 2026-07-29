"""Incrementally maintained aggregates.

Tables, not materialised views. A materialised view refreshes wholesale — at a million
users that is minutes of work to serve one user's dashboard. These rows are updated in
the same transaction as the write that changes them, so a dashboard read is a
primary-key lookup. The nightly reconciliation job exists to repair drift, not to build
the data (docs/03 §9).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from coresync.infrastructure.database.base import Base


class DailyActivitySummaryModel(Base):
    __tablename__ = "daily_activity_summaries"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    workout_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    total_volume_kg: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    total_sets: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Per-group tonnage as jsonb rather than a child table: it is written whole, read
    # whole, and the key set changes as the catalog grows.
    volume_by_muscle_group: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    pr_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("workout_count >= 0", name="workout_count_positive"),
        CheckConstraint("total_volume_kg >= 0", name="volume_positive"),
        CheckConstraint("total_sets >= 0", name="sets_positive"),
        Index("ix_daily_activity_user_date", "user_id", text("local_date DESC")),
    )


class ExerciseStatisticsModel(Base):
    """Per-user, per-exercise rollup.

    ``trend_slope`` is an 8-week rolling gradient, so plateau detection in Phase 5 does
    not have to re-scan a lifter's entire set history on every check.
    """

    __tablename__ = "exercise_statistics"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    total_sessions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_sets: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_volume_kg: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    best_est_1rm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    last_performed_on: Mapped[date | None] = mapped_column(Date)
    trend_slope: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("total_sessions >= 0 AND total_sets >= 0", name="counts_positive"),
        Index("ix_exercise_statistics_user_recent", "user_id", text("last_performed_on DESC")),
    )


class UserStreakModel(Base):
    __tablename__ = "user_streaks"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workout_current: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    workout_longest: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    workout_last_date: Mapped[date | None] = mapped_column(Date)
    nutrition_current: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    nutrition_longest: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    nutrition_last_date: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "workout_current >= 0 AND workout_longest >= workout_current",
            name="workout_streak_sane",
        ),
        CheckConstraint(
            "nutrition_current >= 0 AND nutrition_longest >= nutrition_current",
            name="nutrition_streak_sane",
        ),
    )
