"""Workout entities: routines (the plan) and sessions (what actually happened).

These are deliberately *not* the same objects. A routine prescribes exercises and target
sets; a session records what was performed. They diverge constantly — you planned 5x5
and did 5,5,5,4,3 — and conflating them loses exactly the difference the user cares
about (docs/03 §6).

An exercise is referenced by id only. The workout domain never imports the catalog: a
set knows the numbers it recorded, and that is enough to decide what it beat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

from coresync.core.ids import uuid7

_ZERO = Decimal("0")


class SetType(StrEnum):
    NORMAL = "normal"
    WARMUP = "warmup"
    DROP = "drop"
    FAILURE = "failure"
    AMRAP = "amrap"


class SessionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DISCARDED = "discarded"


class Visibility(StrEnum):
    PRIVATE = "private"
    FOLLOWERS = "followers"
    PUBLIC = "public"


class RecordType(StrEnum):
    MAX_WEIGHT = "max_weight"
    MAX_REPS = "max_reps"
    MAX_VOLUME_SET = "max_volume_set"
    EST_1RM = "est_1rm"
    MAX_DURATION = "max_duration"
    MAX_DISTANCE = "max_distance"


# --------------------------------------------------------------------- routines
@dataclass(slots=True)
class RoutineSet:
    """A prescribed set. Targets are ranges because "8-12 reps" is how lifters think."""

    id: UUID
    set_number: int
    set_type: SetType = SetType.NORMAL
    target_reps_min: int | None = None
    target_reps_max: int | None = None
    target_weight_kg: Decimal | None = None
    target_duration_seconds: int | None = None
    target_distance_m: Decimal | None = None
    target_rpe: Decimal | None = None

    @classmethod
    def create(
        cls,
        *,
        set_number: int,
        set_type: SetType = SetType.NORMAL,
        target_reps_min: int | None = None,
        target_reps_max: int | None = None,
        target_weight_kg: Decimal | None = None,
        target_duration_seconds: int | None = None,
        target_distance_m: Decimal | None = None,
        target_rpe: Decimal | None = None,
    ) -> RoutineSet:
        if target_reps_min is not None and target_reps_max is not None:
            if target_reps_min > target_reps_max:
                raise ValueError("target_reps_min cannot exceed target_reps_max")
        return cls(
            id=uuid7(),
            set_number=set_number,
            set_type=set_type,
            target_reps_min=target_reps_min,
            target_reps_max=target_reps_max,
            target_weight_kg=target_weight_kg,
            target_duration_seconds=target_duration_seconds,
            target_distance_m=target_distance_m,
            target_rpe=target_rpe,
        )


@dataclass(slots=True)
class RoutineExercise:
    id: UUID
    exercise_id: UUID
    position: int
    superset_group: UUID | None = None
    rest_seconds: int | None = None
    notes: str | None = None
    sets: list[RoutineSet] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        exercise_id: UUID,
        position: int,
        superset_group: UUID | None = None,
        rest_seconds: int | None = None,
        notes: str | None = None,
        sets: list[RoutineSet] | None = None,
    ) -> RoutineExercise:
        return cls(
            id=uuid7(),
            exercise_id=exercise_id,
            position=position,
            superset_group=superset_group,
            rest_seconds=rest_seconds,
            notes=notes,
            sets=sets or [],
        )


@dataclass(slots=True)
class Routine:
    """A user's training plan.

    Templates are the same entity with ``is_template`` and no owner. Adoption *copies*
    rather than references, so the author editing their template never mutates someone
    else's plan (docs/03 §6).
    """

    id: UUID
    user_id: UUID | None
    name: str
    folder: str | None = None
    notes: str | None = None
    is_template: bool = False
    estimated_minutes: int | None = None
    position: int = 0
    # Optimistic locking. A stale PATCH gets a 409 with the current state so the client
    # can merge rather than silently clobber (docs/04 §5).
    version: int = 1
    last_performed_at: datetime | None = None
    exercises: list[RoutineExercise] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        name: str,
        folder: str | None = None,
        notes: str | None = None,
        estimated_minutes: int | None = None,
        exercises: list[RoutineExercise] | None = None,
    ) -> Routine:
        if not name.strip():
            raise ValueError("a routine needs a name")
        return cls(
            id=uuid7(),
            user_id=user_id,
            name=name.strip(),
            folder=folder.strip() if folder else None,
            notes=notes,
            estimated_minutes=estimated_minutes,
            exercises=exercises or [],
        )

    def replace_exercises(self, exercises: list[RoutineExercise]) -> None:
        """Reordering and editing as one atomic write.

        N separate PATCHes would leave the routine briefly inconsistent — two exercises
        at position 3 — and a dropped request would strand it there.
        """
        for index, exercise in enumerate(exercises, start=1):
            exercise.position = index
        self.exercises = exercises
        self.version += 1

    def duplicate(self, *, user_id: UUID, name: str | None = None) -> Routine:
        copy = Routine.create(
            user_id=user_id,
            name=name or f"{self.name} (copy)",
            folder=self.folder,
            notes=self.notes,
            estimated_minutes=self.estimated_minutes,
        )
        # Superset groups are ids shared between exercises; remap them so the copy's
        # groupings stay internally consistent instead of pointing at the original's.
        group_map: dict[UUID, UUID] = {}
        for source in self.exercises:
            group = None
            if source.superset_group is not None:
                group = group_map.setdefault(source.superset_group, uuid7())
            copy.exercises.append(
                RoutineExercise.create(
                    exercise_id=source.exercise_id,
                    position=source.position,
                    superset_group=group,
                    rest_seconds=source.rest_seconds,
                    notes=source.notes,
                    sets=[
                        RoutineSet.create(
                            set_number=s.set_number,
                            set_type=s.set_type,
                            target_reps_min=s.target_reps_min,
                            target_reps_max=s.target_reps_max,
                            target_weight_kg=s.target_weight_kg,
                            target_duration_seconds=s.target_duration_seconds,
                            target_distance_m=s.target_distance_m,
                            target_rpe=s.target_rpe,
                        )
                        for s in source.sets
                    ],
                )
            )
        return copy

    @property
    def total_sets(self) -> int:
        return sum(len(e.sets) for e in self.exercises)


# --------------------------------------------------------------------- sessions
@dataclass(slots=True)
class SessionSet:
    """One recorded set. The hottest write in the product.

    Which fields are populated depends on the exercise's logging type. Warm-ups and
    incomplete sets are ordinary rows carrying a flag rather than separate tables —
    they are simply excluded from volume and records.
    """

    id: UUID
    session_exercise_id: UUID
    set_number: int
    set_type: SetType = SetType.NORMAL
    reps: int | None = None
    weight_kg: Decimal | None = None
    duration_seconds: int | None = None
    distance_m: Decimal | None = None
    rpe: Decimal | None = None
    is_completed: bool = True
    completed_at: datetime | None = None
    # Denormalised from the exercise so records can be attributed without a join.
    exercise_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        session_exercise_id: UUID,
        set_number: int,
        set_type: SetType = SetType.NORMAL,
        reps: int | None = None,
        weight_kg: Decimal | None = None,
        duration_seconds: int | None = None,
        distance_m: Decimal | None = None,
        rpe: Decimal | None = None,
        is_completed: bool = True,
        completed_at: datetime | None = None,
        set_id: UUID | None = None,
        exercise_id: UUID | None = None,
    ) -> SessionSet:
        if reps is None and duration_seconds is None and distance_m is None:
            raise ValueError("a set must record reps, duration or distance")
        return cls(
            # The client may name the set: offline logging generates the id locally so the
            # same set flushed twice is one row, not two (docs/04 §7).
            id=set_id or uuid7(),
            session_exercise_id=session_exercise_id,
            set_number=set_number,
            set_type=set_type,
            reps=reps,
            weight_kg=weight_kg,
            duration_seconds=duration_seconds,
            distance_m=distance_m,
            rpe=rpe,
            is_completed=is_completed,
            completed_at=completed_at,
            exercise_id=exercise_id,
        )

    @property
    def counts_toward_records(self) -> bool:
        """Warm-ups are practice, not performance.

        Counting them would inflate every record and make the PR celebration meaningless.
        """
        return self.is_completed and self.set_type is not SetType.WARMUP

    @property
    def volume_kg(self) -> Decimal:
        if self.weight_kg is None or self.reps is None:
            return _ZERO
        return self.weight_kg * self.reps

    @property
    def estimated_one_rep_max(self) -> Decimal | None:
        return estimated_one_rep_max(self.weight_kg, self.reps)


@dataclass(slots=True)
class SessionExercise:
    id: UUID
    session_id: UUID
    exercise_id: UUID
    position: int
    superset_group: UUID | None = None
    rest_seconds: int | None = None
    notes: str | None = None
    sets: list[SessionSet] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        session_id: UUID,
        exercise_id: UUID,
        position: int,
        superset_group: UUID | None = None,
        rest_seconds: int | None = None,
        notes: str | None = None,
        session_exercise_id: UUID | None = None,
    ) -> SessionExercise:
        return cls(
            id=session_exercise_id or uuid7(),
            session_id=session_id,
            exercise_id=exercise_id,
            position=position,
            superset_group=superset_group,
            rest_seconds=rest_seconds,
            notes=notes,
        )

    def next_set_number(self) -> int:
        return max((s.set_number for s in self.sets), default=0) + 1


@dataclass(slots=True)
class WorkoutSession:
    """A training session — the irreplaceable asset in this product.

    ``local_date`` is the user's calendar day at the moment they trained, computed once
    at write time. A workout finished at 23:30 in Athens belongs to that day, not to the
    UTC next one, and every streak, calendar and daily join keys on it.
    """

    id: UUID
    user_id: UUID
    name: str
    started_at: datetime
    local_date: date
    routine_id: UUID | None = None
    notes: str | None = None
    completed_at: datetime | None = None
    duration_seconds: int | None = None
    total_volume_kg: Decimal = _ZERO
    total_sets: int = 0
    total_reps: int = 0
    perceived_effort: int | None = None
    status: SessionStatus = SessionStatus.IN_PROGRESS
    visibility: Visibility = Visibility.PRIVATE
    client_session_id: UUID | None = None
    exercises: list[SessionExercise] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        name: str,
        started_at: datetime,
        local_date: date,
        routine_id: UUID | None = None,
        notes: str | None = None,
        client_session_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> WorkoutSession:
        return cls(
            id=session_id or uuid7(),
            user_id=user_id,
            name=name.strip() or "Workout",
            started_at=started_at,
            local_date=local_date,
            routine_id=routine_id,
            notes=notes,
            client_session_id=client_session_id,
        )

    # ------------------------------------------------------------------ queries
    @property
    def is_active(self) -> bool:
        return self.status is SessionStatus.IN_PROGRESS

    @property
    def all_sets(self) -> list[SessionSet]:
        return [s for exercise in self.exercises for s in exercise.sets]

    @property
    def exercise_ids(self) -> list[UUID]:
        seen: dict[UUID, None] = {}
        for exercise in self.exercises:
            seen.setdefault(exercise.exercise_id, None)
        return list(seen)

    def find_exercise(self, session_exercise_id: UUID) -> SessionExercise | None:
        return next((e for e in self.exercises if e.id == session_exercise_id), None)

    def next_position(self) -> int:
        return max((e.position for e in self.exercises), default=0) + 1

    def sets_for_exercise(self, exercise_id: UUID) -> list[SessionSet]:
        return [
            s for entry in self.exercises if entry.exercise_id == exercise_id for s in entry.sets
        ]

    # ---------------------------------------------------------------- mutations
    def add_exercise(
        self,
        *,
        exercise_id: UUID,
        superset_group: UUID | None = None,
        rest_seconds: int | None = None,
        notes: str | None = None,
        session_exercise_id: UUID | None = None,
    ) -> SessionExercise:
        entry = SessionExercise.create(
            session_id=self.id,
            exercise_id=exercise_id,
            position=self.next_position(),
            superset_group=superset_group,
            rest_seconds=rest_seconds,
            notes=notes,
            session_exercise_id=session_exercise_id,
        )
        self.exercises.append(entry)
        return entry

    def reorder_exercises(self, ordered_ids: list[UUID]) -> None:
        known = {e.id for e in self.exercises}
        if set(ordered_ids) != known:
            raise ValueError("the new order must list every exercise in the session exactly once")
        index = {exercise_id: position for position, exercise_id in enumerate(ordered_ids, 1)}
        for exercise in self.exercises:
            exercise.position = index[exercise.id]
        self.exercises.sort(key=lambda e: e.position)

    def recalculate_totals(self) -> None:
        """Aggregates computed once, on completion, rather than on every read.

        Warm-ups are excluded from volume for the same reason they are excluded from
        records: they are not work performed, and counting them flatters the number.
        """
        counted = [s for s in self.all_sets if s.counts_toward_records]
        self.total_sets = len(counted)
        self.total_reps = sum(s.reps or 0 for s in counted)
        self.total_volume_kg = sum((s.volume_kg for s in counted), _ZERO)

    def complete(self, *, at: datetime, perceived_effort: int | None = None) -> None:
        if self.status is not SessionStatus.IN_PROGRESS:
            raise ValueError(f"session is already {self.status.value}")
        if at < self.started_at:
            raise ValueError("a session cannot finish before it started")
        self.completed_at = at
        self.duration_seconds = int((at - self.started_at).total_seconds())
        self.status = SessionStatus.COMPLETED
        if perceived_effort is not None:
            self.perceived_effort = perceived_effort
        self.recalculate_totals()

    def discard(self) -> None:
        if self.status is not SessionStatus.IN_PROGRESS:
            raise ValueError(f"session is already {self.status.value}")
        self.status = SessionStatus.DISCARDED


# ------------------------------------------------------------- personal records
@dataclass(slots=True)
class PersonalRecord:
    """A best, with the set that proved it and a chain back to what it beat."""

    id: UUID
    user_id: UUID
    exercise_id: UUID
    record_type: RecordType
    value: Decimal
    achieved_on: date
    reps_at_value: int | None = None
    session_set_id: UUID | None = None
    previous_record_id: UUID | None = None
    is_current: bool = True

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        exercise_id: UUID,
        record_type: RecordType,
        value: Decimal,
        achieved_on: date,
        reps_at_value: int | None = None,
        session_set_id: UUID | None = None,
        previous_record_id: UUID | None = None,
    ) -> PersonalRecord:
        return cls(
            id=uuid7(),
            user_id=user_id,
            exercise_id=exercise_id,
            record_type=record_type,
            value=value,
            achieved_on=achieved_on,
            reps_at_value=reps_at_value,
            session_set_id=session_set_id,
            previous_record_id=previous_record_id,
        )

    def supersede(self) -> None:
        self.is_current = False


def estimated_one_rep_max(weight_kg: Decimal | None, reps: int | None) -> Decimal | None:
    """Epley: 1RM ≈ w x (1 + r/30).

    Capped at 15 reps on purpose. The formula diverges badly from reality beyond that,
    and a "PR" derived from a 30-rep set is noise dressed up as progress. This mirrors
    the generated column on ``session_sets`` so the two can never disagree.
    """
    if weight_kg is None or reps is None:
        return None
    if reps <= 0 or reps > 15:
        return None
    if weight_kg <= _ZERO:
        return None
    return (weight_kg * (1 + Decimal(reps) / 30)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
