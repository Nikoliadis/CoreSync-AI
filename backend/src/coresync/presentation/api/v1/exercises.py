"""/v1/exercises — the catalog, custom exercises, history and records."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from coresync.application.catalog.use_cases import (
    CreateCustomExerciseUseCase,
    CustomExerciseCommand,
    DeleteCustomExerciseUseCase,
    GetExerciseHistoryUseCase,
    GetExerciseRecordsUseCase,
    GetExerciseUseCase,
    ListCatalogMetadataUseCase,
    SearchExercisesQuery,
    SearchExercisesUseCase,
    ToggleFavoriteExerciseUseCase,
    UpdateCustomExerciseCommand,
    UpdateCustomExerciseUseCase,
)
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.common import ErrorResponse
from coresync.presentation.schemas.exercises import (
    CreateExerciseRequest,
    EquipmentResponse,
    ExerciseCategoryResponse,
    ExerciseHistoryResponse,
    ExercisePageResponse,
    ExerciseResponse,
    MuscleGroupResponse,
    PersonalRecordResponse,
    UpdateExerciseRequest,
)

router = APIRouter(prefix="/exercises", tags=["exercises"])

# The catalog changes rarely and is read on nearly every screen. Private, because the
# response includes the caller's own custom exercises and favourites.
_CATALOG_CACHE = "private, max-age=3600"
_META_CACHE = "public, max-age=86400"


@router.get(
    "",
    response_model=ExercisePageResponse,
    summary="Search and filter the exercise catalog",
    description=(
        "The global catalog plus this user's custom exercises. Filters combine with AND; "
        "muscle-group filtering matches primary movers only, so 'chest' does not return "
        "every pressing accessory that involves the chest as a stabiliser."
    ),
)
async def search_exercises(
    response: Response,
    user: deps.CurrentUser,
    use_case: Annotated[SearchExercisesUseCase, Depends(deps.search_exercises_use_case)],
    q: Annotated[str | None, Query(max_length=100, description="Fuzzy name search")] = None,
    muscle_group: Annotated[list[str] | None, Query()] = None,
    muscle: Annotated[list[str] | None, Query()] = None,
    equipment: Annotated[list[str] | None, Query()] = None,
    category: Annotated[list[str] | None, Query()] = None,
    difficulty: Annotated[str | None, Query(pattern="beginner|intermediate|advanced")] = None,
    logging_type: Annotated[str | None, Query()] = None,
    favorites_only: Annotated[bool, Query(alias="favoritesOnly")] = False,
    custom_only: Annotated[bool, Query(alias="customOnly")] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExercisePageResponse:
    page = await use_case.execute(
        SearchExercisesQuery(
            user_id=user.id,
            query=q,
            muscle_groups=tuple(muscle_group or ()),
            muscles=tuple(muscle or ()),
            equipment=tuple(equipment or ()),
            categories=tuple(category or ()),
            difficulty=difficulty,
            logging_type=logging_type,
            favorites_only=favorites_only,
            custom_only=custom_only,
            limit=limit,
            offset=offset,
        )
    )
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return ExercisePageResponse(
        items=[ExerciseResponse(**vars(e)) for e in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )


@router.get(
    "/meta/muscle-groups",
    response_model=list[MuscleGroupResponse],
    summary="Muscle groups and their muscles",
)
async def muscle_groups(
    response: Response,
    user: deps.CurrentUser,
    use_case: Annotated[ListCatalogMetadataUseCase, Depends(deps.catalog_metadata_use_case)],
) -> list[MuscleGroupResponse]:
    response.headers["Cache-Control"] = _META_CACHE
    return [MuscleGroupResponse(**vars(g)) for g in await use_case.muscle_groups()]


@router.get(
    "/meta/equipment", response_model=list[EquipmentResponse], summary="Equipment reference data"
)
async def equipment_list(
    response: Response,
    user: deps.CurrentUser,
    use_case: Annotated[ListCatalogMetadataUseCase, Depends(deps.catalog_metadata_use_case)],
) -> list[EquipmentResponse]:
    response.headers["Cache-Control"] = _META_CACHE
    return [EquipmentResponse(**vars(e)) for e in await use_case.equipment()]


@router.get(
    "/meta/categories",
    response_model=list[ExerciseCategoryResponse],
    summary="Exercise categories",
)
async def categories(
    response: Response,
    user: deps.CurrentUser,
    use_case: Annotated[ListCatalogMetadataUseCase, Depends(deps.catalog_metadata_use_case)],
) -> list[ExerciseCategoryResponse]:
    response.headers["Cache-Control"] = _META_CACHE
    return [ExerciseCategoryResponse(**vars(c)) for c in await use_case.categories()]


@router.post(
    "",
    response_model=ExerciseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Create a custom exercise",
    description=(
        "Custom exercises are private to their author and can never be marked verified — "
        "both enforced by CHECK constraints, not only by this endpoint."
    ),
)
async def create_exercise(
    body: CreateExerciseRequest,
    user: deps.CurrentUser,
    use_case: Annotated[CreateCustomExerciseUseCase, Depends(deps.create_exercise_use_case)],
) -> ExerciseResponse:
    exercise = await use_case.execute(
        CustomExerciseCommand(
            user_id=user.id,
            name=body.name,
            category_slug=body.category_slug,
            logging_type=body.logging_type,
            difficulty=body.difficulty,
            force_type=body.force_type,
            mechanic=body.mechanic,
            is_unilateral=body.is_unilateral,
            description=body.description,
            primary_muscle_slugs=tuple(body.primary_muscle_slugs),
            secondary_muscle_slugs=tuple(body.secondary_muscle_slugs),
            equipment_slugs=tuple(body.equipment_slugs),
        )
    )
    return ExerciseResponse(**vars(exercise))


@router.get(
    "/{exercise_id}",
    response_model=ExerciseResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Exercise detail",
)
async def get_exercise(
    exercise_id: UUID,
    response: Response,
    user: deps.CurrentUser,
    use_case: Annotated[GetExerciseUseCase, Depends(deps.get_exercise_use_case)],
) -> ExerciseResponse:
    exercise = await use_case.execute(user.id, exercise_id)
    response.headers["Cache-Control"] = _CATALOG_CACHE
    return ExerciseResponse(**vars(exercise))


@router.patch(
    "/{exercise_id}",
    response_model=ExerciseResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Update your own custom exercise",
)
async def update_exercise(
    exercise_id: UUID,
    body: UpdateExerciseRequest,
    user: deps.CurrentUser,
    use_case: Annotated[UpdateCustomExerciseUseCase, Depends(deps.update_exercise_use_case)],
) -> ExerciseResponse:
    exercise = await use_case.execute(
        UpdateCustomExerciseCommand(
            user_id=user.id,
            exercise_id=exercise_id,
            name=body.name,
            difficulty=body.difficulty,
            force_type=body.force_type,
            mechanic=body.mechanic,
            is_unilateral=body.is_unilateral,
            description=body.description,
        )
    )
    return ExerciseResponse(**vars(exercise))


@router.delete(
    "/{exercise_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Soft-delete your own custom exercise",
    description="History that references the exercise stays intact and readable.",
)
async def delete_exercise(
    exercise_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteCustomExerciseUseCase, Depends(deps.delete_exercise_use_case)],
) -> None:
    await use_case.execute(user.id, exercise_id)


@router.get(
    "/{exercise_id}/history",
    response_model=ExerciseHistoryResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Your history for one exercise",
)
async def exercise_history(
    exercise_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[GetExerciseHistoryUseCase, Depends(deps.exercise_history_use_case)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ExerciseHistoryResponse:
    history = await use_case.execute(user.id, exercise_id, limit=limit)
    return ExerciseHistoryResponse(**vars(history))


@router.get(
    "/{exercise_id}/records",
    response_model=list[PersonalRecordResponse],
    responses={404: {"model": ErrorResponse}},
    summary="Personal records for one exercise, with the progression chain",
)
async def exercise_records(
    exercise_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[GetExerciseRecordsUseCase, Depends(deps.exercise_records_use_case)],
) -> list[PersonalRecordResponse]:
    records = await use_case.execute(user.id, exercise_id)
    return [PersonalRecordResponse(**vars(r)) for r in records]


@router.post(
    "/{exercise_id}/favorite",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Add to favourites",
)
async def add_favorite(
    exercise_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[ToggleFavoriteExerciseUseCase, Depends(deps.favorite_exercise_use_case)],
) -> None:
    await use_case.add(user.id, exercise_id)


@router.delete(
    "/{exercise_id}/favorite",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove from favourites",
)
async def remove_favorite(
    exercise_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[ToggleFavoriteExerciseUseCase, Depends(deps.favorite_exercise_use_case)],
) -> None:
    await use_case.remove(user.id, exercise_id)
