"""Routine use cases: the plan side of the workout domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.workout.dto import (
    RoutineDTO,
    RoutineExerciseDTO,
    RoutineSetDTO,
)
from coresync.core.errors import ConflictError, NotFoundError, ValidationError
from coresync.core.logging import get_logger
from coresync.domain.workout.entities import (
    Routine,
    RoutineExercise,
    RoutineSet,
    SetType,
)
from coresync.domain.workout.repositories import StaleVersionError

logger = get_logger(__name__)

MAX_ROUTINES = 200
MAX_EXERCISES_PER_ROUTINE = 50
MAX_SETS_PER_EXERCISE = 30


# ---------------------------------------------------------------------- mapping
def routine_dto(routine: Routine, names: dict[UUID, str] | None = None) -> RoutineDTO:
    lookup = names or {}
    return RoutineDTO(
        id=routine.id,
        name=routine.name,
        folder=routine.folder,
        notes=routine.notes,
        is_template=routine.is_template,
        estimated_minutes=routine.estimated_minutes,
        version=routine.version,
        last_performed_at=routine.last_performed_at,
        total_sets=routine.total_sets,
        exercises=[
            RoutineExerciseDTO(
                id=entry.id,
                exercise_id=entry.exercise_id,
                exercise_name=lookup.get(entry.exercise_id),
                position=entry.position,
                superset_group=entry.superset_group,
                rest_seconds=entry.rest_seconds,
                notes=entry.notes,
                sets=[
                    RoutineSetDTO(
                        id=s.id,
                        set_number=s.set_number,
                        set_type=s.set_type.value,
                        target_reps_min=s.target_reps_min,
                        target_reps_max=s.target_reps_max,
                        target_weight_kg=s.target_weight_kg,
                        target_duration_seconds=s.target_duration_seconds,
                        target_distance_m=s.target_distance_m,
                        target_rpe=s.target_rpe,
                    )
                    for s in entry.sets
                ],
            )
            for entry in routine.exercises
        ],
    )


# ---------------------------------------------------------------------- commands
@dataclass(frozen=True, slots=True)
class RoutineSetInput:
    set_type: str = "normal"
    target_reps_min: int | None = None
    target_reps_max: int | None = None
    target_weight_kg: Decimal | None = None
    target_duration_seconds: int | None = None
    target_distance_m: Decimal | None = None
    target_rpe: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RoutineExerciseInput:
    exercise_id: UUID
    superset_group: UUID | None = None
    rest_seconds: int | None = None
    notes: str | None = None
    sets: list[RoutineSetInput] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CreateRoutineCommand:
    user_id: UUID
    name: str
    folder: str | None = None
    notes: str | None = None
    estimated_minutes: int | None = None
    exercises: list[RoutineExerciseInput] = field(default_factory=list)


class _RoutineBuilder:
    """Shared validation for create and replace-exercises.

    Both entry points accept the same nested payload, and both must reject an unknown or
    inaccessible exercise id — which is where a user could otherwise probe for another
    user's custom exercises.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def build(
        self, user_id: UUID, inputs: list[RoutineExerciseInput]
    ) -> tuple[list[RoutineExercise], dict[UUID, str]]:
        if len(inputs) > MAX_EXERCISES_PER_ROUTINE:
            raise ValidationError(
                f"A routine can hold at most {MAX_EXERCISES_PER_ROUTINE} exercises."
            )

        exercise_ids = [entry.exercise_id for entry in inputs]
        found = await self._uow.exercises.get_many(exercise_ids, user_id)
        names = {e.id: e.name for e in found}
        missing = sorted({str(i) for i in exercise_ids} - {str(i) for i in names})
        if missing:
            raise ValidationError(
                "Unknown exercise in routine.",
                details=[
                    {"field": "exercises", "code": "unknown_exercise", "message": exercise_id}
                    for exercise_id in missing
                ],
            )

        exercises: list[RoutineExercise] = []
        for position, entry in enumerate(inputs, start=1):
            if len(entry.sets) > MAX_SETS_PER_EXERCISE:
                raise ValidationError(
                    f"An exercise can prescribe at most {MAX_SETS_PER_EXERCISE} sets."
                )
            sets = [
                RoutineSet.create(
                    set_number=number,
                    set_type=SetType(prescribed.set_type),
                    target_reps_min=prescribed.target_reps_min,
                    target_reps_max=prescribed.target_reps_max,
                    target_weight_kg=prescribed.target_weight_kg,
                    target_duration_seconds=prescribed.target_duration_seconds,
                    target_distance_m=prescribed.target_distance_m,
                    target_rpe=prescribed.target_rpe,
                )
                for number, prescribed in enumerate(entry.sets, start=1)
            ]
            exercises.append(
                RoutineExercise.create(
                    exercise_id=entry.exercise_id,
                    position=position,
                    superset_group=entry.superset_group,
                    rest_seconds=entry.rest_seconds,
                    notes=entry.notes,
                    sets=sets,
                )
            )
        return exercises, names


class CreateRoutineUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: CreateRoutineCommand) -> RoutineDTO:
        async with self._uow:
            existing = await self._uow.routines.list_for_user(cmd.user_id)
            if len(existing) >= MAX_ROUTINES:
                raise ConflictError(f"You have reached the limit of {MAX_ROUTINES} routines.")

            exercises, names = await _RoutineBuilder(self._uow).build(cmd.user_id, cmd.exercises)
            try:
                routine = Routine.create(
                    user_id=cmd.user_id,
                    name=cmd.name,
                    folder=cmd.folder,
                    notes=cmd.notes,
                    estimated_minutes=cmd.estimated_minutes,
                    exercises=exercises,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

            await self._uow.routines.add(routine)
            await self._uow.commit()

        logger.info("routine_created", user_id=str(cmd.user_id))
        return routine_dto(routine, names)


class ListRoutinesUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> list[RoutineDTO]:
        async with self._uow:
            routines = await self._uow.routines.list_for_user(user_id)
            names = await _exercise_names(self._uow, user_id, routines)
        return [routine_dto(r, names) for r in routines]


class GetRoutineUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, routine_id: UUID) -> RoutineDTO:
        async with self._uow:
            routine = await self._uow.routines.get(routine_id, user_id)
            if routine is None:
                raise NotFoundError("routine", routine_id)
            names = await _exercise_names(self._uow, user_id, [routine])
        return routine_dto(routine, names)


@dataclass(frozen=True, slots=True)
class UpdateRoutineCommand:
    user_id: UUID
    routine_id: UUID
    name: str | None = None
    folder: str | None = None
    notes: str | None = None
    estimated_minutes: int | None = None
    expected_version: int | None = None


class UpdateRoutineUseCase:
    """Metadata only. The exercise list is replaced wholesale by its own endpoint."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: UpdateRoutineCommand) -> RoutineDTO:
        async with self._uow:
            routine = await self._uow.routines.get(cmd.routine_id, cmd.user_id)
            if routine is None:
                raise NotFoundError("routine", cmd.routine_id)

            if cmd.name is not None:
                routine.name = cmd.name.strip()
            if cmd.folder is not None:
                routine.folder = cmd.folder.strip() or None
            if cmd.notes is not None:
                routine.notes = cmd.notes or None
            if cmd.estimated_minutes is not None:
                routine.estimated_minutes = cmd.estimated_minutes

            try:
                await self._uow.routines.update(routine, expected_version=cmd.expected_version)
            except StaleVersionError as exc:
                raise ConflictError(
                    "This routine was changed elsewhere. Reload and try again."
                ) from exc

            names = await _exercise_names(self._uow, cmd.user_id, [routine])
            await self._uow.commit()
        return routine_dto(routine, names)


@dataclass(frozen=True, slots=True)
class ReplaceRoutineExercisesCommand:
    user_id: UUID
    routine_id: UUID
    exercises: list[RoutineExerciseInput]


class ReplaceRoutineExercisesUseCase:
    """Reordering and editing as one atomic write.

    N separate PATCHes would leave the routine briefly inconsistent, and a dropped
    request would strand it there (docs/04 §2.4).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, cmd: ReplaceRoutineExercisesCommand) -> RoutineDTO:
        async with self._uow:
            routine = await self._uow.routines.get(cmd.routine_id, cmd.user_id)
            if routine is None:
                raise NotFoundError("routine", cmd.routine_id)

            exercises, names = await _RoutineBuilder(self._uow).build(cmd.user_id, cmd.exercises)
            routine.replace_exercises(exercises)
            await self._uow.routines.replace_exercises(routine)
            await self._uow.commit()
        return routine_dto(routine, names)


class DuplicateRoutineUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, user_id: UUID, routine_id: UUID, *, name: str | None = None
    ) -> RoutineDTO:
        async with self._uow:
            source = await self._uow.routines.get(routine_id, user_id)
            if source is None:
                raise NotFoundError("routine", routine_id)
            copy = source.duplicate(user_id=user_id, name=name)
            await self._uow.routines.add(copy)
            names = await _exercise_names(self._uow, user_id, [copy])
            await self._uow.commit()
        return routine_dto(copy, names)


class DeleteRoutineUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, routine_id: UUID) -> None:
        async with self._uow:
            routine = await self._uow.routines.get(routine_id, user_id)
            if routine is None:
                raise NotFoundError("routine", routine_id)
            # Sessions keep their history: the FK is SET NULL, so deleting a plan never
            # deletes the record of having trained it.
            await self._uow.routines.delete(routine_id, user_id)
            await self._uow.commit()


class ListTemplatesUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> list[RoutineDTO]:
        async with self._uow:
            templates = await self._uow.routines.list_templates()
            names = await _exercise_names(self._uow, user_id, templates)
        return [routine_dto(t, names) for t in templates]


class AdoptTemplateUseCase:
    """Copy a curated template into the user's own routines.

    A copy, never a reference — so editing the adopted routine cannot change the
    template, and improving the template cannot silently rewrite someone's plan.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, template_id: UUID) -> RoutineDTO:
        async with self._uow:
            template = await self._uow.routines.get_template(template_id)
            if template is None:
                raise NotFoundError("template", template_id)
            adopted = template.duplicate(user_id=user_id, name=template.name)
            await self._uow.routines.add(adopted)
            names = await _exercise_names(self._uow, user_id, [adopted])
            await self._uow.commit()

        logger.info("template_adopted", user_id=str(user_id), template_id=str(template_id))
        return routine_dto(adopted, names)


async def _exercise_names(
    uow: UnitOfWork, user_id: UUID, routines: list[Routine]
) -> dict[UUID, str]:
    """One lookup for every exercise across every routine, rather than one per routine."""
    ids = list({entry.exercise_id for routine in routines for entry in routine.exercises})
    if not ids:
        return {}
    return {e.id: e.name for e in await uow.exercises.get_many(ids, user_id)}
