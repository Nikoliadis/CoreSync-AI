"""Exercise catalog use cases.

Browsing and searching the library, plus the one thing users can write to it: their own
custom exercises. Everything here is scoped to the caller — the repository ports do not
offer an unscoped read, so a missing filter is a compile-time absence rather than a
runtime leak.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from coresync.application.catalog.dto import (
    EquipmentDTO,
    ExerciseCategoryDTO,
    ExerciseDTO,
    ExerciseHistoryDTO,
    ExerciseHistorySessionDTO,
    ExercisePageDTO,
    MediaDTO,
    MuscleGroupDTO,
    MuscleRefDTO,
    PersonalRecordDTO,
    SetHistoryDTO,
)
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from coresync.core.logging import get_logger
from coresync.domain.catalog.entities import (
    Difficulty,
    Exercise,
    ExerciseMuscle,
    ForceType,
    LoggingType,
    Mechanic,
    MuscleRole,
)
from coresync.domain.catalog.repositories import ExerciseFilter
from coresync.domain.workout.entities import PersonalRecord, SessionSet

logger = get_logger(__name__)

MAX_CUSTOM_EXERCISES = 300


# ---------------------------------------------------------------------- mapping
def exercise_dto(exercise: Exercise) -> ExerciseDTO:
    return ExerciseDTO(
        id=exercise.id,
        slug=exercise.slug,
        name=exercise.name,
        category_slug=exercise.category_slug,
        logging_type=exercise.logging_type.value,
        difficulty=exercise.difficulty.value,
        force_type=exercise.force_type.value if exercise.force_type else None,
        mechanic=exercise.mechanic.value if exercise.mechanic else None,
        is_unilateral=exercise.is_unilateral,
        is_verified=exercise.is_verified,
        is_custom=exercise.is_custom,
        is_favorite=exercise.is_favorite,
        description=exercise.description,
        instructions=list(exercise.instructions),
        muscles=[
            MuscleRefDTO(
                id=m.muscle_id,
                slug=m.muscle_slug or "",
                name=m.muscle_name or "",
                group_slug=m.muscle_group_slug,
                role=m.role.value,
                contribution_pct=m.contribution_pct,
            )
            for m in exercise.muscles
        ],
        equipment=list(exercise.equipment_slugs),
        media=[
            MediaDTO(id=media.id, media_type=media.media_type, url=media.url)
            for media in exercise.media
        ],
    )


def record_dto(record: PersonalRecord, *, exercise_name: str | None = None) -> PersonalRecordDTO:
    return PersonalRecordDTO(
        id=record.id,
        exercise_id=record.exercise_id,
        record_type=record.record_type.value,
        value=record.value,
        reps_at_value=record.reps_at_value,
        achieved_on=record.achieved_on,
        is_current=record.is_current,
        exercise_name=exercise_name,
    )


def _set_history_dto(entry: SessionSet) -> SetHistoryDTO:
    return SetHistoryDTO(
        id=entry.id,
        set_number=entry.set_number,
        set_type=entry.set_type.value,
        reps=entry.reps,
        weight_kg=entry.weight_kg,
        duration_seconds=entry.duration_seconds,
        distance_m=entry.distance_m,
        rpe=entry.rpe,
        is_completed=entry.is_completed,
        estimated_1rm=entry.estimated_one_rep_max,
    )


# ------------------------------------------------------------------------- read
@dataclass(frozen=True, slots=True)
class SearchExercisesQuery:
    user_id: UUID
    query: str | None = None
    muscle_groups: tuple[str, ...] = ()
    muscles: tuple[str, ...] = ()
    equipment: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    difficulty: str | None = None
    logging_type: str | None = None
    favorites_only: bool = False
    custom_only: bool = False
    limit: int = 50
    offset: int = 0


class SearchExercisesUseCase:
    """The catalog listing. Cached and ETagged at the edge (docs/04 §4)."""

    MAX_LIMIT = 100

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, query: SearchExercisesQuery) -> ExercisePageDTO:
        limit = min(max(query.limit, 1), self.MAX_LIMIT)
        offset = max(query.offset, 0)

        criteria = ExerciseFilter(
            query=query.query,
            muscle_group_slugs=query.muscle_groups,
            muscle_slugs=query.muscles,
            equipment_slugs=query.equipment,
            category_slugs=query.categories,
            difficulty=query.difficulty,
            logging_type=query.logging_type,
            favorites_only=query.favorites_only,
            custom_only=query.custom_only,
        )
        async with self._uow:
            exercises, total = await self._uow.exercises.search(
                query.user_id, criteria, limit=limit, offset=offset
            )
        return ExercisePageDTO(
            items=[exercise_dto(e) for e in exercises],
            total=total,
            limit=limit,
            offset=offset,
        )


class GetExerciseUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, exercise_id: UUID) -> ExerciseDTO:
        async with self._uow:
            exercise = await self._uow.exercises.get(exercise_id, user_id)
        if exercise is None:
            raise NotFoundError("exercise", exercise_id)
        return exercise_dto(exercise)


class ListCatalogMetadataUseCase:
    """Muscle groups and equipment. Reference data, cached for a day (docs/04 §4)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def muscle_groups(self) -> list[MuscleGroupDTO]:
        async with self._uow:
            groups = await self._uow.catalog.list_muscle_groups()
            muscles = await self._uow.catalog.list_muscles()

        by_group: dict[UUID, list[MuscleRefDTO]] = {}
        for muscle in muscles:
            by_group.setdefault(muscle.muscle_group_id, []).append(
                MuscleRefDTO(
                    id=muscle.id,
                    slug=muscle.slug,
                    name=muscle.name,
                    group_slug=muscle.muscle_group_slug,
                )
            )
        return [
            MuscleGroupDTO(
                id=group.id,
                slug=group.slug,
                name=group.name,
                muscles=by_group.get(group.id, []),
            )
            for group in groups
        ]

    async def equipment(self) -> list[EquipmentDTO]:
        async with self._uow:
            items = await self._uow.catalog.list_equipment()
        return [
            EquipmentDTO(
                id=item.id,
                slug=item.slug,
                name=item.name,
                is_home_available=item.is_home_available,
            )
            for item in items
        ]

    async def categories(self) -> list[ExerciseCategoryDTO]:
        async with self._uow:
            items = await self._uow.catalog.list_categories()
        return [ExerciseCategoryDTO(id=c.id, slug=c.slug, name=c.name) for c in items]


class GetExerciseHistoryUseCase:
    """This user's history for one exercise: every set, plus the rollup."""

    DEFAULT_SESSIONS = 30

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, user_id: UUID, exercise_id: UUID, *, limit: int | None = None
    ) -> ExerciseHistoryDTO:
        async with self._uow:
            exercise = await self._uow.exercises.get(exercise_id, user_id)
            if exercise is None:
                raise NotFoundError("exercise", exercise_id)

            entries = await self._uow.sessions.exercise_history(
                user_id, exercise_id, limit=limit or self.DEFAULT_SESSIONS
            )
            stats = await self._uow.exercise_stats.get_many(user_id, [exercise_id])

        stat = stats.get(exercise_id)
        return ExerciseHistoryDTO(
            exercise_id=exercise_id,
            exercise_name=exercise.name,
            total_sessions=stat.total_sessions if stat else len(entries),
            total_sets=stat.total_sets if stat else sum(len(e.sets) for e in entries),
            total_volume_kg=stat.total_volume_kg if stat else Decimal("0"),
            best_est_1rm=stat.best_est_1rm if stat else None,
            last_performed_on=stat.last_performed_on if stat else None,
            sessions=[
                ExerciseHistorySessionDTO(
                    session_id=entry.session_id,
                    session_name=entry.session_name,
                    local_date=entry.local_date,
                    total_volume_kg=entry.total_volume_kg,
                    best_set_id=entry.best_set_id,
                    sets=[_set_history_dto(s) for s in entry.sets],
                )
                for entry in entries
            ],
        )


class GetExerciseRecordsUseCase:
    """Current records for an exercise, plus the chain of what they beat."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, exercise_id: UUID) -> list[PersonalRecordDTO]:
        async with self._uow:
            exercise = await self._uow.exercises.get(exercise_id, user_id)
            if exercise is None:
                raise NotFoundError("exercise", exercise_id)
            records = await self._uow.records.list_for_exercise(user_id, exercise_id)
        return [record_dto(r, exercise_name=exercise.name) for r in records]


class ListCurrentRecordsUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> list[PersonalRecordDTO]:
        async with self._uow:
            records = await self._uow.records.list_current(user_id)
            names = {
                e.id: e.name
                for e in await self._uow.exercises.get_many(
                    [r.exercise_id for r in records], user_id
                )
            }
        return [record_dto(r, exercise_name=names.get(r.exercise_id)) for r in records]


# ---------------------------------------------------------------- custom writes
@dataclass(frozen=True, slots=True)
class CustomExerciseCommand:
    user_id: UUID
    name: str
    category_slug: str
    logging_type: str = "weight_reps"
    difficulty: str = "intermediate"
    force_type: str | None = None
    mechanic: str | None = None
    is_unilateral: bool = False
    description: str | None = None
    primary_muscle_slugs: tuple[str, ...] = ()
    secondary_muscle_slugs: tuple[str, ...] = ()
    equipment_slugs: tuple[str, ...] = ()


class CreateCustomExerciseUseCase:
    """Let a user add a movement the catalog does not have.

    Custom exercises are never verified and never visible to anyone else — both
    guaranteed by CHECK constraints and the scoped read, not by this code alone.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: CustomExerciseCommand) -> ExerciseDTO:
        if not cmd.name.strip():
            raise ValidationError("An exercise needs a name.")

        async with self._uow:
            category = await self._uow.catalog.category_by_slug(cmd.category_slug)
            if category is None:
                raise ValidationError(
                    f"Unknown category '{cmd.category_slug}'.",
                    details=[
                        {
                            "field": "categorySlug",
                            "code": "unknown",
                            "message": "Pick one of the categories from /v1/exercises/meta.",
                        }
                    ],
                )

            _, existing_count = await self._uow.exercises.search(
                cmd.user_id, ExerciseFilter(custom_only=True), limit=1, offset=0
            )
            if existing_count >= MAX_CUSTOM_EXERCISES:
                raise ConflictError(
                    f"You have reached the limit of {MAX_CUSTOM_EXERCISES} custom exercises."
                )

            muscles = await self._resolve_muscles(cmd)
            equipment_ids = await self._resolve_equipment(cmd.equipment_slugs)

            exercise = Exercise.create_custom(
                owner_user_id=cmd.user_id,
                name=cmd.name,
                category_id=category.id,
                logging_type=LoggingType(cmd.logging_type),
                difficulty=Difficulty(cmd.difficulty),
                force_type=ForceType(cmd.force_type) if cmd.force_type else None,
                mechanic=Mechanic(cmd.mechanic) if cmd.mechanic else None,
                is_unilateral=cmd.is_unilateral,
                description=cmd.description,
                muscles=muscles,
                equipment_ids=equipment_ids,
            )
            await self._uow.exercises.add(exercise)
            await self._uow.commit()

            stored = await self._uow.exercises.get(exercise.id, cmd.user_id)

        logger.info("custom_exercise_created", user_id=str(cmd.user_id))
        return exercise_dto(stored or exercise)

    async def _resolve_muscles(self, cmd: CustomExerciseCommand) -> list[ExerciseMuscle]:
        slugs = list(cmd.primary_muscle_slugs) + list(cmd.secondary_muscle_slugs)
        if not slugs:
            return []
        resolved = await self._uow.catalog.muscle_ids_by_slug(slugs)
        unknown = sorted(set(slugs) - set(resolved))
        if unknown:
            raise ValidationError(f"Unknown muscles: {', '.join(unknown)}.")
        return [
            ExerciseMuscle(muscle_id=resolved[slug], role=MuscleRole.PRIMARY)
            for slug in cmd.primary_muscle_slugs
        ] + [
            ExerciseMuscle(muscle_id=resolved[slug], role=MuscleRole.SECONDARY)
            for slug in cmd.secondary_muscle_slugs
        ]

    async def _resolve_equipment(self, slugs: tuple[str, ...]) -> list[UUID]:
        if not slugs:
            return []
        resolved = await self._uow.catalog.equipment_ids_by_slug(list(slugs))
        unknown = sorted(set(slugs) - set(resolved))
        if unknown:
            raise ValidationError(f"Unknown equipment: {', '.join(unknown)}.")
        return [resolved[slug] for slug in slugs]


@dataclass(frozen=True, slots=True)
class UpdateCustomExerciseCommand:
    user_id: UUID
    exercise_id: UUID
    name: str | None = None
    difficulty: str | None = None
    force_type: str | None = None
    mechanic: str | None = None
    is_unilateral: bool | None = None
    description: str | None = None


class UpdateCustomExerciseUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: UpdateCustomExerciseCommand) -> ExerciseDTO:
        async with self._uow:
            exercise = await self._uow.exercises.get(cmd.exercise_id, cmd.user_id)
            if exercise is None:
                raise NotFoundError("exercise", cmd.exercise_id)
            if not exercise.is_editable_by(cmd.user_id):
                # The global catalog is changed through the admin surface, which has an
                # audit trail. This path is for a user's own exercises only.
                raise ForbiddenError("Only your own custom exercises can be edited.")

            if cmd.name is not None:
                exercise.name = cmd.name.strip()
            if cmd.difficulty is not None:
                exercise.difficulty = Difficulty(cmd.difficulty)
            if cmd.force_type is not None:
                exercise.force_type = ForceType(cmd.force_type)
            if cmd.mechanic is not None:
                exercise.mechanic = Mechanic(cmd.mechanic)
            if cmd.is_unilateral is not None:
                exercise.is_unilateral = cmd.is_unilateral
            if cmd.description is not None:
                exercise.description = cmd.description or None

            await self._uow.exercises.update(exercise)
            await self._uow.commit()
        return exercise_dto(exercise)


class DeleteCustomExerciseUseCase:
    """Soft delete. History that references the exercise stays intact and readable."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, exercise_id: UUID) -> None:
        async with self._uow:
            exercise = await self._uow.exercises.get(exercise_id, user_id)
            if exercise is None:
                raise NotFoundError("exercise", exercise_id)
            if not exercise.is_editable_by(user_id):
                raise ForbiddenError("Only your own custom exercises can be deleted.")
            await self._uow.exercises.soft_delete(exercise_id, user_id)
            await self._uow.commit()


class ToggleFavoriteExerciseUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def add(self, user_id: UUID, exercise_id: UUID) -> None:
        async with self._uow:
            if await self._uow.exercises.get(exercise_id, user_id) is None:
                raise NotFoundError("exercise", exercise_id)
            await self._uow.exercises.add_favorite(user_id, exercise_id)
            await self._uow.commit()

    async def remove(self, user_id: UUID, exercise_id: UUID) -> None:
        async with self._uow:
            await self._uow.exercises.remove_favorite(user_id, exercise_id)
            await self._uow.commit()
