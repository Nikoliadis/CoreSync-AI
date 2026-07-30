"""ORM models for the workout domain.

The plan (`routines`) and the record of what happened (`workout_sessions`) are separate
table families on purpose. They diverge constantly, and conflating them would lose the
difference — which is the thing a lifter actually wants to see.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from coresync.infrastructure.database.base import Base, SoftDeleteMixin, TimestampMixin


# ---------------------------------------------------------------------- routines
class RoutineModel(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "routines"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    # NULL for curated starter templates, which belong to no one and are copied on adopt.
    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    folder: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    estimated_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    # Optimistic locking: a stale PATCH gets a 409 with current state (docs/04 §5).
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    last_performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exercises: Mapped[list[RoutineExerciseModel]] = relationship(
        back_populates="routine",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RoutineExerciseModel.position",
    )

    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 120", name="name_len"),
        CheckConstraint(
            "estimated_minutes IS NULL OR estimated_minutes BETWEEN 1 AND 600",
            name="estimated_minutes_range",
        ),
        # A template has no owner; an owned routine is not a template.
        CheckConstraint(
            "(is_template AND user_id IS NULL) OR (NOT is_template AND user_id IS NOT NULL)",
            name="template_ownership",
        ),
        Index(
            "ix_routines_user",
            "user_id",
            "position",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_routines_templates",
            "position",
            postgresql_where=text("is_template AND deleted_at IS NULL"),
        ),
    )


class RoutineExerciseModel(TimestampMixin, Base):
    __tablename__ = "routine_exercises"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    routine_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("routines.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # A shared uuid rather than a supersets table: a superset has no attributes of its
    # own, so a junction would add a join to a hot read path for zero information.
    superset_group: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    rest_seconds: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)

    routine: Mapped[RoutineModel] = relationship(back_populates="exercises")
    sets: Mapped[list[RoutineSetModel]] = relationship(
        back_populates="routine_exercise",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RoutineSetModel.set_number",
    )

    __table_args__ = (
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint(
            "rest_seconds IS NULL OR rest_seconds BETWEEN 0 AND 3600", name="rest_range"
        ),
        UniqueConstraint("routine_id", "position", name="uq_routine_exercise_position"),
        Index("ix_routine_exercises_routine", "routine_id", "position"),
        Index("ix_routine_exercises_exercise", "exercise_id"),
    )


class RoutineSetModel(Base):
    __tablename__ = "routine_sets"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    routine_exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("routine_exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    set_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="normal")
    target_reps_min: Mapped[int | None] = mapped_column(SmallInteger)
    target_reps_max: Mapped[int | None] = mapped_column(SmallInteger)
    target_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    target_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    target_distance_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    target_rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))

    routine_exercise: Mapped[RoutineExerciseModel] = relationship(back_populates="sets")

    __table_args__ = (
        CheckConstraint("set_number > 0", name="set_number_positive"),
        CheckConstraint(
            "set_type IN ('normal','warmup','drop','failure','amrap')", name="set_type_valid"
        ),
        CheckConstraint(
            "target_reps_min IS NULL OR target_reps_max IS NULL "
            "OR target_reps_min <= target_reps_max",
            name="rep_range_ordered",
        ),
        CheckConstraint(
            "target_rpe IS NULL OR target_rpe BETWEEN 1 AND 10", name="target_rpe_range"
        ),
        UniqueConstraint("routine_exercise_id", "set_number", name="uq_routine_set_number"),
    )


# ---------------------------------------------------------------------- sessions
class WorkoutSessionModel(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "workout_sessions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL, not CASCADE: deleting a routine must never delete workout history. This
    # is the single most important ON DELETE choice in the schema (docs/03 §6).
    routine_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("routines.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The user's calendar day, computed at write time. Deriving it at query time would
    # make every streak and calendar predicate non-sargable (docs/03 §6).
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    total_volume_kg: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    total_sets: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    total_reps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    perceived_effort: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="in_progress")
    visibility: Mapped[str] = mapped_column(String(10), nullable=False, server_default="private")
    client_session_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    exercises: Mapped[list[SessionExerciseModel]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SessionExerciseModel.position",
    )

    __table_args__ = (
        CheckConstraint("status IN ('in_progress','completed','discarded')", name="status_valid"),
        CheckConstraint("visibility IN ('private','followers','public')", name="visibility_valid"),
        CheckConstraint("completed_at IS NULL OR completed_at >= started_at", name="session_times"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="duration_positive"
        ),
        CheckConstraint(
            "perceived_effort IS NULL OR perceived_effort BETWEEN 1 AND 10", name="effort_range"
        ),
        Index(
            "ix_workout_sessions_user_date",
            "user_id",
            text("local_date DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Offline sync deduplication: the same client-named session is one row forever.
        Index(
            "uq_workout_sessions_client_id",
            "user_id",
            "client_session_id",
            unique=True,
            postgresql_where=text("client_session_id IS NOT NULL"),
        ),
        # At most one workout in progress per user. Stops a double-tapped "Start workout"
        # on a laggy connection from creating two sessions.
        Index(
            "uq_workout_sessions_one_in_progress",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'in_progress' AND deleted_at IS NULL"),
        ),
        Index("ix_workout_sessions_routine", "routine_id"),
    )


class SessionExerciseModel(TimestampMixin, Base):
    __tablename__ = "session_exercises"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    superset_group: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    rest_seconds: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)

    session: Mapped[WorkoutSessionModel] = relationship(back_populates="exercises")
    sets: Mapped[list[SessionSetModel]] = relationship(
        back_populates="session_exercise",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SessionSetModel.set_number",
    )

    __table_args__ = (
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint(
            "rest_seconds IS NULL OR rest_seconds BETWEEN 0 AND 3600", name="rest_range"
        ),
        Index("ix_session_exercises_session", "session_id", "position"),
        Index("ix_session_exercises_exercise", "exercise_id"),
    )


class SessionSetModel(TimestampMixin, Base):
    """One logged set — the hottest write in the product."""

    __tablename__ = "session_sets"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    session_exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("session_exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    set_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="normal")
    reps: Mapped[int | None] = mapped_column(SmallInteger)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Epley, stored so PR queries and charts never recompute it. Mirrors
    # ``domain.workout.entities.estimated_one_rep_max`` — the two cannot drift because
    # the database owns this value.
    estimated_1rm: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 2),
        Computed(
            "CASE WHEN weight_kg IS NOT NULL AND reps IS NOT NULL "
            "AND reps > 0 AND reps <= 15 AND weight_kg > 0 "
            "THEN round(weight_kg * (1 + reps::numeric / 30), 2) END",
            persisted=True,
        ),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session_exercise: Mapped[SessionExerciseModel] = relationship(back_populates="sets")

    __table_args__ = (
        CheckConstraint("set_number > 0", name="set_number_positive"),
        CheckConstraint(
            "set_type IN ('normal','warmup','drop','failure','amrap')", name="set_type_valid"
        ),
        CheckConstraint("reps IS NULL OR reps BETWEEN 0 AND 1000", name="reps_range"),
        CheckConstraint(
            "weight_kg IS NULL OR (weight_kg >= 0 AND weight_kg <= 1000)", name="weight_range"
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="duration_positive"
        ),
        CheckConstraint("distance_m IS NULL OR distance_m >= 0", name="distance_positive"),
        CheckConstraint("rpe IS NULL OR rpe BETWEEN 1 AND 10", name="rpe_range"),
        # A set must record something. Without this, an empty row is indistinguishable
        # from a real one and silently drags every average down.
        CheckConstraint(
            "reps IS NOT NULL OR duration_seconds IS NOT NULL OR distance_m IS NOT NULL",
            name="set_has_payload",
        ),
        UniqueConstraint("session_exercise_id", "set_number", name="uq_session_set_number"),
        Index("ix_session_sets_exercise", "session_exercise_id", "set_number"),
    )


# --------------------------------------------------------------- personal records
class PersonalRecordModel(Base):
    __tablename__ = "personal_records"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    record_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reps_at_value: Mapped[int | None] = mapped_column(SmallInteger)
    # SET NULL so a corrected or deleted set does not erase the achievement.
    session_set_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("session_sets.id", ondelete="SET NULL")
    )
    achieved_on: Mapped[date] = mapped_column(Date, nullable=False)
    previous_record_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("personal_records.id", ondelete="SET NULL")
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "record_type IN ('max_weight','max_reps','max_volume_set','est_1rm',"
            "'max_duration','max_distance')",
            name="record_type_valid",
        ),
        CheckConstraint("value > 0", name="value_positive"),
        # Exactly one current record per (user, exercise, type). History survives via the
        # previous_record_id chain, so "current PRs" stays an index-only lookup.
        Index(
            "uq_personal_records_current",
            "user_id",
            "exercise_id",
            "record_type",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_personal_records_user_recent", "user_id", text("achieved_on DESC")),
        Index("ix_personal_records_set", "session_set_id"),
        Index("ix_personal_records_previous", "previous_record_id"),
    )


# ------------------------------------------------------------------ offline sync
class SyncOperationModel(Base):
    """Applied client operation ids.

    The phone flushes its whole write-ahead log on reconnect, so the same operation
    arrives repeatedly. This table is what makes replaying a batch a no-op rather than a
    duplicated workout (docs/04 §7).
    """

    __tablename__ = "sync_operations"

    op_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (Index("ix_sync_operations_user", "user_id", "applied_at"),)
