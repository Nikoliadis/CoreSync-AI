"""HTTP schemas for routines, sessions and offline sync."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field

from coresync.presentation.schemas.common import ApiModel
from coresync.presentation.schemas.exercises import PersonalRecordResponse

SET_TYPES = ("normal", "warmup", "drop", "failure", "amrap")
SET_TYPE_PATTERN = "|".join(SET_TYPES)

# Bounds mirror the CHECK constraints on the tables. Rejecting here produces a helpful
# field-level message; the constraint is what makes the guarantee real.
WEIGHT = Field(default=None, ge=0, le=1000, decimal_places=2)
REPS = Field(default=None, ge=0, le=1000)
RPE = Field(default=None, ge=1, le=10, decimal_places=1)


# ---------------------------------------------------------------------- routines
class RoutineSetRequest(ApiModel):
    set_type: str = Field(default="normal", pattern=SET_TYPE_PATTERN)
    target_reps_min: int | None = REPS
    target_reps_max: int | None = REPS
    target_weight_kg: Decimal | None = WEIGHT
    target_duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    target_distance_m: Decimal | None = Field(default=None, ge=0)
    target_rpe: Decimal | None = RPE


class RoutineExerciseRequest(ApiModel):
    exercise_id: UUID
    superset_group: UUID | None = None
    rest_seconds: int | None = Field(default=None, ge=0, le=3600)
    notes: str | None = Field(default=None, max_length=1000)
    sets: list[RoutineSetRequest] = Field(default_factory=list, max_length=30)


class CreateRoutineRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    folder: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    estimated_minutes: int | None = Field(default=None, ge=1, le=600)
    exercises: list[RoutineExerciseRequest] = Field(default_factory=list, max_length=50)


class UpdateRoutineRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    folder: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    estimated_minutes: int | None = Field(default=None, ge=1, le=600)
    # Optimistic locking. Omit to force the write; send the version you read to be told
    # about a conflicting edit instead of silently overwriting it.
    version: int | None = None


class ReplaceRoutineExercisesRequest(ApiModel):
    exercises: list[RoutineExerciseRequest] = Field(max_length=50)


class DuplicateRoutineRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class RoutineSetResponse(ApiModel):
    id: UUID
    set_number: int
    set_type: str
    target_reps_min: int | None
    target_reps_max: int | None
    target_weight_kg: Decimal | None
    target_duration_seconds: int | None
    target_distance_m: Decimal | None
    target_rpe: Decimal | None


class RoutineExerciseResponse(ApiModel):
    id: UUID
    exercise_id: UUID
    exercise_name: str | None
    position: int
    superset_group: UUID | None
    rest_seconds: int | None
    notes: str | None
    sets: list[RoutineSetResponse] = Field(default_factory=list)


class RoutineResponse(ApiModel):
    id: UUID
    name: str
    folder: str | None
    notes: str | None
    is_template: bool
    estimated_minutes: int | None
    version: int
    last_performed_at: datetime | None
    total_sets: int
    exercises: list[RoutineExerciseResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------- sessions
class StartSessionRequest(ApiModel):
    routine_id: UUID | None = None
    name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    # Supplied by the client so a retried "Start workout" resolves to one session.
    client_session_id: UUID | None = None
    started_at: datetime | None = None


class UpdateSessionRequest(ApiModel):
    name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    perceived_effort: int | None = Field(default=None, ge=1, le=10)


class AddSessionExerciseRequest(ApiModel):
    exercise_id: UUID
    superset_group: UUID | None = None
    rest_seconds: int | None = Field(default=None, ge=0, le=3600)
    notes: str | None = Field(default=None, max_length=1000)


class UpdateSessionExerciseRequest(ApiModel):
    superset_group: UUID | None = None
    rest_seconds: int | None = Field(default=None, ge=0, le=3600)
    notes: str | None = Field(default=None, max_length=1000)


class ReorderExercisesRequest(ApiModel):
    exercise_ids: list[UUID] = Field(min_length=1, max_length=60)


class LogSetRequest(ApiModel):
    set_type: str = Field(default="normal", pattern=SET_TYPE_PATTERN)
    reps: int | None = REPS
    weight_kg: Decimal | None = WEIGHT
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    distance_m: Decimal | None = Field(default=None, ge=0)
    rpe: Decimal | None = RPE
    is_completed: bool = True
    # Client-generated so an offline set flushed twice is one row.
    id: UUID | None = None
    completed_at: datetime | None = None


class UpdateSetRequest(ApiModel):
    set_type: str | None = Field(default=None, pattern=SET_TYPE_PATTERN)
    reps: int | None = REPS
    weight_kg: Decimal | None = WEIGHT
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    distance_m: Decimal | None = Field(default=None, ge=0)
    rpe: Decimal | None = RPE
    is_completed: bool | None = None


class CompleteSessionRequest(ApiModel):
    perceived_effort: int | None = Field(default=None, ge=1, le=10)
    completed_at: datetime | None = None


class SessionSetResponse(ApiModel):
    id: UUID
    session_exercise_id: UUID
    set_number: int
    set_type: str
    reps: int | None
    weight_kg: Decimal | None
    duration_seconds: int | None
    distance_m: Decimal | None
    rpe: Decimal | None
    is_completed: bool
    estimated_one_rep_max: Decimal | None
    completed_at: datetime | None


class SessionExerciseResponse(ApiModel):
    id: UUID
    exercise_id: UUID
    exercise_name: str | None
    logging_type: str | None
    position: int
    superset_group: UUID | None
    rest_seconds: int | None
    notes: str | None
    sets: list[SessionSetResponse] = Field(default_factory=list)


class WorkoutSessionResponse(ApiModel):
    id: UUID
    name: str
    routine_id: UUID | None
    notes: str | None
    started_at: datetime
    completed_at: datetime | None
    local_date: date
    duration_seconds: int | None
    total_volume_kg: Decimal
    total_sets: int
    total_reps: int
    perceived_effort: int | None
    status: str
    visibility: str
    client_session_id: UUID | None
    exercises: list[SessionExerciseResponse] = Field(default_factory=list)


class SessionSummaryResponse(ApiModel):
    id: UUID
    name: str
    routine_id: UUID | None
    started_at: datetime
    completed_at: datetime | None
    local_date: date
    duration_seconds: int | None
    total_volume_kg: Decimal
    total_sets: int
    total_reps: int
    exercise_count: int
    pr_count: int


class SessionHistoryResponse(ApiModel):
    items: list[SessionSummaryResponse]
    next_cursor: str | None
    has_more: bool


class CalendarDayResponse(ApiModel):
    local_date: date
    workout_count: int
    total_volume_kg: Decimal
    duration_seconds: int


class StreakResponse(ApiModel):
    current: int
    longest: int
    last_workout_date: date | None


class CompletedSessionResponse(ApiModel):
    """The finish screen. Records travel with the session so the PR celebration is
    immediate rather than a second round-trip."""

    session: WorkoutSessionResponse
    new_records: list[PersonalRecordResponse]
    streak: StreakResponse | None = None


# ------------------------------------------------------------------ offline sync
class SyncOperationRequest(ApiModel):
    op_id: UUID = Field(description="Idempotency unit. Replaying a batch is always safe.")
    type: str = Field(
        max_length=40,
        description=(
            "session.create | session.update | session.complete | session.discard | "
            "exercise.add | set.log | set.update | set.delete"
        ),
    )
    at: datetime = Field(description="When the user performed it. Bounded by server time.")
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncRequest(ApiModel):
    device_id: UUID | None = None
    operations: list[SyncOperationRequest] = Field(max_length=500)


class SyncOperationResultResponse(ApiModel):
    op_id: UUID
    status: str = Field(description="applied | duplicate | rejected")
    reason: str | None = None
    result: dict[str, Any] | None = None


class SyncResponse(ApiModel):
    results: list[SyncOperationResultResponse]
    server_time: datetime
