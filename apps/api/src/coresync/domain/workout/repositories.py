"""Repository ports for the workout domain.

``user_id`` is a required parameter on every read. There is deliberately no
``get(session_id)`` overload — authorisation is a data-access concern, and an unscoped
fetch is the shape of an IDOR bug (docs/05 §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from coresync.domain.workout.entities import (
    PersonalRecord,
    RecordType,
    Routine,
    SessionExercise,
    SessionSet,
    WorkoutSession,
)


class StaleVersionError(Exception):
    """Optimistic-lock failure on a versioned aggregate.

    Declared with the port rather than with the SQLAlchemy implementation: the
    application layer has to catch it to return a 409, and it must not import
    infrastructure to do so.
    """


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """The history-list projection: enough to render a row, without loading every set."""

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
    status: str
    exercise_count: int
    pr_count: int = 0


@dataclass(frozen=True, slots=True)
class CalendarDay:
    local_date: date
    workout_count: int
    total_volume_kg: Decimal
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class ExerciseHistoryEntry:
    """One exercise's appearance in one session, for the per-exercise history screen."""

    session_id: UUID
    session_name: str
    local_date: date
    sets: list[SessionSet]
    best_set_id: UUID | None
    total_volume_kg: Decimal


class RoutineRepository(Protocol):
    async def get(self, routine_id: UUID, user_id: UUID) -> Routine | None: ...

    async def get_template(self, routine_id: UUID) -> Routine | None:
        """Templates have no owner, so they are the one routine read not scoped to a user."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[Routine]: ...

    async def list_templates(self) -> list[Routine]: ...

    async def add(self, routine: Routine) -> None: ...

    async def update(self, routine: Routine, *, expected_version: int | None = None) -> None:
        """Optimistic locking: a mismatched version means someone else edited first."""
        ...

    async def replace_exercises(self, routine: Routine) -> None: ...

    async def delete(self, routine_id: UUID, user_id: UUID) -> None: ...

    async def touch_last_performed(self, routine_id: UUID, at: datetime) -> None: ...


class WorkoutSessionRepository(Protocol):
    async def get(self, session_id: UUID, user_id: UUID) -> WorkoutSession | None: ...

    async def get_active(self, user_id: UUID) -> WorkoutSession | None: ...

    async def get_by_client_id(
        self, user_id: UUID, client_session_id: UUID
    ) -> WorkoutSession | None:
        """Idempotency for offline creates: the same client id is always the same session."""
        ...

    async def add(self, session: WorkoutSession) -> None: ...

    async def update(self, session: WorkoutSession) -> None: ...

    async def soft_delete(self, session_id: UUID, user_id: UUID) -> None: ...

    async def list_history(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor: tuple[date, UUID] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[SessionSummary]: ...

    async def calendar(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[CalendarDay]: ...

    async def exercise_history(
        self, user_id: UUID, exercise_id: UUID, *, limit: int
    ) -> list[ExerciseHistoryEntry]: ...

    # -------------------------------------------------------- set-level writes
    async def add_exercise_entry(self, entry: SessionExercise) -> None: ...

    async def update_exercise_entry(self, entry: SessionExercise) -> None: ...

    async def remove_exercise_entry(self, session_exercise_id: UUID) -> None: ...

    async def reorder_exercise_entries(self, session: WorkoutSession) -> None: ...

    async def add_set(self, entry: SessionSet) -> None: ...

    async def update_set(self, entry: SessionSet) -> None: ...

    async def delete_set(self, set_id: UUID) -> None: ...

    async def get_set(self, set_id: UUID, user_id: UUID) -> SessionSet | None: ...


class PersonalRecordRepository(Protocol):
    async def current_for_exercises(
        self, user_id: UUID, exercise_ids: list[UUID]
    ) -> dict[tuple[UUID, RecordType], PersonalRecord]: ...

    async def list_current(self, user_id: UUID) -> list[PersonalRecord]: ...

    async def list_for_exercise(self, user_id: UUID, exercise_id: UUID) -> list[PersonalRecord]:
        """Current records plus the progression chain behind them."""
        ...

    async def supersede_and_add(
        self, superseded_ids: list[UUID], records: list[PersonalRecord]
    ) -> None:
        """One call, so the partial unique index on ``is_current`` never sees two winners."""
        ...

    async def delete_for_session(self, session_id: UUID, user_id: UUID) -> None:
        """Undo the records a session created, when that session is discarded or deleted."""
        ...


class ActivitySummaryRepository(Protocol):
    """Incrementally maintained daily aggregates — dashboards never scan raw sets."""

    async def apply_workout(
        self,
        *,
        user_id: UUID,
        local_date: date,
        volume_kg: Decimal,
        set_count: int,
        duration_seconds: int,
        volume_by_muscle_group: dict[str, Decimal],
        pr_count: int,
    ) -> None: ...

    async def revert_workout(
        self,
        *,
        user_id: UUID,
        local_date: date,
        volume_kg: Decimal,
        set_count: int,
        duration_seconds: int,
        pr_count: int,
    ) -> None: ...

    async def range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[CalendarDay]: ...


@dataclass(frozen=True, slots=True)
class ExerciseStatistics:
    exercise_id: UUID
    total_sessions: int
    total_sets: int
    total_volume_kg: Decimal
    best_est_1rm: Decimal | None
    last_performed_on: date | None


class ExerciseStatisticsRepository(Protocol):
    async def apply_session(
        self,
        *,
        user_id: UUID,
        exercise_id: UUID,
        local_date: date,
        set_count: int,
        volume_kg: Decimal,
        best_est_1rm: Decimal | None,
    ) -> None: ...

    async def get_many(
        self, user_id: UUID, exercise_ids: list[UUID]
    ) -> dict[UUID, ExerciseStatistics]: ...


@dataclass(frozen=True, slots=True)
class Streak:
    user_id: UUID
    workout_current: int
    workout_longest: int
    workout_last_date: date | None
    nutrition_current: int = 0
    nutrition_longest: int = 0
    nutrition_last_date: date | None = None


class StreakRepository(Protocol):
    async def get(self, user_id: UUID) -> Streak | None: ...

    async def register_workout(self, user_id: UUID, workout_date: date) -> Streak: ...


class SyncOperationLogRepository(Protocol):
    """Records which client operation ids have been applied.

    This is what makes ``POST /sync`` safe to replay: the phone flushes its whole
    write-ahead log whenever it reconnects, and an operation that already landed must
    report ``duplicate`` rather than apply twice (docs/04 §7).
    """

    async def seen(self, user_id: UUID, op_ids: list[UUID]) -> set[UUID]: ...

    async def record(
        self, user_id: UUID, device_id: UUID | None, op_ids: list[UUID], at: datetime
    ) -> None: ...
