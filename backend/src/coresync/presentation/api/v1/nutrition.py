"""/v1/nutrition — food search, the diary and water."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from coresync.application.nutrition.use_cases import (
    CreateCustomFoodUseCase,
    DeleteDiaryEntryUseCase,
    GetDiaryUseCase,
    LogFoodCommand,
    LogFoodUseCase,
    LogWaterUseCase,
    QuickAddCommand,
    SearchFoodsUseCase,
)
from coresync.core.errors import NotFoundError
from coresync.domain.nutrition.entities import Food, MealType
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.common import ErrorResponse
from coresync.presentation.schemas.nutrition import (
    CreateFoodRequest,
    DiaryEntryResponse,
    DiaryResponse,
    FoodResponse,
    FoodSearchResponse,
    FoodServingResponse,
    LogFoodRequest,
    LogWaterRequest,
    MacrosResponse,
    MealTotalsResponse,
    QuickAddRequest,
    WaterResponse,
)

router = APIRouter(prefix="/nutrition", tags=["nutrition"])


def _food_response(food: Food) -> FoodResponse:
    return FoodResponse(
        id=food.id,
        name=food.name,
        source=food.source.value,
        trust_tier=int(food.trust_tier),
        is_verified=food.is_verified,
        is_custom=food.is_custom,
        is_liquid=food.is_liquid,
        calories_per_100g=food.calories_per_100g,
        protein_per_100g=food.protein_per_100g,
        carbs_per_100g=food.carbs_per_100g,
        fat_per_100g=food.fat_per_100g,
        servings=[
            FoodServingResponse(id=s.id, label=s.label, grams=s.grams, is_default=s.is_default)
            for s in food.servings
        ],
    )


def _macros(macros: object) -> MacrosResponse:
    return MacrosResponse.model_validate(macros)


# ------------------------------------------------------------------------ foods
@router.get(
    "/foods",
    response_model=FoodSearchResponse,
    summary="Search foods",
    description=(
        "Ranked by trust tier before anything else — a wrong number is worse than an "
        "unfamiliar name. Your own foods and exact name matches outrank the tier "
        "ordering, and popularity breaks the remaining ties. Search is "
        "diacritic-insensitive, so 'γιαουρτι' finds 'Γιαούρτι'."
    ),
)
async def search_foods(
    user: deps.CurrentUser,
    use_case: Annotated[SearchFoodsUseCase, Depends(deps.search_foods_use_case)],
    q: Annotated[str, Query(max_length=120)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FoodSearchResponse:
    items, total = await use_case.execute(user.id, query=q, limit=limit, offset=offset)
    return FoodSearchResponse(items=[_food_response(f) for f in items], total=total)


@router.get(
    "/foods/recent",
    response_model=FoodSearchResponse,
    summary="What you log often",
    description="Derived from the diary rather than a separate table.",
)
async def recent_foods(
    user: deps.CurrentUser,
    use_case: Annotated[SearchFoodsUseCase, Depends(deps.search_foods_use_case)],
) -> FoodSearchResponse:
    items = await use_case.recent(user.id)
    return FoodSearchResponse(items=[_food_response(f) for f in items], total=len(items))


@router.get(
    "/foods/barcode/{barcode}",
    response_model=FoodResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Look up a scanned product",
    description=(
        "Checks the local catalogue only. A miss is a 404 — the client decides whether "
        "to offer an external lookup."
    ),
)
async def food_by_barcode(
    barcode: str,
    user: deps.CurrentUser,
    use_case: Annotated[SearchFoodsUseCase, Depends(deps.search_foods_use_case)],
) -> FoodResponse:
    food = await use_case.by_barcode(user.id, barcode)
    if food is None:
        raise NotFoundError("We don't have that product yet.")
    return _food_response(food)


@router.post(
    "/foods",
    response_model=FoodResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Create a custom food",
    description=(
        "Private to you and searchable only by you. Macros must reconcile with the "
        "stated calories — a misplaced decimal point is rejected with the number it "
        "should have been."
    ),
)
async def create_food(
    body: CreateFoodRequest,
    user: deps.CurrentUser,
    use_case: Annotated[CreateCustomFoodUseCase, Depends(deps.create_food_use_case)],
) -> FoodResponse:
    food = await use_case.execute(
        user.id,
        name=body.name,
        calories_per_100g=body.calories_per_100g,
        protein_per_100g=body.protein_per_100g,
        carbs_per_100g=body.carbs_per_100g,
        fat_per_100g=body.fat_per_100g,
        is_liquid=body.is_liquid,
        servings=[(s.label, s.grams) for s in body.servings],
    )
    return _food_response(food)


# ------------------------------------------------------------------------ diary
@router.get(
    "/diary",
    response_model=DiaryResponse,
    summary="A day's diary and totals",
    description=(
        "Targets are the ones in force on *that* day, not today's — they are versioned "
        "so 'was I in a deficit in March?' stays answerable."
    ),
)
async def get_diary(
    user: deps.CurrentUser,
    use_case: Annotated[GetDiaryUseCase, Depends(deps.get_diary_use_case)],
    on: Annotated[date | None, Query()] = None,
) -> DiaryResponse:
    day, totals, entries, targets = await use_case.execute(user.id, on=on)

    return DiaryResponse(
        local_date=day,
        totals=_macros(totals.macros),
        water_ml=totals.water_ml,
        by_meal=[
            MealTotalsResponse(
                meal_type=meal.meal_type.value, entries=meal.entries, macros=_macros(meal.macros)
            )
            for meal in totals.by_meal
        ],
        entries=[
            DiaryEntryResponse(
                id=entry.id,
                local_date=entry.local_date,
                meal_type=entry.meal_type.value,
                display_name=entry.display_name,
                quantity=entry.quantity,
                total_grams=entry.total_grams,
                macros=_macros(entry.macros),
                food_id=entry.food_id,
                recipe_id=entry.recipe_id,
                serving_id=entry.serving_id,
                logged_at=entry.logged_at,
            )
            for entry in entries
        ],
        targets=_macros(targets) if targets else None,
        remaining=_macros(totals.remaining(targets)) if targets else None,
    )


@router.post(
    "/diary",
    response_model=DiaryEntryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Log a food",
    description=(
        "Nutrition is snapshotted at the moment of logging. A later correction to the "
        "food never rewrites what you already ate."
    ),
)
async def log_food(
    body: LogFoodRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LogFoodUseCase, Depends(deps.log_food_use_case)],
) -> DiaryEntryResponse:
    entry = await use_case.execute(
        LogFoodCommand(
            user_id=user.id,
            food_id=body.food_id,
            meal_type=MealType(body.meal_type),
            quantity=body.quantity,
            serving_id=body.serving_id,
            local_date=body.local_date,
        )
    )
    return DiaryEntryResponse(
        id=entry.id,
        local_date=entry.local_date,
        meal_type=entry.meal_type.value,
        display_name=entry.display_name,
        quantity=entry.quantity,
        total_grams=entry.total_grams,
        macros=_macros(entry.macros),
        food_id=entry.food_id,
        serving_id=entry.serving_id,
        logged_at=entry.logged_at,
    )


@router.post(
    "/diary/quick-add",
    response_model=DiaryEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log calories without a food",
)
async def quick_add(
    body: QuickAddRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LogFoodUseCase, Depends(deps.log_food_use_case)],
) -> DiaryEntryResponse:
    entry = await use_case.quick_add(
        QuickAddCommand(
            user_id=user.id,
            meal_type=MealType(body.meal_type),
            calories=body.calories,
            protein_g=body.protein_g,
            carbs_g=body.carbs_g,
            fat_g=body.fat_g,
            label=body.label,
            local_date=body.local_date,
        )
    )
    return DiaryEntryResponse(
        id=entry.id,
        local_date=entry.local_date,
        meal_type=entry.meal_type.value,
        display_name=entry.display_name,
        quantity=entry.quantity,
        total_grams=entry.total_grams,
        macros=_macros(entry.macros),
        logged_at=entry.logged_at,
    )


@router.delete(
    "/diary/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Remove a diary entry",
    description="Soft delete — history is corrected by replacement, never by removal.",
)
async def delete_entry(
    entry_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteDiaryEntryUseCase, Depends(deps.delete_diary_entry_use_case)],
) -> None:
    await use_case.execute(entry_id, user.id)


# ------------------------------------------------------------------------ water
@router.get("/water", response_model=WaterResponse, summary="Today's hydration total")
async def get_water(
    user: deps.CurrentUser,
    use_case: Annotated[LogWaterUseCase, Depends(deps.log_water_use_case)],
    on: Annotated[date | None, Query()] = None,
) -> WaterResponse:
    day, total = await use_case.total_for_day(user.id, on)
    return WaterResponse(local_date=day, total_ml=total)


@router.post(
    "/water",
    response_model=WaterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Log water",
    description="Increments through the day; the timestamps drive reminder timing.",
)
async def log_water(
    body: LogWaterRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LogWaterUseCase, Depends(deps.log_water_use_case)],
) -> WaterResponse:
    day, total = await use_case.execute(user.id, millilitres=body.millilitres, on=body.local_date)
    return WaterResponse(local_date=day, total_ml=total)
