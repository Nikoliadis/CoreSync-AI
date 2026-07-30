"""/v1/workouts/routines — the plan side of the workout domain."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from coresync.application.workout.routines import (
    AdoptTemplateUseCase,
    CreateRoutineCommand,
    CreateRoutineUseCase,
    DeleteRoutineUseCase,
    DuplicateRoutineUseCase,
    GetRoutineUseCase,
    ListRoutinesUseCase,
    ListTemplatesUseCase,
    ReplaceRoutineExercisesCommand,
    ReplaceRoutineExercisesUseCase,
    RoutineExerciseInput,
    RoutineSetInput,
    UpdateRoutineCommand,
    UpdateRoutineUseCase,
)
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.common import ErrorResponse
from coresync.presentation.schemas.workouts import (
    CreateRoutineRequest,
    DuplicateRoutineRequest,
    ReplaceRoutineExercisesRequest,
    RoutineExerciseRequest,
    RoutineResponse,
    UpdateRoutineRequest,
)

router = APIRouter(prefix="/workouts/routines", tags=["routines"])


def _to_inputs(exercises: list[RoutineExerciseRequest]) -> list[RoutineExerciseInput]:
    return [
        RoutineExerciseInput(
            exercise_id=entry.exercise_id,
            superset_group=entry.superset_group,
            rest_seconds=entry.rest_seconds,
            notes=entry.notes,
            sets=[
                RoutineSetInput(
                    set_type=s.set_type,
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
        for entry in exercises
    ]


def _response(routine) -> RoutineResponse:
    return RoutineResponse.model_validate(routine)


@router.get("", response_model=list[RoutineResponse], summary="Your routines, grouped by folder")
async def list_routines(
    user: deps.CurrentUser,
    use_case: Annotated[ListRoutinesUseCase, Depends(deps.list_routines_use_case)],
) -> list[RoutineResponse]:
    return [_response(r) for r in await use_case.execute(user.id)]


@router.post(
    "",
    response_model=RoutineResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Create a routine with its exercises and prescribed sets",
    description="One nested payload rather than N calls, so a routine is never half-created.",
)
async def create_routine(
    body: CreateRoutineRequest,
    user: deps.CurrentUser,
    use_case: Annotated[CreateRoutineUseCase, Depends(deps.create_routine_use_case)],
) -> RoutineResponse:
    routine = await use_case.execute(
        CreateRoutineCommand(
            user_id=user.id,
            name=body.name,
            folder=body.folder,
            notes=body.notes,
            estimated_minutes=body.estimated_minutes,
            exercises=_to_inputs(body.exercises),
        )
    )
    return _response(routine)


@router.get(
    "/templates",
    response_model=list[RoutineResponse],
    summary="Curated starter templates",
)
async def list_templates(
    user: deps.CurrentUser,
    use_case: Annotated[ListTemplatesUseCase, Depends(deps.list_templates_use_case)],
) -> list[RoutineResponse]:
    return [_response(t) for t in await use_case.execute(user.id)]


@router.post(
    "/templates/{template_id}/adopt",
    response_model=RoutineResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}},
    summary="Copy a template into your routines",
    description=(
        "A copy, never a reference: editing your adopted routine cannot change the "
        "template, and improving the template cannot rewrite your plan."
    ),
)
async def adopt_template(
    template_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[AdoptTemplateUseCase, Depends(deps.adopt_template_use_case)],
) -> RoutineResponse:
    return _response(await use_case.execute(user.id, template_id))


@router.get(
    "/{routine_id}",
    response_model=RoutineResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Full routine",
)
async def get_routine(
    routine_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[GetRoutineUseCase, Depends(deps.get_routine_use_case)],
) -> RoutineResponse:
    return _response(await use_case.execute(user.id, routine_id))


@router.patch(
    "/{routine_id}",
    response_model=RoutineResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Update routine metadata",
    description=(
        "Send `version` to opt into optimistic locking: a conflicting edit returns 409 "
        "rather than silently overwriting someone else's change."
    ),
)
async def update_routine(
    routine_id: UUID,
    body: UpdateRoutineRequest,
    user: deps.CurrentUser,
    use_case: Annotated[UpdateRoutineUseCase, Depends(deps.update_routine_use_case)],
) -> RoutineResponse:
    routine = await use_case.execute(
        UpdateRoutineCommand(
            user_id=user.id,
            routine_id=routine_id,
            name=body.name,
            folder=body.folder,
            notes=body.notes,
            estimated_minutes=body.estimated_minutes,
            expected_version=body.version,
        )
    )
    return _response(routine)


@router.put(
    "/{routine_id}/exercises",
    response_model=RoutineResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Replace the whole exercise list",
    description=(
        "Reordering and editing as one atomic write. N separate PATCHes would leave the "
        "routine briefly inconsistent, and a dropped request would strand it there."
    ),
)
async def replace_exercises(
    routine_id: UUID,
    body: ReplaceRoutineExercisesRequest,
    user: deps.CurrentUser,
    use_case: Annotated[
        ReplaceRoutineExercisesUseCase, Depends(deps.replace_routine_exercises_use_case)
    ],
) -> RoutineResponse:
    routine = await use_case.execute(
        ReplaceRoutineExercisesCommand(
            user_id=user.id, routine_id=routine_id, exercises=_to_inputs(body.exercises)
        )
    )
    return _response(routine)


@router.post(
    "/{routine_id}/duplicate",
    response_model=RoutineResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}},
    summary="Duplicate a routine",
)
async def duplicate_routine(
    routine_id: UUID,
    body: DuplicateRoutineRequest,
    user: deps.CurrentUser,
    use_case: Annotated[DuplicateRoutineUseCase, Depends(deps.duplicate_routine_use_case)],
) -> RoutineResponse:
    return _response(await use_case.execute(user.id, routine_id, name=body.name))


@router.delete(
    "/{routine_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Delete a routine",
    description="Workout history survives: the session foreign key is SET NULL.",
)
async def delete_routine(
    routine_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteRoutineUseCase, Depends(deps.delete_routine_use_case)],
) -> None:
    await use_case.execute(user.id, routine_id)
