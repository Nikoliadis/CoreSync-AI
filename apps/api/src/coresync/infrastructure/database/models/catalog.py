"""ORM models for the exercise catalog."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from coresync.infrastructure.database.base import Base, SoftDeleteMixin, TimestampMixin


class MuscleGroupModel(TimestampMixin, Base):
    __tablename__ = "muscle_groups"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class MuscleModel(TimestampMixin, Base):
    __tablename__ = "muscles"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    muscle_group_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("muscle_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )

    group: Mapped[MuscleGroupModel] = relationship(lazy="joined")

    __table_args__ = (Index("ix_muscles_group", "muscle_group_id"),)


class EquipmentModel(TimestampMixin, Base):
    __tablename__ = "equipment"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Powers "what can I do at home with only dumbbells?" — a top-5 requested filter.
    is_home_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class ExerciseCategoryModel(TimestampMixin, Base):
    __tablename__ = "exercise_categories"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class ExerciseModel(SoftDeleteMixin, TimestampMixin, Base):
    """Global catalog and user-authored exercises in one table.

    ``owner_user_id IS NULL`` is the global verified catalog. One table means workout
    logging joins one table rather than a UNION, and custom exercises get every catalog
    feature for free (docs/03 §5).
    """

    __tablename__ = "exercises"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("exercise_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    force_type: Mapped[str | None] = mapped_column(String(10))
    mechanic: Mapped[str | None] = mapped_column(String(10))
    difficulty: Mapped[str] = mapped_column(
        String(15), nullable=False, server_default="intermediate"
    )
    logging_type: Mapped[str] = mapped_column(
        String(25), nullable=False, server_default="weight_reps"
    )
    is_unilateral: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    description: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(name,'')), 'A') || "
            "setweight(to_tsvector('simple', coalesce(description,'')), 'C')",
            persisted=True,
        ),
    )

    muscles: Mapped[list[ExerciseMuscleModel]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan", lazy="selectin"
    )
    equipment: Mapped[list[ExerciseEquipmentModel]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan", lazy="selectin"
    )
    media: Mapped[list[ExerciseMediaModel]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ExerciseMediaModel.sort_order",
    )
    instructions: Mapped[list[ExerciseInstructionModel]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ExerciseInstructionModel.step_number",
    )
    category: Mapped[ExerciseCategoryModel] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(
            "force_type IS NULL OR force_type IN ('push','pull','static')", name="force_type_valid"
        ),
        CheckConstraint(
            "mechanic IS NULL OR mechanic IN ('compound','isolation')", name="mechanic_valid"
        ),
        CheckConstraint(
            "difficulty IN ('beginner','intermediate','advanced')", name="difficulty_valid"
        ),
        CheckConstraint(
            "logging_type IN ('weight_reps','bodyweight_reps','weighted_bodyweight',"
            "'time','distance_time','reps_only')",
            name="logging_type_valid",
        ),
        # Only the curated catalog carries the "Verified" badge. A user cannot mint a
        # verified exercise by writing one field, whatever the API layer believes.
        CheckConstraint("owner_user_id IS NULL OR is_verified = false", name="custom_not_verified"),
        Index(
            "uq_exercises_slug_global",
            "slug",
            unique=True,
            postgresql_where=text("owner_user_id IS NULL"),
        ),
        Index(
            "uq_exercises_slug_user",
            "owner_user_id",
            "slug",
            unique=True,
            postgresql_where=text("owner_user_id IS NOT NULL"),
        ),
        Index("ix_exercises_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_exercises_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_exercises_catalog",
            "category_id",
            "difficulty",
            postgresql_where=text("owner_user_id IS NULL AND deleted_at IS NULL"),
        ),
        Index(
            "ix_exercises_owner",
            "owner_user_id",
            postgresql_where=text("owner_user_id IS NOT NULL AND deleted_at IS NULL"),
        ),
    )


class ExerciseMuscleModel(Base):
    """Carries ``role`` and ``contribution_pct``.

    A plain M:N could not express that a bench press is chest-primary with a meaningful
    triceps share — which is exactly what per-muscle volume analytics needs.
    """

    __tablename__ = "exercise_muscles"

    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    muscle_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("muscles.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    contribution_pct: Mapped[int | None] = mapped_column(SmallInteger)

    exercise: Mapped[ExerciseModel] = relationship(back_populates="muscles")
    muscle: Mapped[MuscleModel] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("role IN ('primary','secondary','stabilizer')", name="role_valid"),
        CheckConstraint(
            "contribution_pct IS NULL OR contribution_pct BETWEEN 0 AND 100",
            name="contribution_range",
        ),
        Index("ix_exercise_muscles_muscle", "muscle_id", "role"),
    )


class ExerciseEquipmentModel(Base):
    __tablename__ = "exercise_equipment"

    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("equipment.id", ondelete="RESTRICT"), primary_key=True
    )

    exercise: Mapped[ExerciseModel] = relationship(back_populates="equipment")
    item: Mapped[EquipmentModel] = relationship(lazy="joined")

    __table_args__ = (Index("ix_exercise_equipment_item", "equipment_id"),)


class ExerciseMediaModel(TimestampMixin, Base):
    __tablename__ = "exercise_media"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    media_type: Mapped[str] = mapped_column(String(12), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")

    exercise: Mapped[ExerciseModel] = relationship(back_populates="media")

    __table_args__ = (
        CheckConstraint("media_type IN ('image','video','animation')", name="media_type_valid"),
        Index("ix_exercise_media_exercise", "exercise_id", "sort_order"),
    )


class ExerciseInstructionModel(Base):
    __tablename__ = "exercise_instructions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    exercise: Mapped[ExerciseModel] = relationship(back_populates="instructions")

    __table_args__ = (
        UniqueConstraint("exercise_id", "step_number", name="uq_exercise_instruction_step"),
        CheckConstraint("step_number > 0", name="step_positive"),
    )


class UserFavoriteExerciseModel(Base):
    __tablename__ = "user_favorite_exercises"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (Index("ix_favorite_exercises_user", "user_id", "created_at"),)
