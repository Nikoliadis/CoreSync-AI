"""ORM models for the profile domain."""

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
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from coresync.infrastructure.database.base import Base, TimestampMixin


class ProfileModel(TimestampMixin, Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(20))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    activity_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="moderate"
    )
    experience_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="beginner"
    )
    avatar_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # 13 is the registration floor (COPPA / GDPR Article 8 territory). Enforced in
        # the schema so no code path can create a younger account.
        CheckConstraint(
            "date_of_birth IS NULL OR "
            "(date_of_birth > DATE '1900-01-01' "
            " AND date_of_birth < (CURRENT_DATE - INTERVAL '13 years'))",
            name="dob_valid",
        ),
        CheckConstraint(
            "gender IS NULL OR gender IN ('male','female','other','prefer_not_to_say')",
            name="gender_valid",
        ),
        CheckConstraint(
            "activity_level IN ('sedentary','light','moderate','active','very_active')",
            name="activity_level_valid",
        ),
        CheckConstraint(
            "experience_level IN ('beginner','intermediate','advanced')",
            name="experience_level_valid",
        ),
        CheckConstraint(
            "height_cm IS NULL OR (height_cm > 0 AND height_cm <= 300)", name="height_range"
        ),
        CheckConstraint("bio IS NULL OR length(bio) <= 500", name="bio_len"),
    )


class GoalModel(TimestampMixin, Base):
    __tablename__ = "user_goals"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    goal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    weekly_rate_kg: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    target_date: Mapped[date | None] = mapped_column(Date)
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint(
            "goal_type IN ('lose_fat','maintain','gain_muscle','recomp','performance')",
            name="goal_type_valid",
        ),
        CheckConstraint("ended_on IS NULL OR ended_on >= started_on", name="goal_range"),
        CheckConstraint(
            "target_weight_kg IS NULL OR (target_weight_kg > 20 AND target_weight_kg <= 500)",
            name="target_weight_range",
        ),
        # Exactly one open goal per user.
        Index(
            "uq_user_goals_current",
            "user_id",
            unique=True,
            postgresql_where=text("ended_on IS NULL"),
        ),
        Index("ix_user_goals_user", "user_id", "started_on"),
    )


class NutritionTargetModel(TimestampMixin, Base):
    """Temporally versioned targets — see docs/03 §4."""

    __tablename__ = "nutrition_targets"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)  # NULL = currently active
    calories: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    protein_g: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False)
    carbs_g: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False)
    fat_g: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(9, 3))
    water_ml: Mapped[Decimal] = mapped_column(Numeric(9, 2), nullable=False, server_default="2500")
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="auto")
    rationale: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("source IN ('auto','manual','ai')", name="source_valid"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="targets_range"
        ),
        # The safety floor. This is the ring that cannot be argued with: prompt
        # instructions and service validation can both be bypassed by a bug, a CHECK
        # constraint cannot. See docs/10 §7.1.
        CheckConstraint("calories >= 1000", name="calorie_floor"),
        CheckConstraint("calories <= 10000", name="calorie_ceiling"),
        CheckConstraint("protein_g >= 0 AND carbs_g >= 0 AND fat_g >= 0", name="macros_positive"),
        CheckConstraint("water_ml >= 0 AND water_ml <= 10000", name="water_range"),
        Index(
            "uq_nutrition_targets_current",
            "user_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        Index("ix_nutrition_targets_user_from", "user_id", "effective_from"),
    )
