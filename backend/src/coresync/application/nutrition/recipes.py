"""Recipe use cases.

A recipe is a *definition* and a diary entry is a *record*, which is why these read so
differently from the food ones: a recipe holds references to its ingredients and is
totalled on every read, so correcting a food's macros silently corrects every recipe
that uses it. Logging one snapshots the result, and from then on nothing changes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError, ValidationError
from coresync.core.ids import uuid7
from coresync.domain.nutrition.entities import (
    DiaryEntry,
    Food,
    Macros,
    MealType,
    Recipe,
    RecipeIngredient,
)

MAX_INGREDIENTS = 60


@dataclass(frozen=True, slots=True)
class IngredientInput:
    food_id: UUID
    grams: Decimal


@dataclass(frozen=True, slots=True)
class RecipeView:
    """A recipe with its totals already resolved.

    The macros are computed rather than stored: storing them would mean a corrected food
    leaves every recipe that uses it quietly wrong, which is the exact failure the
    reference-not-copy rule exists to prevent.
    """

    recipe: Recipe
    total: Macros
    per_serving: Macros
    foods: dict[UUID, Food]

    @property
    def has_missing_ingredients(self) -> bool:
        """True when an ingredient's food is gone.

        Surfaced rather than hidden: the totals are under-reported while it is true, and
        a user shown a confidently wrong calorie count has no way to notice.
        """
        return any(i.food_id not in self.foods for i in self.recipe.ingredients)


@dataclass(frozen=True, slots=True)
class LogRecipeCommand:
    user_id: UUID
    recipe_id: UUID
    meal_type: MealType
    servings: Decimal
    local_date: date | None = None


class _RecipeResolver:
    """Shared loading of a recipe's ingredient foods."""

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def _resolve(self, recipe: Recipe, user_id: UUID) -> RecipeView:
        food_ids = [i.food_id for i in recipe.ingredients]
        foods = await self._uow.foods.get_many(food_ids, user_id) if food_ids else {}
        return RecipeView(
            recipe=recipe,
            total=recipe.total_macros(foods),
            per_serving=recipe.per_serving(foods),
            foods=foods,
        )


class ListRecipesUseCase(_RecipeResolver):
    async def execute(self, user_id: UUID) -> list[RecipeView]:
        async with self._uow:
            recipes = await self._uow.recipes.list_for_user(user_id)
            return [await self._resolve(recipe, user_id) for recipe in recipes]


class GetRecipeUseCase(_RecipeResolver):
    async def execute(self, recipe_id: UUID, user_id: UUID) -> RecipeView:
        async with self._uow:
            recipe = await self._uow.recipes.get(recipe_id, user_id)
            if recipe is None:
                raise NotFoundError("That recipe does not exist.")
            return await self._resolve(recipe, user_id)


class SaveRecipeUseCase(_RecipeResolver):
    """Create or replace a recipe and its ingredient list.

    Ingredients are replaced wholesale rather than patched one at a time. Editing a
    recipe is an editing session — add two things, remove one, change a weight — and
    making the client send that as a diff would put the reconciliation in the least
    reliable place.
    """

    async def create(
        self,
        user_id: UUID,
        *,
        name: str,
        servings_count: Decimal,
        notes: str | None = None,
        ingredients: list[IngredientInput] | None = None,
    ) -> RecipeView:
        try:
            recipe = Recipe.create(user_id=user_id, name=name, servings_count=servings_count)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        recipe.notes = notes

        async with self._uow:
            await self._uow.recipes.add(recipe)
            if ingredients:
                recipe.ingredients = await self._build(recipe.id, user_id, ingredients)
                await self._uow.recipes.replace_ingredients(recipe)
            view = await self._resolve(recipe, user_id)
            await self._uow.commit()
        return view

    async def update(
        self,
        recipe_id: UUID,
        user_id: UUID,
        *,
        name: str,
        servings_count: Decimal,
        notes: str | None = None,
        ingredients: list[IngredientInput] | None = None,
    ) -> RecipeView:
        async with self._uow:
            recipe = await self._uow.recipes.get(recipe_id, user_id)
            if recipe is None:
                raise NotFoundError("That recipe does not exist.")
            if not name.strip():
                raise ValidationError("A recipe needs a name.")
            if servings_count <= Decimal(0):
                raise ValidationError("A recipe makes at least part of a serving.")

            recipe.name = name.strip()
            recipe.servings_count = servings_count
            recipe.notes = notes
            recipe.ingredients = await self._build(recipe.id, user_id, ingredients or [])

            await self._uow.recipes.update(recipe)
            await self._uow.recipes.replace_ingredients(recipe)
            view = await self._resolve(recipe, user_id)
            await self._uow.commit()
        return view

    async def _build(
        self, recipe_id: UUID, user_id: UUID, inputs: list[IngredientInput]
    ) -> list[RecipeIngredient]:
        if len(inputs) > MAX_INGREDIENTS:
            raise ValidationError(f"A recipe can hold at most {MAX_INGREDIENTS} ingredients.")

        # Every food is checked against the caller before it is stored. Without this, a
        # recipe is a way to read the macros of someone else's private custom food by
        # guessing its id.
        found = await self._uow.foods.get_many([i.food_id for i in inputs], user_id)
        built: list[RecipeIngredient] = []
        for item in inputs:
            if item.grams <= Decimal(0):
                raise ValidationError("Every ingredient needs a weight greater than zero.")
            food = found.get(item.food_id)
            if food is None:
                raise ValidationError("One of those ingredients does not exist.")
            built.append(
                RecipeIngredient(
                    id=uuid7(),
                    recipe_id=recipe_id,
                    food_id=item.food_id,
                    grams=item.grams,
                    display_name=food.name,
                )
            )
        return built


class DeleteRecipeUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, recipe_id: UUID, user_id: UUID) -> None:
        async with self._uow:
            recipe = await self._uow.recipes.get(recipe_id, user_id)
            if recipe is None:
                raise NotFoundError("That recipe does not exist.")
            await self._uow.recipes.delete(recipe_id, user_id)
            await self._uow.commit()


class LogRecipeUseCase(_RecipeResolver):
    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        super().__init__(uow=uow)
        self._clock = clock

    async def execute(self, command: LogRecipeCommand) -> DiaryEntry:
        async with self._uow:
            user = await self._uow.users.get_by_id(command.user_id)
            if user is None:
                raise NotFoundError("user", command.user_id)
            on = command.local_date or local_date_for(self._clock.now(), user.timezone)

            recipe = await self._uow.recipes.get(command.recipe_id, command.user_id)
            if recipe is None:
                raise NotFoundError("That recipe does not exist.")
            if not recipe.ingredients:
                raise ValidationError("Add an ingredient before logging this recipe.")

            food_ids = [i.food_id for i in recipe.ingredients]
            foods = await self._uow.foods.get_many(food_ids, command.user_id)

            try:
                entry = DiaryEntry.for_recipe(
                    user_id=command.user_id,
                    local_date=on,
                    meal_type=command.meal_type,
                    recipe=recipe,
                    servings=command.servings,
                    foods=foods,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

            await self._uow.diary.add(entry)
            await self._uow.commit()

        return entry
