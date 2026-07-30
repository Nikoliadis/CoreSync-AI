"""Live workout session use cases.

The hot path of the product. Starting a session, logging sets, and finishing — the last
of which is the only place in the system that writes personal records, activity
summaries and streaks, all inside one transaction.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from coresync.application.catalog.dto import PersonalRecordDTO
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.workout.dto import (
    CalendarDayDTO,
    CompletedSessionDTO,
    SessionExerciseDTO,
    SessionHistoryPageDTO,
    SessionSetDTO,
    SessionSummaryDTO,
    StreakDTO,
    WorkoutSessionDTO,
)
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import ConflictError, NotFoundError, ValidationError
from coresync.core.logging import get_logger
from coresync.domain.workout.entities import (
    PersonalRecord,
    SessionSet,
    SessionStatus,
    SetType,
    WorkoutSession,
)
from coresync.domain.workout.services import (
    DetectedRecord,
    PersonalRecordDetector,
    VolumeCalculator,
)

logger = get_logger(__name__)

MAX_EXERCISES_PER_SESSION = 60
MAX_SETS_PER_EXERCISE = 60
_ZERO = Decimal("0")


# ---------------------------------------------------------------------- mapping
def _set_dto(entry: SessionSet) -> SessionSetDTO:
    return SessionSetDTO(
        id=entry.id,
        session_exercise_id=entry.session_exercise_id,
        set_number=entry.set_number,
        set_type=entry.set_type.value,
        reps=entry.reps,
        weight_kg=entry.weight_kg,
        duration_seconds=entry.duration_seconds,
        distance_m=entry.distance_m,
        rpe=entry.rpe,
        is_completed=entry.is_completed,
        estimated_one_rep_max=entry.estimated_one_rep_max,
        completed_at=entry.completed_at,
    )


def session_dto(
    session: WorkoutSession,
    names: dict[UUID, str] | None = None,
    logging_types: dict[UUID, str] | None = None,
) -> WorkoutSessionDTO:
    lookup = names or {}
    types = logging_types or {}
    return WorkoutSessionDTO(
        id=session.id,
        name=session.name,
        routine_id=session.routine_id,
        notes=session.notes,
        started_at=session.started_at,
        completed_at=session.completed_at,
        local_date=session.local_date,
        duration_seconds=session.duration_seconds,
        total_volume_kg=session.total_volume_kg,
        total_sets=session.total_sets,
        total_reps=session.total_reps,
        perceived_effort=session.perceived_effort,
        status=session.status.value,
        visibility=session.visibility.value,
        client_session_id=session.client_session_id,
        exercises=[
            SessionExerciseDTO(
                id=entry.id,
                exercise_id=entry.exercise_id,
                exercise_name=lookup.get(entry.exercise_id),
                logging_type=types.get(entry.exercise_id),
                position=entry.position,
                superset_group=entry.superset_group,
                rest_seconds=entry.rest_seconds,
                notes=entry.notes,
                sets=[_set_dto(s) for s in entry.sets],
            )
            for entry in session.exercises
        ],
    )


def _detected_dto(detected: DetectedRecord, record: PersonalRecord) -> PersonalRecordDTO:
    return PersonalRecordDTO(
        id=record.id,
        exercise_id=detected.exercise_id,
        record_type=detected.record_type.value,
        value=detected.value,
        reps_at_value=detected.reps_at_value,
        achieved_on=record.achieved_on,
        is_current=True,
        previous_value=detected.previous_value,
        improvement=detected.improvement,
    )


async def _decorate(uow: UnitOfWork, user_id: UUID, session: WorkoutSession) -> WorkoutSessionDTO:
    exercises = await uow.exercises.get_many(session.exercise_ids, user_id)
    return session_dto(
        session,
        {e.id: e.name for e in exercises},
        {e.id: e.logging_type.value for e in exercises},
    )


# ------------------------------------------------------------------------ start
@dataclass(frozen=True, slots=True)
class StartSessionCommand:
    user_id: UUID
    routine_id: UUID | None = None
    name: str | None = None
    notes: str | None = None
    client_session_id: UUID | None = None
    # Offline sessions are started in the past and flushed later, so the client supplies
    # the real start time rather than having the server invent one.
    started_at: datetime | None = None
    session_id: UUID | None = None


class StartSessionUseCase:
    """Begin a workout, optionally seeded from a routine.

    Idempotent on ``client_session_id``: a double-tapped "Start workout" on gym Wi-Fi
    returns the session that already exists rather than creating a second one. The
    partial unique index is the real guarantee; this lookup makes the response correct
    instead of an error.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, cmd: StartSessionCommand) -> WorkoutSessionDTO:
        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise NotFoundError("user", cmd.user_id)

            if cmd.client_session_id is not None:
                existing = await self._uow.sessions.get_by_client_id(
                    cmd.user_id, cmd.client_session_id
                )
                if existing is not None:
                    return await _decorate(self._uow, cmd.user_id, existing)

            active = await self._uow.sessions.get_active(cmd.user_id)
            if active is not None:
                raise ConflictError(
                    "You already have a workout in progress. Finish or discard it first."
                )

            started_at = _bounded_client_time(cmd.started_at, now)
            routine = None
            if cmd.routine_id is not None:
                routine = await self._uow.routines.get(cmd.routine_id, cmd.user_id)
                if routine is None:
                    raise NotFoundError("routine", cmd.routine_id)

            session = WorkoutSession.create(
                user_id=cmd.user_id,
                name=cmd.name or (routine.name if routine else "Workout"),
                started_at=started_at,
                local_date=local_date_for(started_at, user.timezone),
                routine_id=cmd.routine_id,
                notes=cmd.notes,
                client_session_id=cmd.client_session_id,
                session_id=cmd.session_id,
            )

            # Seed the session from the plan. Prescribed sets are *not* copied as logged
            # sets — the user has not done them yet, and pre-filling them would record a
            # workout nobody performed.
            if routine is not None:
                for entry in routine.exercises:
                    session.add_exercise(
                        exercise_id=entry.exercise_id,
                        superset_group=entry.superset_group,
                        rest_seconds=entry.rest_seconds,
                        notes=entry.notes,
                    )

            await self._uow.sessions.add(session)
            await self._uow.commit()

            result = await _decorate(self._uow, cmd.user_id, session)

        logger.info("workout_started", user_id=str(cmd.user_id), session_id=str(session.id))
        return result


# ------------------------------------------------------------------------- read
class GetActiveSessionUseCase:
    """Called on every app resume, so it stays a single scoped read."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> WorkoutSessionDTO | None:
        async with self._uow:
            session = await self._uow.sessions.get_active(user_id)
            if session is None:
                return None
            return await _decorate(self._uow, user_id, session)


class GetSessionUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, session_id: UUID) -> WorkoutSessionDTO:
        async with self._uow:
            session = await self._uow.sessions.get(session_id, user_id)
            if session is None:
                raise NotFoundError("workout_session", session_id)
            return await _decorate(self._uow, user_id, session)


@dataclass(frozen=True, slots=True)
class ListHistoryQuery:
    user_id: UUID
    limit: int = 25
    cursor: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class ListSessionHistoryUseCase:
    MAX_LIMIT = 100

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, query: ListHistoryQuery) -> SessionHistoryPageDTO:
        limit = min(max(query.limit, 1), self.MAX_LIMIT)
        cursor = _decode_cursor(query.cursor)

        async with self._uow:
            # One extra row tells us whether there is another page without a COUNT.
            rows = await self._uow.sessions.list_history(
                query.user_id,
                limit=limit + 1,
                cursor=cursor,
                date_from=query.date_from,
                date_to=query.date_to,
            )

        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = (
            _encode_cursor(page[-1].local_date, page[-1].id) if has_more and page else None
        )
        return SessionHistoryPageDTO(
            items=[
                SessionSummaryDTO(
                    id=row.id,
                    name=row.name,
                    routine_id=row.routine_id,
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                    local_date=row.local_date,
                    duration_seconds=row.duration_seconds,
                    total_volume_kg=row.total_volume_kg,
                    total_sets=row.total_sets,
                    total_reps=row.total_reps,
                    exercise_count=row.exercise_count,
                    pr_count=row.pr_count,
                )
                for row in page
            ],
            next_cursor=next_cursor,
            has_more=has_more,
        )


class GetCalendarUseCase:
    """Heatmap data, served from the daily aggregate rather than the raw sessions."""

    MAX_DAYS = 400

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self, user_id: UUID, *, date_from: date | None = None, date_to: date | None = None
    ) -> list[CalendarDayDTO]:
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            today = local_date_for(self._clock.now(), user.timezone if user else "UTC")
            end = date_to or today
            start = date_from or (end - timedelta(days=364))
            if (end - start).days > self.MAX_DAYS:
                raise ValidationError(f"Ask for at most {self.MAX_DAYS} days at a time.")

            days = await self._uow.summaries.range(user_id, date_from=start, date_to=end)
        return [
            CalendarDayDTO(
                local_date=day.local_date,
                workout_count=day.workout_count,
                total_volume_kg=day.total_volume_kg,
                duration_seconds=day.duration_seconds,
            )
            for day in days
        ]


# ------------------------------------------------------------------ session edit
@dataclass(frozen=True, slots=True)
class UpdateSessionCommand:
    user_id: UUID
    session_id: UUID
    name: str | None = None
    notes: str | None = None
    perceived_effort: int | None = None


class UpdateSessionUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: UpdateSessionCommand) -> WorkoutSessionDTO:
        async with self._uow:
            session = await self._uow.sessions.get(cmd.session_id, cmd.user_id)
            if session is None:
                raise NotFoundError("workout_session", cmd.session_id)

            if cmd.name is not None:
                session.name = cmd.name.strip() or session.name
            if cmd.notes is not None:
                session.notes = cmd.notes or None
            if cmd.perceived_effort is not None:
                session.perceived_effort = cmd.perceived_effort

            await self._uow.sessions.update(session)
            await self._uow.commit()
            return await _decorate(self._uow, cmd.user_id, session)


@dataclass(frozen=True, slots=True)
class AddSessionExerciseCommand:
    user_id: UUID
    session_id: UUID
    exercise_id: UUID
    superset_group: UUID | None = None
    rest_seconds: int | None = None
    notes: str | None = None
    session_exercise_id: UUID | None = None


class AddSessionExerciseUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: AddSessionExerciseCommand) -> WorkoutSessionDTO:
        async with self._uow:
            session = await _load_active(self._uow, cmd.user_id, cmd.session_id)
            if len(session.exercises) >= MAX_EXERCISES_PER_SESSION:
                raise ConflictError(
                    f"A session can hold at most {MAX_EXERCISES_PER_SESSION} exercises."
                )
            if await self._uow.exercises.get(cmd.exercise_id, cmd.user_id) is None:
                raise NotFoundError("exercise", cmd.exercise_id)

            entry = session.add_exercise(
                exercise_id=cmd.exercise_id,
                superset_group=cmd.superset_group,
                rest_seconds=cmd.rest_seconds,
                notes=cmd.notes,
                session_exercise_id=cmd.session_exercise_id,
            )
            await self._uow.sessions.add_exercise_entry(entry)
            await self._uow.commit()
            return await _decorate(self._uow, cmd.user_id, session)


@dataclass(frozen=True, slots=True)
class UpdateSessionExerciseCommand:
    user_id: UUID
    session_id: UUID
    session_exercise_id: UUID
    rest_seconds: int | None = None
    notes: str | None = None
    superset_group: UUID | None = None


class UpdateSessionExerciseUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: UpdateSessionExerciseCommand) -> WorkoutSessionDTO:
        async with self._uow:
            session = await _load_active(self._uow, cmd.user_id, cmd.session_id)
            entry = session.find_exercise(cmd.session_exercise_id)
            if entry is None:
                raise NotFoundError("session_exercise", cmd.session_exercise_id)

            if cmd.rest_seconds is not None:
                entry.rest_seconds = cmd.rest_seconds
            if cmd.notes is not None:
                entry.notes = cmd.notes or None
            if cmd.superset_group is not None:
                entry.superset_group = cmd.superset_group

            await self._uow.sessions.update_exercise_entry(entry)
            await self._uow.commit()
            return await _decorate(self._uow, cmd.user_id, session)


class RemoveSessionExerciseUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, user_id: UUID, session_id: UUID, session_exercise_id: UUID
    ) -> WorkoutSessionDTO:
        async with self._uow:
            session = await _load_active(self._uow, user_id, session_id)
            entry = session.find_exercise(session_exercise_id)
            if entry is None:
                raise NotFoundError("session_exercise", session_exercise_id)

            await self._uow.sessions.remove_exercise_entry(session_exercise_id)
            session.exercises = [e for e in session.exercises if e.id != session_exercise_id]
            await self._uow.commit()
            return await _decorate(self._uow, user_id, session)


class ReorderSessionExercisesUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, user_id: UUID, session_id: UUID, ordered_ids: list[UUID]
    ) -> WorkoutSessionDTO:
        async with self._uow:
            session = await _load_active(self._uow, user_id, session_id)
            try:
                session.reorder_exercises(ordered_ids)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            await self._uow.sessions.reorder_exercise_entries(session)
            await self._uow.commit()
            return await _decorate(self._uow, user_id, session)


# -------------------------------------------------------------------- log a set
@dataclass(frozen=True, slots=True)
class LogSetCommand:
    user_id: UUID
    session_id: UUID
    session_exercise_id: UUID
    set_type: str = "normal"
    reps: int | None = None
    weight_kg: Decimal | None = None
    duration_seconds: int | None = None
    distance_m: Decimal | None = None
    rpe: Decimal | None = None
    is_completed: bool = True
    set_id: UUID | None = None
    set_number: int | None = None
    completed_at: datetime | None = None


class LogSetUseCase:
    """The hottest write in the product.

    Deliberately does not recompute session totals: those are derived once at completion.
    Updating three aggregate columns on every set would triple the write cost of the one
    action a lifter performs forty times an hour.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, cmd: LogSetCommand) -> SessionSetDTO:
        now = self._clock.now()
        async with self._uow:
            session = await _load_active(self._uow, cmd.user_id, cmd.session_id)
            entry = session.find_exercise(cmd.session_exercise_id)
            if entry is None:
                raise NotFoundError("session_exercise", cmd.session_exercise_id)
            if len(entry.sets) >= MAX_SETS_PER_EXERCISE:
                raise ConflictError(f"An exercise can hold at most {MAX_SETS_PER_EXERCISE} sets.")

            # A replayed offline op names the same set id; return what is already there
            # rather than colliding on the primary key.
            if cmd.set_id is not None:
                existing = next((s for s in entry.sets if s.id == cmd.set_id), None)
                if existing is not None:
                    return _set_dto(existing)

            try:
                logged = SessionSet.create(
                    session_exercise_id=entry.id,
                    set_number=cmd.set_number or entry.next_set_number(),
                    set_type=SetType(cmd.set_type),
                    reps=cmd.reps,
                    weight_kg=cmd.weight_kg,
                    duration_seconds=cmd.duration_seconds,
                    distance_m=cmd.distance_m,
                    rpe=cmd.rpe,
                    is_completed=cmd.is_completed,
                    completed_at=_bounded_client_time(cmd.completed_at, now)
                    if cmd.is_completed
                    else None,
                    set_id=cmd.set_id,
                    exercise_id=entry.exercise_id,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

            await self._uow.sessions.add_set(logged)
            entry.sets.append(logged)
            await self._uow.commit()
        return _set_dto(logged)


@dataclass(frozen=True, slots=True)
class UpdateSetCommand:
    user_id: UUID
    set_id: UUID
    set_type: str | None = None
    reps: int | None = None
    weight_kg: Decimal | None = None
    duration_seconds: int | None = None
    distance_m: Decimal | None = None
    rpe: Decimal | None = None
    is_completed: bool | None = None


class UpdateSetUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: UpdateSetCommand) -> SessionSetDTO:
        async with self._uow:
            entry = await self._uow.sessions.get_set(cmd.set_id, cmd.user_id)
            if entry is None:
                raise NotFoundError("set", cmd.set_id)

            if cmd.set_type is not None:
                entry.set_type = SetType(cmd.set_type)
            if cmd.reps is not None:
                entry.reps = cmd.reps
            if cmd.weight_kg is not None:
                entry.weight_kg = cmd.weight_kg
            if cmd.duration_seconds is not None:
                entry.duration_seconds = cmd.duration_seconds
            if cmd.distance_m is not None:
                entry.distance_m = cmd.distance_m
            if cmd.rpe is not None:
                entry.rpe = cmd.rpe
            if cmd.is_completed is not None:
                entry.is_completed = cmd.is_completed

            if entry.reps is None and entry.duration_seconds is None and entry.distance_m is None:
                raise ValidationError("A set must record reps, duration or distance.")

            await self._uow.sessions.update_set(entry)
            await self._uow.commit()
        return _set_dto(entry)


class DeleteSetUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, set_id: UUID) -> None:
        async with self._uow:
            entry = await self._uow.sessions.get_set(set_id, user_id)
            if entry is None:
                raise NotFoundError("set", set_id)
            await self._uow.sessions.delete_set(set_id)
            await self._uow.commit()


# ---------------------------------------------------------------------- finish
@dataclass(frozen=True, slots=True)
class CompleteSessionCommand:
    user_id: UUID
    session_id: UUID
    perceived_effort: int | None = None
    completed_at: datetime | None = None


class CompleteSessionUseCase:
    """Finish a workout.

    One transaction covers the session, its records, the daily aggregate, the per-exercise
    statistics and the streak. Anything less and a crash mid-way leaves a completed
    workout that the dashboard cannot see, which is worse than not having finished at all.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        detector: PersonalRecordDetector,
        volume: VolumeCalculator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._detector = detector
        self._volume = volume
        self._clock = clock

    async def execute(self, cmd: CompleteSessionCommand) -> CompletedSessionDTO:
        now = self._clock.now()
        async with self._uow:
            session = await self._uow.sessions.get(cmd.session_id, cmd.user_id)
            if session is None:
                raise NotFoundError("workout_session", cmd.session_id)
            if session.status is not SessionStatus.IN_PROGRESS:
                raise ConflictError("This workout has already been finished.")

            completed_at = _bounded_client_time(cmd.completed_at, now)
            if completed_at < session.started_at:
                completed_at = now

            try:
                session.complete(at=completed_at, perceived_effort=cmd.perceived_effort)
            except ValueError as exc:
                raise ConflictError(str(exc)) from exc

            all_sets = session.all_sets
            current = await self._uow.records.current_for_exercises(
                cmd.user_id, session.exercise_ids
            )
            detected = self._detector.detect(all_sets, current)

            records = [
                PersonalRecord.create(
                    user_id=cmd.user_id,
                    exercise_id=d.exercise_id,
                    record_type=d.record_type,
                    value=d.value,
                    achieved_on=session.local_date,
                    reps_at_value=d.reps_at_value,
                    session_set_id=d.session_set_id,
                    previous_record_id=d.previous_record_id,
                )
                for d in detected
            ]
            await self._uow.records.supersede_and_add(
                [d.previous_record_id for d in detected if d.previous_record_id], records
            )

            await self._uow.sessions.update(session)
            if session.routine_id is not None:
                await self._uow.routines.touch_last_performed(session.routine_id, completed_at)

            await self._apply_aggregates(session, detected_count=len(records))
            streak = await self._uow.streaks.register_workout(cmd.user_id, session.local_date)
            await self._uow.commit()

            payload = await _decorate(self._uow, cmd.user_id, session)

        logger.info(
            "workout_completed",
            user_id=str(cmd.user_id),
            session_id=str(session.id),
            new_records=len(records),
        )
        return CompletedSessionDTO(
            session=payload,
            new_records=[_detected_dto(d, r) for d, r in zip(detected, records, strict=True)],
            streak=StreakDTO(
                current=streak.workout_current,
                longest=streak.workout_longest,
                last_workout_date=streak.workout_last_date,
            ),
        )

    async def _apply_aggregates(self, session: WorkoutSession, *, detected_count: int) -> None:
        counted = [s for s in session.all_sets if s.counts_toward_records]
        contributions = await self._uow.catalog.muscle_group_contributions(session.exercise_ids)

        await self._uow.summaries.apply_workout(
            user_id=session.user_id,
            local_date=session.local_date,
            volume_kg=session.total_volume_kg,
            set_count=session.total_sets,
            duration_seconds=session.duration_seconds or 0,
            volume_by_muscle_group=self._volume.by_muscle_group(counted, contributions),
            pr_count=detected_count,
        )

        for exercise_id in session.exercise_ids:
            exercise_sets = [s for s in counted if s.exercise_id == exercise_id]
            if not exercise_sets:
                continue
            best = max(
                (s.estimated_one_rep_max for s in exercise_sets if s.estimated_one_rep_max),
                default=None,
            )
            await self._uow.exercise_stats.apply_session(
                user_id=session.user_id,
                exercise_id=exercise_id,
                local_date=session.local_date,
                set_count=len(exercise_sets),
                volume_kg=sum((s.volume_kg for s in exercise_sets), _ZERO),
                best_est_1rm=best,
            )


class DiscardSessionUseCase:
    """Abandon a workout without writing it to history.

    Any records the session managed to set are removed and whatever they superseded is
    restored — otherwise discarding would silently cost the user a PR they still hold.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, session_id: UUID) -> None:
        async with self._uow:
            session = await self._uow.sessions.get(session_id, user_id)
            if session is None:
                raise NotFoundError("workout_session", session_id)
            if session.status is not SessionStatus.IN_PROGRESS:
                raise ConflictError("Only a workout in progress can be discarded.")

            session.discard()
            await self._uow.records.delete_for_session(session_id, user_id)
            await self._uow.sessions.update(session)
            await self._uow.commit()

        logger.info("workout_discarded", user_id=str(user_id), session_id=str(session_id))


class DeleteSessionUseCase:
    """Soft-delete a completed session and back its numbers out of the aggregates."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, session_id: UUID) -> None:
        async with self._uow:
            session = await self._uow.sessions.get(session_id, user_id)
            if session is None:
                raise NotFoundError("workout_session", session_id)

            if session.status is SessionStatus.COMPLETED:
                await self._uow.summaries.revert_workout(
                    user_id=user_id,
                    local_date=session.local_date,
                    volume_kg=session.total_volume_kg,
                    set_count=session.total_sets,
                    duration_seconds=session.duration_seconds or 0,
                    pr_count=0,
                )
            await self._uow.records.delete_for_session(session_id, user_id)
            await self._uow.sessions.soft_delete(session_id, user_id)
            await self._uow.commit()


# ---------------------------------------------------------------------- helpers
async def _load_active(uow: UnitOfWork, user_id: UUID, session_id: UUID) -> WorkoutSession:
    session = await uow.sessions.get(session_id, user_id)
    if session is None:
        raise NotFoundError("workout_session", session_id)
    if session.status is not SessionStatus.IN_PROGRESS:
        raise ConflictError("This workout has already been finished.")
    return session


def _bounded_client_time(supplied: datetime | None, now: datetime) -> datetime:
    """Trust the client's clock, but not past the present.

    Offline logging genuinely happened in the past, so a client timestamp is the honest
    one. A phone with a wrong clock claiming to be from 2030 must not be able to write a
    workout into the future (docs/04 §7, rule 5).
    """
    if supplied is None:
        return now
    return min(supplied, now)


def _encode_cursor(local_date: date, session_id: UUID) -> str:
    payload = json.dumps({"d": local_date.isoformat(), "i": str(session_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[date, UUID] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        return date.fromisoformat(payload["d"]), UUID(payload["i"])
    except (ValueError, KeyError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationError("That pagination cursor is not valid.") from exc


__all__ = [
    "AddSessionExerciseCommand",
    "AddSessionExerciseUseCase",
    "CompleteSessionCommand",
    "CompleteSessionUseCase",
    "DeleteSessionUseCase",
    "DeleteSetUseCase",
    "DiscardSessionUseCase",
    "GetActiveSessionUseCase",
    "GetCalendarUseCase",
    "GetSessionUseCase",
    "ListHistoryQuery",
    "ListSessionHistoryUseCase",
    "LogSetCommand",
    "LogSetUseCase",
    "RemoveSessionExerciseUseCase",
    "ReorderSessionExercisesUseCase",
    "SessionExerciseDTO",
    "StartSessionCommand",
    "StartSessionUseCase",
    "UpdateSessionCommand",
    "UpdateSessionExerciseCommand",
    "UpdateSessionExerciseUseCase",
    "UpdateSessionUseCase",
    "UpdateSetCommand",
    "UpdateSetUseCase",
    "session_dto",
]
