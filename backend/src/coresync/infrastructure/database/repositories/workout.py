"""SQLAlchemy implementations of the workout repository ports.

Ownership is expressed in the query, never checked afterwards in Python. A read that
forgets its `user_id` predicate is an IDOR, and the only reliable defence is that no
method offers the unscoped shape (docs/05 §3).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from coresync.domain.workout.entities import (
    PersonalRecord,
    RecordType,
    Routine,
    SessionExercise,
    SessionSet,
    WorkoutSession,
)
from coresync.domain.workout.repositories import (
    CalendarDay,
    ExerciseHistoryEntry,
    ExerciseStatistics,
    MuscleVolumeDay,
    SessionSummary,
    StaleVersionError,
    Streak,
)
from coresync.domain.workout.services import StreakCalculator
from coresync.infrastructure.database.mappers import (
    PersonalRecordMapper,
    RoutineExerciseMapper,
    RoutineMapper,
    SessionExerciseMapper,
    SessionSetMapper,
    WorkoutSessionMapper,
)
from coresync.infrastructure.database.models.aggregates import (
    DailyActivitySummaryModel,
    ExerciseStatisticsModel,
    UserStreakModel,
)
from coresync.infrastructure.database.models.workout import (
    PersonalRecordModel,
    RoutineModel,
    SessionExerciseModel,
    SessionSetModel,
    SyncOperationModel,
    WorkoutSessionModel,
)

_ZERO = Decimal("0")


# ---------------------------------------------------------------------- routines
class SqlAlchemyRoutineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, routine_id: UUID, user_id: UUID) -> Routine | None:
        stmt = select(RoutineModel).where(
            RoutineModel.id == routine_id,
            RoutineModel.user_id == user_id,
            RoutineModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).unique().scalar_one_or_none()
        return RoutineMapper.to_entity(model) if model else None

    async def get_template(self, routine_id: UUID) -> Routine | None:
        stmt = select(RoutineModel).where(
            RoutineModel.id == routine_id,
            RoutineModel.is_template.is_(True),
            RoutineModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).unique().scalar_one_or_none()
        return RoutineMapper.to_entity(model) if model else None

    async def list_for_user(self, user_id: UUID) -> list[Routine]:
        stmt = (
            select(RoutineModel)
            .where(RoutineModel.user_id == user_id, RoutineModel.deleted_at.is_(None))
            .order_by(RoutineModel.folder.nullsfirst(), RoutineModel.position, RoutineModel.name)
        )
        rows = (await self._session.execute(stmt)).unique().scalars().all()
        return [RoutineMapper.to_entity(m) for m in rows]

    async def list_templates(self) -> list[Routine]:
        stmt = (
            select(RoutineModel)
            .where(RoutineModel.is_template.is_(True), RoutineModel.deleted_at.is_(None))
            .order_by(RoutineModel.position, RoutineModel.name)
        )
        rows = (await self._session.execute(stmt)).unique().scalars().all()
        return [RoutineMapper.to_entity(m) for m in rows]

    async def add(self, routine: Routine) -> None:
        self._session.add(RoutineMapper.to_model(routine))
        await self._session.flush()

    async def update(self, routine: Routine, *, expected_version: int | None = None) -> None:
        model = await self._session.get(RoutineModel, routine.id)
        if model is None:
            raise ValueError(f"routine {routine.id} does not exist")
        if expected_version is not None and model.version != expected_version:
            raise StaleVersionError(
                f"routine {routine.id} is at version {model.version}, not {expected_version}"
            )
        RoutineMapper.apply(routine, model)
        model.version = model.version + 1
        routine.version = model.version
        await self._session.flush()

    async def replace_exercises(self, routine: Routine) -> None:
        """Delete-and-rewrite rather than a diff.

        A routine holds a handful of exercises, the client always sends the whole list,
        and reconciling positions incrementally is where off-by-one reorder bugs live.
        """
        model = await self._session.get(RoutineModel, routine.id)
        if model is None:
            raise ValueError(f"routine {routine.id} does not exist")
        model.exercises = [
            RoutineExerciseMapper.to_model(entry, routine.id) for entry in routine.exercises
        ]
        model.version = model.version + 1
        routine.version = model.version
        await self._session.flush()

    async def delete(self, routine_id: UUID, user_id: UUID) -> None:
        stmt = (
            update(RoutineModel)
            .where(
                RoutineModel.id == routine_id,
                RoutineModel.user_id == user_id,
                RoutineModel.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def touch_last_performed(self, routine_id: UUID, at: datetime) -> None:
        stmt = (
            update(RoutineModel).where(RoutineModel.id == routine_id).values(last_performed_at=at)
        )
        await self._session.execute(stmt)


# ---------------------------------------------------------------------- sessions
class SqlAlchemyWorkoutSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _full(self) -> Select[tuple[WorkoutSessionModel]]:
        return select(WorkoutSessionModel).options(
            selectinload(WorkoutSessionModel.exercises).selectinload(SessionExerciseModel.sets)
        )

    async def get(self, session_id: UUID, user_id: UUID) -> WorkoutSession | None:
        stmt = self._full().where(
            WorkoutSessionModel.id == session_id,
            WorkoutSessionModel.user_id == user_id,  # ownership in the query
            WorkoutSessionModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).unique().scalar_one_or_none()
        return WorkoutSessionMapper.to_entity(model) if model else None

    async def get_active(self, user_id: UUID) -> WorkoutSession | None:
        stmt = self._full().where(
            WorkoutSessionModel.user_id == user_id,
            WorkoutSessionModel.status == "in_progress",
            WorkoutSessionModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).unique().scalar_one_or_none()
        return WorkoutSessionMapper.to_entity(model) if model else None

    async def get_by_client_id(
        self, user_id: UUID, client_session_id: UUID
    ) -> WorkoutSession | None:
        stmt = self._full().where(
            WorkoutSessionModel.user_id == user_id,
            WorkoutSessionModel.client_session_id == client_session_id,
            WorkoutSessionModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).unique().scalar_one_or_none()
        return WorkoutSessionMapper.to_entity(model) if model else None

    async def add(self, session: WorkoutSession) -> None:
        self._session.add(WorkoutSessionMapper.to_model(session))
        await self._session.flush()

    async def update(self, session: WorkoutSession) -> None:
        model = await self._session.get(WorkoutSessionModel, session.id)
        if model is None:
            raise ValueError(f"session {session.id} does not exist")
        WorkoutSessionMapper.apply(session, model)
        await self._session.flush()

    async def soft_delete(self, session_id: UUID, user_id: UUID) -> None:
        stmt = (
            update(WorkoutSessionModel)
            .where(
                WorkoutSessionModel.id == session_id,
                WorkoutSessionModel.user_id == user_id,
            )
            .values(deleted_at=func.now())
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_history(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor: tuple[date, UUID] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[SessionSummary]:
        """History rows without loading every set.

        A year of training is ~150 sessions x 25 sets; materialising those to render a
        list would be several thousand rows for a screen that shows a date and a volume.
        """
        exercise_count = (
            select(func.count(SessionExerciseModel.id))
            .where(SessionExerciseModel.session_id == WorkoutSessionModel.id)
            .correlate(WorkoutSessionModel)
            .scalar_subquery()
        )
        pr_count = (
            select(func.count(PersonalRecordModel.id))
            .join(SessionSetModel, SessionSetModel.id == PersonalRecordModel.session_set_id)
            .join(
                SessionExerciseModel,
                SessionExerciseModel.id == SessionSetModel.session_exercise_id,
            )
            .where(SessionExerciseModel.session_id == WorkoutSessionModel.id)
            .correlate(WorkoutSessionModel)
            .scalar_subquery()
        )

        stmt = select(WorkoutSessionModel, exercise_count, pr_count).where(
            WorkoutSessionModel.user_id == user_id,
            WorkoutSessionModel.deleted_at.is_(None),
            WorkoutSessionModel.status == "completed",
        )
        if date_from is not None:
            stmt = stmt.where(WorkoutSessionModel.local_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(WorkoutSessionModel.local_date <= date_to)
        if cursor is not None:
            # Keyset pagination on (local_date, id). OFFSET would drift as new sessions
            # land at the head of the list mid-scroll.
            cursor_date, cursor_id = cursor
            stmt = stmt.where(
                (WorkoutSessionModel.local_date, WorkoutSessionModel.id) < (cursor_date, cursor_id)
            )

        stmt = stmt.order_by(
            WorkoutSessionModel.local_date.desc(), WorkoutSessionModel.id.desc()
        ).limit(limit)

        rows = (await self._session.execute(stmt)).unique().all()
        return [
            SessionSummary(
                id=model.id,
                name=model.name,
                routine_id=model.routine_id,
                started_at=model.started_at,
                completed_at=model.completed_at,
                local_date=model.local_date,
                duration_seconds=model.duration_seconds,
                total_volume_kg=model.total_volume_kg,
                total_sets=model.total_sets,
                total_reps=model.total_reps,
                status=model.status,
                exercise_count=int(exercises or 0),
                pr_count=int(prs or 0),
            )
            for model, exercises, prs in rows
        ]

    async def calendar(self, user_id: UUID, *, date_from: date, date_to: date) -> list[CalendarDay]:
        stmt = (
            select(
                WorkoutSessionModel.local_date,
                func.count(WorkoutSessionModel.id),
                func.coalesce(func.sum(WorkoutSessionModel.total_volume_kg), 0),
                func.coalesce(func.sum(WorkoutSessionModel.duration_seconds), 0),
            )
            .where(
                WorkoutSessionModel.user_id == user_id,
                WorkoutSessionModel.deleted_at.is_(None),
                WorkoutSessionModel.status == "completed",
                WorkoutSessionModel.local_date >= date_from,
                WorkoutSessionModel.local_date <= date_to,
            )
            .group_by(WorkoutSessionModel.local_date)
            .order_by(WorkoutSessionModel.local_date)
        )
        return [
            CalendarDay(
                local_date=day,
                workout_count=int(count),
                total_volume_kg=Decimal(volume),
                duration_seconds=int(duration),
            )
            for day, count, volume, duration in (await self._session.execute(stmt)).all()
        ]

    async def exercise_history(
        self, user_id: UUID, exercise_id: UUID, *, limit: int
    ) -> list[ExerciseHistoryEntry]:
        stmt = (
            select(WorkoutSessionModel, SessionExerciseModel)
            .join(
                SessionExerciseModel,
                SessionExerciseModel.session_id == WorkoutSessionModel.id,
            )
            .options(selectinload(SessionExerciseModel.sets))
            .where(
                WorkoutSessionModel.user_id == user_id,
                WorkoutSessionModel.deleted_at.is_(None),
                WorkoutSessionModel.status == "completed",
                SessionExerciseModel.exercise_id == exercise_id,
            )
            .order_by(WorkoutSessionModel.local_date.desc())
            .limit(limit)
        )
        entries: list[ExerciseHistoryEntry] = []
        for session_model, entry_model in (await self._session.execute(stmt)).unique().all():
            sets = [
                SessionSetMapper.to_entity(s, exercise_id=exercise_id) for s in entry_model.sets
            ]
            counted = [s for s in sets if s.counts_toward_records]
            best = max(
                counted,
                key=lambda s: s.estimated_one_rep_max or s.volume_kg or _ZERO,
                default=None,
            )
            entries.append(
                ExerciseHistoryEntry(
                    session_id=session_model.id,
                    session_name=session_model.name,
                    local_date=session_model.local_date,
                    sets=sets,
                    best_set_id=best.id if best else None,
                    total_volume_kg=sum((s.volume_kg for s in counted), _ZERO),
                )
            )
        return entries

    # --------------------------------------------------------- set-level writes
    async def add_exercise_entry(self, entry: SessionExercise) -> None:
        self._session.add(SessionExerciseMapper.to_model(entry))
        await self._session.flush()

    async def update_exercise_entry(self, entry: SessionExercise) -> None:
        model = await self._session.get(SessionExerciseModel, entry.id)
        if model is None:
            raise ValueError(f"session exercise {entry.id} does not exist")
        SessionExerciseMapper.apply(entry, model)
        await self._session.flush()

    async def remove_exercise_entry(self, session_exercise_id: UUID) -> None:
        model = await self._session.get(SessionExerciseModel, session_exercise_id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()

    async def reorder_exercise_entries(self, session: WorkoutSession) -> None:
        """Two passes, because ``uq_session_exercise_position`` would trip mid-swap.

        Positions are pushed into a temporary high range first, then written down to
        their targets — the standard trick for reordering under a unique constraint.
        """
        for offset, entry in enumerate(session.exercises, start=1):
            await self._session.execute(
                update(SessionExerciseModel)
                .where(SessionExerciseModel.id == entry.id)
                .values(position=1000 + offset)
            )
        await self._session.flush()
        for entry in session.exercises:
            await self._session.execute(
                update(SessionExerciseModel)
                .where(SessionExerciseModel.id == entry.id)
                .values(position=entry.position)
            )
        await self._session.flush()

    async def add_set(self, entry: SessionSet) -> None:
        self._session.add(SessionSetMapper.to_model(entry))
        await self._session.flush()

    async def update_set(self, entry: SessionSet) -> None:
        model = await self._session.get(SessionSetModel, entry.id)
        if model is None:
            raise ValueError(f"set {entry.id} does not exist")
        SessionSetMapper.apply(entry, model)
        await self._session.flush()

    async def delete_set(self, set_id: UUID) -> None:
        await self._session.execute(delete(SessionSetModel).where(SessionSetModel.id == set_id))
        await self._session.flush()

    async def get_set(self, set_id: UUID, user_id: UUID) -> SessionSet | None:
        stmt = (
            select(SessionSetModel, SessionExerciseModel.exercise_id)
            .join(
                SessionExerciseModel,
                SessionExerciseModel.id == SessionSetModel.session_exercise_id,
            )
            .join(
                WorkoutSessionModel,
                WorkoutSessionModel.id == SessionExerciseModel.session_id,
            )
            .where(
                SessionSetModel.id == set_id,
                WorkoutSessionModel.user_id == user_id,
                WorkoutSessionModel.deleted_at.is_(None),
            )
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        model, exercise_id = row
        return SessionSetMapper.to_entity(model, exercise_id=exercise_id)


# --------------------------------------------------------------- personal records
class SqlAlchemyPersonalRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current_for_exercises(
        self, user_id: UUID, exercise_ids: list[UUID]
    ) -> dict[tuple[UUID, RecordType], PersonalRecord]:
        if not exercise_ids:
            return {}
        stmt = select(PersonalRecordModel).where(
            PersonalRecordModel.user_id == user_id,
            PersonalRecordModel.exercise_id.in_(exercise_ids),
            PersonalRecordModel.is_current.is_(True),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return {
            (m.exercise_id, RecordType(m.record_type)): PersonalRecordMapper.to_entity(m)
            for m in rows
        }

    async def list_current(self, user_id: UUID) -> list[PersonalRecord]:
        stmt = (
            select(PersonalRecordModel)
            .where(
                PersonalRecordModel.user_id == user_id,
                PersonalRecordModel.is_current.is_(True),
            )
            .order_by(PersonalRecordModel.achieved_on.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [PersonalRecordMapper.to_entity(m) for m in rows]

    async def list_for_exercise(self, user_id: UUID, exercise_id: UUID) -> list[PersonalRecord]:
        stmt = (
            select(PersonalRecordModel)
            .where(
                PersonalRecordModel.user_id == user_id,
                PersonalRecordModel.exercise_id == exercise_id,
            )
            .order_by(PersonalRecordModel.achieved_on.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [PersonalRecordMapper.to_entity(m) for m in rows]

    async def supersede_and_add(
        self, superseded_ids: list[UUID], records: list[PersonalRecord]
    ) -> None:
        """Clear the old winners before inserting the new ones.

        The partial unique index on ``is_current`` permits exactly one current record per
        (user, exercise, type), so the order of these two statements is load-bearing.
        """
        if superseded_ids:
            await self._session.execute(
                update(PersonalRecordModel)
                .where(PersonalRecordModel.id.in_(superseded_ids))
                .values(is_current=False)
            )
            await self._session.flush()
        for record in records:
            self._session.add(PersonalRecordMapper.to_model(record))
        if records:
            await self._session.flush()

    async def delete_for_session(self, session_id: UUID, user_id: UUID) -> None:
        """Undo a session's records, restoring whatever they superseded.

        Without the restore step, discarding a session would leave the exercise with no
        current record at all — the user would appear to have lost a PR they still hold.
        """
        set_ids = (
            select(SessionSetModel.id)
            .join(
                SessionExerciseModel,
                SessionExerciseModel.id == SessionSetModel.session_exercise_id,
            )
            .where(SessionExerciseModel.session_id == session_id)
        )
        stmt = select(PersonalRecordModel).where(
            PersonalRecordModel.user_id == user_id,
            PersonalRecordModel.session_set_id.in_(set_ids),
        )
        doomed = list((await self._session.execute(stmt)).scalars().all())
        if not doomed:
            return

        restore_ids = [m.previous_record_id for m in doomed if m.previous_record_id]
        await self._session.execute(
            delete(PersonalRecordModel).where(PersonalRecordModel.id.in_([m.id for m in doomed]))
        )
        if restore_ids:
            await self._session.execute(
                update(PersonalRecordModel)
                .where(PersonalRecordModel.id.in_(restore_ids))
                .values(is_current=True)
            )
        await self._session.flush()


# -------------------------------------------------------------------- aggregates
class SqlAlchemyActivitySummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
    ) -> None:
        """Add this workout into the day's row, creating it if this is the first.

        The row is locked for the read-modify-write so two sessions completing at once
        on the same day cannot lose one another's contribution. Locking one summary row
        is cheap; getting the arithmetic wrong shows up as a dashboard that disagrees
        with the workout list, which is the kind of bug users never report and never
        forgive.
        """
        existing = await self._session.get(
            DailyActivitySummaryModel, (user_id, local_date), with_for_update=True
        )
        if existing is None:
            self._session.add(
                DailyActivitySummaryModel(
                    user_id=user_id,
                    local_date=local_date,
                    workout_count=1,
                    total_volume_kg=volume_kg,
                    total_sets=set_count,
                    duration_seconds=duration_seconds,
                    volume_by_muscle_group={k: str(v) for k, v in volume_by_muscle_group.items()},
                    pr_count=pr_count,
                )
            )
            await self._session.flush()
            return

        merged = dict(existing.volume_by_muscle_group or {})
        for group, value in volume_by_muscle_group.items():
            merged[group] = str(Decimal(merged.get(group, "0")) + value)

        existing.workout_count += 1
        existing.total_volume_kg += volume_kg
        existing.total_sets += set_count
        existing.duration_seconds += duration_seconds
        existing.pr_count += pr_count
        existing.volume_by_muscle_group = merged
        await self._session.flush()

    async def revert_workout(
        self,
        *,
        user_id: UUID,
        local_date: date,
        volume_kg: Decimal,
        set_count: int,
        duration_seconds: int,
        pr_count: int,
    ) -> None:
        """Subtract a deleted session back out.

        Clamped at zero: a summary that has already been reconciled must not be driven
        negative by a late delete.
        """
        stmt = (
            update(DailyActivitySummaryModel)
            .where(
                DailyActivitySummaryModel.user_id == user_id,
                DailyActivitySummaryModel.local_date == local_date,
            )
            .values(
                workout_count=func.greatest(DailyActivitySummaryModel.workout_count - 1, 0),
                total_volume_kg=func.greatest(
                    DailyActivitySummaryModel.total_volume_kg - volume_kg, 0
                ),
                total_sets=func.greatest(DailyActivitySummaryModel.total_sets - set_count, 0),
                duration_seconds=func.greatest(
                    DailyActivitySummaryModel.duration_seconds - duration_seconds, 0
                ),
                pr_count=func.greatest(DailyActivitySummaryModel.pr_count - pr_count, 0),
                updated_at=func.now(),
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def muscle_volume_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[MuscleVolumeDay]:
        stmt = (
            select(
                DailyActivitySummaryModel.local_date,
                DailyActivitySummaryModel.volume_by_muscle_group,
                DailyActivitySummaryModel.total_sets,
            )
            .where(
                DailyActivitySummaryModel.user_id == user_id,
                DailyActivitySummaryModel.local_date >= date_from,
                DailyActivitySummaryModel.local_date <= date_to,
            )
            .order_by(DailyActivitySummaryModel.local_date)
        )
        days: list[MuscleVolumeDay] = []
        for on, split, sets in (await self._session.execute(stmt)).all():
            # The jsonb stores decimals as strings so summing stays exact.
            days.append(
                MuscleVolumeDay(
                    local_date=on,
                    volume_by_muscle_group={
                        group: Decimal(str(value)) for group, value in (split or {}).items()
                    },
                    total_sets=int(sets or 0),
                )
            )
        return days

    async def range(self, user_id: UUID, *, date_from: date, date_to: date) -> list[CalendarDay]:
        stmt = (
            select(DailyActivitySummaryModel)
            .where(
                DailyActivitySummaryModel.user_id == user_id,
                DailyActivitySummaryModel.local_date >= date_from,
                DailyActivitySummaryModel.local_date <= date_to,
            )
            .order_by(DailyActivitySummaryModel.local_date)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [
            CalendarDay(
                local_date=m.local_date,
                workout_count=m.workout_count,
                total_volume_kg=m.total_volume_kg,
                duration_seconds=m.duration_seconds,
                total_sets=m.total_sets,
            )
            for m in rows
        ]


class SqlAlchemyExerciseStatisticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def apply_session(
        self,
        *,
        user_id: UUID,
        exercise_id: UUID,
        local_date: date,
        set_count: int,
        volume_kg: Decimal,
        best_est_1rm: Decimal | None,
    ) -> None:
        stmt = pg_insert(ExerciseStatisticsModel).values(
            user_id=user_id,
            exercise_id=exercise_id,
            total_sessions=1,
            total_sets=set_count,
            total_volume_kg=volume_kg,
            best_est_1rm=best_est_1rm,
            last_performed_on=local_date,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "exercise_id"],
            set_={
                "total_sessions": ExerciseStatisticsModel.total_sessions + 1,
                "total_sets": ExerciseStatisticsModel.total_sets + set_count,
                "total_volume_kg": ExerciseStatisticsModel.total_volume_kg + volume_kg,
                "best_est_1rm": func.greatest(ExerciseStatisticsModel.best_est_1rm, best_est_1rm)
                if best_est_1rm is not None
                else ExerciseStatisticsModel.best_est_1rm,
                "last_performed_on": func.greatest(
                    ExerciseStatisticsModel.last_performed_on, local_date
                ),
                "updated_at": func.now(),
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def get_many(
        self, user_id: UUID, exercise_ids: list[UUID]
    ) -> dict[UUID, ExerciseStatistics]:
        if not exercise_ids:
            return {}
        stmt = select(ExerciseStatisticsModel).where(
            ExerciseStatisticsModel.user_id == user_id,
            ExerciseStatisticsModel.exercise_id.in_(exercise_ids),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return {
            m.exercise_id: ExerciseStatistics(
                exercise_id=m.exercise_id,
                total_sessions=m.total_sessions,
                total_sets=m.total_sets,
                total_volume_kg=m.total_volume_kg,
                best_est_1rm=m.best_est_1rm,
                last_performed_on=m.last_performed_on,
            )
            for m in rows
        }


class SqlAlchemyStreakRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        # The streak rules live in the domain; this repository only persists the result.
        self._calculator = StreakCalculator()

    async def get(self, user_id: UUID) -> Streak | None:
        model = await self._session.get(UserStreakModel, user_id)
        return _streak(model) if model else None

    async def register_workout(self, user_id: UUID, workout_date: date) -> Streak:
        model = await self._session.get(UserStreakModel, user_id, with_for_update=True)
        if model is None:
            model = UserStreakModel(user_id=user_id)
            self._session.add(model)
            await self._session.flush()

        current, longest, last = self._calculator.apply(
            workout_date=workout_date,
            last_date=model.workout_last_date,
            current=model.workout_current,
            longest=model.workout_longest,
        )
        model.workout_current = current
        model.workout_longest = longest
        model.workout_last_date = last
        await self._session.flush()
        return _streak(model)


def _streak(model: UserStreakModel) -> Streak:
    return Streak(
        user_id=model.user_id,
        workout_current=model.workout_current,
        workout_longest=model.workout_longest,
        workout_last_date=model.workout_last_date,
        nutrition_current=model.nutrition_current,
        nutrition_longest=model.nutrition_longest,
        nutrition_last_date=model.nutrition_last_date,
    )


# ------------------------------------------------------------------ offline sync
class SqlAlchemySyncOperationLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def seen(self, user_id: UUID, op_ids: list[UUID]) -> set[UUID]:
        if not op_ids:
            return set()
        stmt = select(SyncOperationModel.op_id).where(
            SyncOperationModel.user_id == user_id,
            SyncOperationModel.op_id.in_(op_ids),
        )
        return set((await self._session.execute(stmt)).scalars().all())

    async def record(
        self, user_id: UUID, device_id: UUID | None, op_ids: list[UUID], at: datetime
    ) -> None:
        if not op_ids:
            return
        stmt = (
            pg_insert(SyncOperationModel)
            .values(
                [
                    {
                        "op_id": op_id,
                        "user_id": user_id,
                        "device_id": device_id,
                        "applied_at": at,
                    }
                    for op_id in op_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["op_id", "user_id"])
        )
        await self._session.execute(stmt)
        await self._session.flush()
