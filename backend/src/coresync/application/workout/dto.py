"""Workout DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from coresync.application.catalog.dto import PersonalRecordDTO


@dataclass(frozen=True, slots=True)
class RoutineSetDTO:
    id: UUID
    set_number: int
    set_type: str
    target_reps_min: int | None
    target_reps_max: int | None
    target_weight_kg: Decimal | None
    target_duration_seconds: int | None
    target_distance_m: Decimal | None
    target_rpe: Decimal | None


@dataclass(frozen=True, slots=True)
class RoutineExerciseDTO:
    id: UUID
    exercise_id: UUID
    exercise_name: str | None
    position: int
    superset_group: UUID | None
    rest_seconds: int | None
    notes: str | None
    sets: list[RoutineSetDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RoutineDTO:
    id: UUID
    name: str
    folder: str | None
    notes: str | None
    is_template: bool
    estimated_minutes: int | None
    version: int
    last_performed_at: datetime | None
    total_sets: int
    exercises: list[RoutineExerciseDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SessionSetDTO:
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


@dataclass(frozen=True, slots=True)
class SessionExerciseDTO:
    id: UUID
    exercise_id: UUID
    exercise_name: str | None
    logging_type: str | None
    position: int
    superset_group: UUID | None
    rest_seconds: int | None
    notes: str | None
    sets: list[SessionSetDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WorkoutSessionDTO:
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
    exercises: list[SessionExerciseDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SessionSummaryDTO:
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


@dataclass(frozen=True, slots=True)
class SessionHistoryPageDTO:
    items: list[SessionSummaryDTO]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class CalendarDayDTO:
    local_date: date
    workout_count: int
    total_volume_kg: Decimal
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class StreakDTO:
    current: int
    longest: int
    last_workout_date: date | None


@dataclass(frozen=True, slots=True)
class CompletedSessionDTO:
    """What the "finish workout" screen renders.

    The records come back with the session because the PR celebration has to fire
    immediately — a second round-trip to find out whether anything was beaten would
    show the summary first and the confetti after, which reads as a bug.
    """

    session: WorkoutSessionDTO
    new_records: list[PersonalRecordDTO]
    streak: StreakDTO | None = None


# ------------------------------------------------------------------ offline sync
@dataclass(frozen=True, slots=True)
class SyncOperationResultDTO:
    op_id: UUID
    status: str  # applied | duplicate | rejected
    reason: str | None = None
    result: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SyncResultDTO:
    results: list[SyncOperationResultDTO]
    server_time: datetime
