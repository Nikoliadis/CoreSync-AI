"""/v1/nutrition — food search, the diary and water."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from coresync.application.nutrition.moderation import SubmitFoodUseCase
from coresync.application.nutrition.recipes import (
    DeleteRecipeUseCase,
    GetRecipeUseCase,
    IngredientInput,
    ListRecipesUseCase,
    LogRecipeCommand,
    LogRecipeUseCase,
    RecipeView,
    SaveRecipeUseCase,
)
from coresync.application.nutrition.summaries import (
    GetNutritionHistoryUseCase,
    GetNutritionStreakUseCase,
)
from coresync.application.nutrition.use_cases import (
    CopyDayUseCase,
    CreateCustomFoodUseCase,
    DeleteCustomFoodUseCase,
    DeleteDiaryEntryUseCase,
    EditCustomFoodUseCase,
    EditDiaryEntryUseCase,
    FavouriteFoodsUseCase,
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
    CopyDayRequest,
    CopyDayResponse,
    CreateFoodRequest,
    DailySummaryResponse,
    DiaryEntryResponse,
    DiaryResponse,
    EditDiaryEntryRequest,
    FoodDetailResponse,
    FoodResponse,
    FoodSearchResponse,
    FoodServingResponse,
    FoodSubmissionResponse,
    LogFoodRequest,
    LogRecipeRequest,
    LogWaterRequest,
    MacrosResponse,
    MealTotalsResponse,
    NutrientResponse,
    NutritionHistoryResponse,
    NutritionStreakResponse,
    QuickAddRequest,
    RecipeIngredientResponse,
    RecipeListResponse,
    RecipeResponse,
    SaveRecipeRequest,
    SubmitFoodRequest,
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
        alcohol_per_100g=food.alcohol_per_100g,
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
        alcohol_per_100g=body.alcohol_per_100g,
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
            alcohol_g=body.alcohol_g,
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


@router.patch(
    "/diary/{entry_id}",
    response_model=DiaryEntryResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Correct a diary entry",
    description=(
        "Every field is optional — send only what changed. Changing the amount "
        "re-derives the macros from the food rather than scaling the stored numbers, so "
        "repeated corrections do not drift on rounding."
    ),
)
async def edit_entry(
    entry_id: UUID,
    body: EditDiaryEntryRequest,
    user: deps.CurrentUser,
    use_case: Annotated[EditDiaryEntryUseCase, Depends(deps.edit_diary_entry_use_case)],
) -> DiaryEntryResponse:
    entry = await use_case.execute(
        entry_id,
        user.id,
        quantity=body.quantity,
        meal_type=MealType(body.meal_type) if body.meal_type else None,
        serving_id=body.serving_id,
        local_date=body.local_date,
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
        recipe_id=entry.recipe_id,
        serving_id=entry.serving_id,
        logged_at=entry.logged_at,
    )


@router.post(
    "/diary/copy",
    response_model=CopyDayResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Copy a day, or one meal, onto another day",
    description=(
        "Snapshots are copied verbatim rather than re-derived. What was eaten on Tuesday "
        "is a fact about Tuesday, and a copy that disagreed with its source would be "
        "worse than no copy at all."
    ),
)
async def copy_day(
    body: CopyDayRequest,
    user: deps.CurrentUser,
    use_case: Annotated[CopyDayUseCase, Depends(deps.copy_day_use_case)],
) -> CopyDayResponse:
    copies = await use_case.execute(
        user.id,
        source=body.source_date,
        target=body.target_date,
        meal_type=MealType(body.meal_type) if body.meal_type else None,
    )
    return CopyDayResponse(copied=len(copies), target_date=body.target_date)


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


# ------------------------------------------------------------------- favourites
@router.get(
    "/foods/favourites",
    response_model=FoodSearchResponse,
    summary="Foods you starred",
    description="Ranked directly below your own foods in search, above trust tier.",
)
async def list_favourites(
    user: deps.CurrentUser,
    use_case: Annotated[FavouriteFoodsUseCase, Depends(deps.favourite_foods_use_case)],
) -> FoodSearchResponse:
    items = await use_case.list(user.id)
    return FoodSearchResponse(items=[_food_response(f) for f in items], total=len(items))


@router.put(
    "/foods/{food_id}/favourite",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Star a food",
    description="Idempotent — starring something already starred is not an error.",
)
async def add_favourite(
    food_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[FavouriteFoodsUseCase, Depends(deps.favourite_foods_use_case)],
) -> None:
    await use_case.add(user.id, food_id)


@router.delete(
    "/foods/{food_id}/favourite",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unstar a food",
)
async def remove_favourite(
    food_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[FavouriteFoodsUseCase, Depends(deps.favourite_foods_use_case)],
) -> None:
    await use_case.remove(user.id, food_id)


@router.get(
    "/foods/{food_id}",
    response_model=FoodDetailResponse,
    responses={404: {"model": ErrorResponse}},
    summary="One food, with its full nutrient breakdown",
    description=(
        "Kept apart from search: returning every nutrient for twenty-five search results "
        "would be an order of magnitude more bytes for data nobody is looking at yet. "
        "The breakdown is only as complete as the source — most community rows carry a "
        "handful of nutrients, not all twenty-nine."
    ),
)
async def food_detail(
    food_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[SearchFoodsUseCase, Depends(deps.search_foods_use_case)],
) -> FoodDetailResponse:
    food, nutrients = await use_case.detail(user.id, food_id)
    return FoodDetailResponse(
        food=_food_response(food),
        nutrients=[
            NutrientResponse(
                code=n.code, name=n.name, unit=n.unit, amount_per_100g=n.amount_per_100g
            )
            for n in nutrients
        ],
    )


@router.put(
    "/foods/{food_id}",
    response_model=FoodResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Correct one of your own foods",
    description=(
        "Your own foods only. Meals already logged against it keep the numbers they were "
        "logged with — correcting a food never rewrites history."
    ),
)
async def update_food(
    food_id: UUID,
    body: CreateFoodRequest,
    user: deps.CurrentUser,
    use_case: Annotated[EditCustomFoodUseCase, Depends(deps.edit_food_use_case)],
) -> FoodResponse:
    food = await use_case.execute(
        food_id,
        user.id,
        name=body.name,
        calories_per_100g=body.calories_per_100g,
        protein_per_100g=body.protein_per_100g,
        carbs_per_100g=body.carbs_per_100g,
        fat_per_100g=body.fat_per_100g,
        alcohol_per_100g=body.alcohol_per_100g,
        is_liquid=body.is_liquid,
        servings=[(s.label, s.grams) for s in body.servings],
    )
    return _food_response(food)


@router.delete(
    "/foods/{food_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Delete one of your own foods",
    description="Soft delete, so recipes and diary entries that reference it stay intact.",
)
async def delete_food(
    food_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteCustomFoodUseCase, Depends(deps.delete_food_use_case)],
) -> None:
    await use_case.execute(food_id, user.id)


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


# ---------------------------------------------------------------------- recipes
def _recipe_response(view: RecipeView) -> RecipeResponse:
    return RecipeResponse(
        id=view.recipe.id,
        name=view.recipe.name,
        servings_count=view.recipe.servings_count,
        notes=view.recipe.notes,
        ingredients=[
            RecipeIngredientResponse(
                id=ingredient.id,
                food_id=ingredient.food_id,
                # Resolved from the loaded food rather than the stored label, so a
                # renamed food shows its current name here. A recipe is a definition:
                # it is meant to track the catalogue.
                food_name=(
                    food.name
                    if (food := view.foods.get(ingredient.food_id)) is not None
                    else ingredient.display_name or "Unknown ingredient"
                ),
                grams=ingredient.grams,
            )
            for ingredient in view.recipe.ingredients
        ],
        total=_macros(view.total),
        per_serving=_macros(view.per_serving),
        has_missing_ingredients=view.has_missing_ingredients,
    )


@router.get(
    "/recipes",
    response_model=RecipeListResponse,
    summary="Your recipes",
    description=(
        "Totals are computed on read from the current ingredient macros, never stored. "
        "Correcting a food corrects every recipe that uses it."
    ),
)
async def list_recipes(
    user: deps.CurrentUser,
    use_case: Annotated[ListRecipesUseCase, Depends(deps.list_recipes_use_case)],
) -> RecipeListResponse:
    views = await use_case.execute(user.id)
    return RecipeListResponse(items=[_recipe_response(view) for view in views])


@router.get(
    "/recipes/{recipe_id}",
    response_model=RecipeResponse,
    responses={404: {"model": ErrorResponse}},
    summary="One recipe with its ingredients",
)
async def get_recipe(
    recipe_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[GetRecipeUseCase, Depends(deps.get_recipe_use_case)],
) -> RecipeResponse:
    return _recipe_response(await use_case.execute(recipe_id, user.id))


@router.post(
    "/recipes",
    response_model=RecipeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Create a recipe",
)
async def create_recipe(
    body: SaveRecipeRequest,
    user: deps.CurrentUser,
    use_case: Annotated[SaveRecipeUseCase, Depends(deps.save_recipe_use_case)],
) -> RecipeResponse:
    view = await use_case.create(
        user.id,
        name=body.name,
        servings_count=body.servings_count,
        notes=body.notes,
        ingredients=[IngredientInput(food_id=i.food_id, grams=i.grams) for i in body.ingredients],
    )
    return _recipe_response(view)


@router.put(
    "/recipes/{recipe_id}",
    response_model=RecipeResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Replace a recipe",
    description=(
        "PUT rather than PATCH: the ingredient list is sent whole. Editing a recipe is a "
        "session of several changes, and reconciling them client-side is the least "
        "reliable place for that logic."
    ),
)
async def update_recipe(
    recipe_id: UUID,
    body: SaveRecipeRequest,
    user: deps.CurrentUser,
    use_case: Annotated[SaveRecipeUseCase, Depends(deps.save_recipe_use_case)],
) -> RecipeResponse:
    view = await use_case.update(
        recipe_id,
        user.id,
        name=body.name,
        servings_count=body.servings_count,
        notes=body.notes,
        ingredients=[IngredientInput(food_id=i.food_id, grams=i.grams) for i in body.ingredients],
    )
    return _recipe_response(view)


@router.delete(
    "/recipes/{recipe_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Delete a recipe",
    description=(
        "Soft delete. Diary entries logged from it keep their snapshotted numbers and "
        "are untouched."
    ),
)
async def delete_recipe(
    recipe_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteRecipeUseCase, Depends(deps.delete_recipe_use_case)],
) -> None:
    await use_case.execute(recipe_id, user.id)


@router.post(
    "/recipes/{recipe_id}/log",
    response_model=DiaryEntryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Log servings of a recipe",
    description=(
        "The per-serving macros are resolved now and snapshotted into the entry, exactly "
        "as a food is. Editing the recipe afterwards never rewrites what you ate."
    ),
)
async def log_recipe(
    recipe_id: UUID,
    body: LogRecipeRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LogRecipeUseCase, Depends(deps.log_recipe_use_case)],
) -> DiaryEntryResponse:
    entry = await use_case.execute(
        LogRecipeCommand(
            user_id=user.id,
            recipe_id=recipe_id,
            meal_type=MealType(body.meal_type),
            servings=body.servings,
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
        recipe_id=entry.recipe_id,
        logged_at=entry.logged_at,
    )


# ------------------------------------------------------------------- summaries
@router.get(
    "/history",
    response_model=NutritionHistoryResponse,
    summary="Daily totals over a range",
    description=(
        "Read from pre-computed daily summaries rather than re-aggregating raw entries, "
        "so a thirty-day chart is one query. Days with nothing logged are absent rather "
        "than zero — the client can tell 'ate nothing' from 'logged nothing'."
    ),
)
async def nutrition_history(
    user: deps.CurrentUser,
    use_case: Annotated[GetNutritionHistoryUseCase, Depends(deps.nutrition_history_use_case)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> NutritionHistoryResponse:
    summaries = await use_case.execute(user.id, days=days)
    return NutritionHistoryResponse(
        items=[
            DailySummaryResponse(
                local_date=s.local_date,
                calories=s.calories,
                protein_g=s.protein_g,
                carbs_g=s.carbs_g,
                fat_g=s.fat_g,
                alcohol_g=s.alcohol_g,
                water_ml=s.water_ml,
                entry_count=s.entry_count,
                target_calories=s.target_calories,
                target_protein_g=s.target_protein_g,
            )
            for s in summaries
        ]
    )


@router.get(
    "/streak",
    response_model=NutritionStreakResponse,
    summary="Consecutive days logged",
    description=(
        "A day counts if anything was logged on it, regardless of calories — a fasting "
        "day must not break a streak the person believes they kept. Today not being "
        "logged yet does not break it either; yesterday not being logged does."
    ),
)
async def nutrition_streak_endpoint(
    user: deps.CurrentUser,
    use_case: Annotated[GetNutritionStreakUseCase, Depends(deps.nutrition_streak_use_case)],
) -> NutritionStreakResponse:
    streak = await use_case.execute(user.id)
    return NutritionStreakResponse(
        current=streak.current, longest=streak.longest, last_date=streak.last_date
    )


@router.post(
    "/foods/{food_id}/submit",
    response_model=FoodSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Offer one of your foods to the shared catalogue",
    description=(
        "Puts it in a review queue. Nothing reaches the shared catalogue without a "
        "person checking the numbers first — food data quality is the risk this phase "
        "is built around. Submitting twice is not an error; the first request stands."
    ),
)
async def submit_food(
    food_id: UUID,
    body: SubmitFoodRequest,
    user: deps.CurrentUser,
    use_case: Annotated[SubmitFoodUseCase, Depends(deps.submit_food_use_case)],
) -> FoodSubmissionResponse:
    submission = await use_case.execute(food_id, user.id, note=body.note)
    return FoodSubmissionResponse(
        id=submission.id,
        food_id=submission.food_id,
        status=submission.status.value,
        note=submission.note,
        created_at=submission.created_at,
        reviewed_at=submission.reviewed_at,
    )
