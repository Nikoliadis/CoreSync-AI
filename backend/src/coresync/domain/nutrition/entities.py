"""Nutrition entities.

The two decisions that shape everything here are already made in docs/03 §7:

**Macros are denormalised onto the food row.** Every diary read needs exactly five
numbers, and joining `food_nutrients` four times per entry to get them would be absurd.
The full micronutrient set stays normalised because it is read on one screen.

**Diary entries snapshot their nutrition.** They copy calories and macros rather than
recomputing from the food. Food data gets corrected — by moderators, by upstream
imports, by a brand reformulating — and if yesterday's diary recalculated from today's
row, the user's *history* would change under them and every trend built on it would be
wrong. A diary entry records what was true when it was logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import IntEnum, StrEnum
from typing import Any
from uuid import UUID

from coresync.core.ids import uuid7

_ZERO = Decimal("0")
GRAMS_PER_REFERENCE = Decimal("100")

# Atwater factors. Protein and carbohydrate yield 4 kcal/g, fat 9.
KCAL_PER_G_PROTEIN = Decimal("4")
KCAL_PER_G_CARBS = Decimal("4")
KCAL_PER_G_FAT = Decimal("9")
# Ethanol. Not one of the three macros, but it is where most of the energy in a glass
# of wine comes from — omitting it makes the reconciliation reject every alcoholic
# drink as if it were a data-entry error.
KCAL_PER_G_ALCOHOL = Decimal("7")


class FoodSource(StrEnum):
    CURATED = "curated"
    OFF = "off"
    USDA = "usda"
    USER = "user"


class TrustTier(IntEnum):
    """How much the data can be relied on. Search ranks by this before anything else.

    Food data quality is a *fatal* risk in docs/15 — a product that tells someone they
    ate 300 kcal when they ate 600 is worse than one that tells them nothing. Ranking
    by provenance is the structural half of the mitigation; the visible "Verified"
    badge is the other half.
    """

    CURATED = 1
    OFFICIAL = 2
    COMMUNITY = 3
    USER = 4

    @classmethod
    def for_source(cls, source: FoodSource) -> TrustTier:
        return {
            FoodSource.CURATED: cls.CURATED,
            FoodSource.USDA: cls.OFFICIAL,
            FoodSource.OFF: cls.COMMUNITY,
            FoodSource.USER: cls.USER,
        }[source]


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


def _round(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Macros:
    """Calories and the three macronutrients, for some quantity of food."""

    calories: Decimal = _ZERO
    protein_g: Decimal = _ZERO
    carbs_g: Decimal = _ZERO
    fat_g: Decimal = _ZERO
    alcohol_g: Decimal = _ZERO

    def __add__(self, other: Macros) -> Macros:
        return Macros(
            calories=self.calories + other.calories,
            protein_g=self.protein_g + other.protein_g,
            carbs_g=self.carbs_g + other.carbs_g,
            fat_g=self.fat_g + other.fat_g,
            alcohol_g=self.alcohol_g + other.alcohol_g,
        )

    def scaled(self, factor: Decimal) -> Macros:
        return Macros(
            calories=self.calories * factor,
            protein_g=self.protein_g * factor,
            carbs_g=self.carbs_g * factor,
            fat_g=self.fat_g * factor,
            alcohol_g=self.alcohol_g * factor,
        )

    def rounded(self) -> Macros:
        return Macros(
            calories=_round(self.calories),
            protein_g=_round(self.protein_g),
            carbs_g=_round(self.carbs_g),
            fat_g=_round(self.fat_g),
            alcohol_g=_round(self.alcohol_g),
        )

    @property
    def energy_from_macros(self) -> Decimal:
        """Calories implied by the macros, via the Atwater factors."""
        return (
            self.protein_g * KCAL_PER_G_PROTEIN
            + self.carbs_g * KCAL_PER_G_CARBS
            + self.fat_g * KCAL_PER_G_FAT
            + self.alcohol_g * KCAL_PER_G_ALCOHOL
        )


@dataclass(slots=True)
class FoodServing:
    """A household unit with its gram equivalent.

    Users log "one medium banana", not "118 g". Without this table every user derives
    portions by hand and the data becomes noise (docs/03 §7).
    """

    id: UUID
    food_id: UUID
    label: str
    grams: Decimal
    is_default: bool = False

    @classmethod
    def create(
        cls, *, food_id: UUID, label: str, grams: Decimal, is_default: bool = False
    ) -> FoodServing:
        if grams <= _ZERO:
            raise ValueError("A serving must weigh more than nothing.")
        return cls(
            id=uuid7(), food_id=food_id, label=label.strip(), grams=grams, is_default=is_default
        )


@dataclass(slots=True)
class Food:
    """A food, with macros expressed per 100 g."""

    id: UUID
    name: str
    source: FoodSource
    trust_tier: TrustTier
    calories_per_100g: Decimal
    protein_per_100g: Decimal = _ZERO
    carbs_per_100g: Decimal = _ZERO
    fat_per_100g: Decimal = _ZERO
    alcohol_per_100g: Decimal = _ZERO
    brand_id: UUID | None = None
    # NULL means public. A custom food is searchable only by its owner, the same
    # single-table pattern the exercise catalog uses.
    owner_user_id: UUID | None = None
    is_verified: bool = False
    is_liquid: bool = False
    usage_count: int = 0
    servings: list[FoodServing] = field(default_factory=list)
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        source: FoodSource,
        calories_per_100g: Decimal,
        protein_per_100g: Decimal = _ZERO,
        carbs_per_100g: Decimal = _ZERO,
        fat_per_100g: Decimal = _ZERO,
        alcohol_per_100g: Decimal = _ZERO,
        brand_id: UUID | None = None,
        owner_user_id: UUID | None = None,
        is_liquid: bool = False,
    ) -> Food:
        if not name.strip():
            raise ValueError("A food needs a name.")
        if calories_per_100g < _ZERO:
            raise ValueError("Calories cannot be negative.")
        for label, value in (
            ("protein", protein_per_100g),
            ("carbohydrate", carbs_per_100g),
            ("fat", fat_per_100g),
            ("alcohol", alcohol_per_100g),
        ):
            if value < _ZERO:
                raise ValueError(f"{label.capitalize()} cannot be negative.")

        return cls(
            id=uuid7(),
            name=name.strip(),
            source=source,
            trust_tier=TrustTier.for_source(source),
            calories_per_100g=calories_per_100g,
            protein_per_100g=protein_per_100g,
            carbs_per_100g=carbs_per_100g,
            fat_per_100g=fat_per_100g,
            alcohol_per_100g=alcohol_per_100g,
            brand_id=brand_id,
            owner_user_id=owner_user_id,
            # Only tier 1 is badged "Verified" — the badge means a human checked it,
            # not that the row exists.
            is_verified=TrustTier.for_source(source) is TrustTier.CURATED,
            is_liquid=is_liquid,
        )

    @property
    def is_custom(self) -> bool:
        return self.owner_user_id is not None

    @property
    def per_100g(self) -> Macros:
        return Macros(
            calories=self.calories_per_100g,
            protein_g=self.protein_per_100g,
            carbs_g=self.carbs_per_100g,
            fat_g=self.fat_per_100g,
            alcohol_g=self.alcohol_per_100g,
        )

    def macros_for(self, grams: Decimal) -> Macros:
        """Nutrition for an arbitrary weight."""
        if grams < _ZERO:
            raise ValueError("A portion cannot weigh less than nothing.")
        return self.per_100g.scaled(grams / GRAMS_PER_REFERENCE).rounded()

    def default_serving(self) -> FoodServing | None:
        return next(
            (s for s in self.servings if s.is_default),
            self.servings[0] if self.servings else None,
        )


@dataclass(slots=True)
class DiaryEntry:
    """One logged item.

    The macros here are a snapshot, not a reference. See the module docstring.
    """

    id: UUID
    user_id: UUID
    local_date: date
    meal_type: MealType
    quantity: Decimal
    total_grams: Decimal
    macros: Macros
    food_id: UUID | None = None
    recipe_id: UUID | None = None
    serving_id: UUID | None = None
    # Denormalised for display so the diary list needs no join.
    display_name: str = ""
    micronutrients: dict[str, Any] = field(default_factory=dict)
    logged_at: datetime | None = None

    @classmethod
    def for_food(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        meal_type: MealType,
        food: Food,
        quantity: Decimal,
        serving: FoodServing | None = None,
    ) -> DiaryEntry:
        """Log a food, in servings if one is given and grams otherwise."""
        if quantity <= _ZERO:
            raise ValueError("Log an amount greater than zero.")

        grams = (serving.grams * quantity) if serving else quantity
        return cls(
            id=uuid7(),
            user_id=user_id,
            local_date=local_date,
            meal_type=meal_type,
            quantity=quantity,
            total_grams=_round(grams),
            macros=food.macros_for(grams),
            food_id=food.id,
            serving_id=serving.id if serving else None,
            display_name=food.name,
        )

    @classmethod
    def for_recipe(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        meal_type: MealType,
        recipe: Recipe,
        servings: Decimal,
        foods: dict[UUID, Food],
    ) -> DiaryEntry:
        """Log servings of a recipe.

        The recipe's per-serving macros are resolved *now* and snapshotted, exactly as a
        food is. This is where the two rules meet: the recipe keeps referencing its
        ingredients so it stays correct as food data is corrected, while the entry keeps
        the numbers that were true at the moment it was eaten.
        """
        if servings <= _ZERO:
            raise ValueError("Log an amount greater than zero.")

        per_serving = recipe.per_serving(foods)
        grams = (
            sum(
                (ingredient.grams for ingredient in recipe.ingredients),
                _ZERO,
            )
            / recipe.servings_count
        )
        return cls(
            id=uuid7(),
            user_id=user_id,
            local_date=local_date,
            meal_type=meal_type,
            quantity=servings,
            total_grams=_round(grams * servings),
            macros=per_serving.scaled(servings).rounded(),
            recipe_id=recipe.id,
            display_name=recipe.name,
        )

    @classmethod
    def quick_add(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        meal_type: MealType,
        macros: Macros,
        label: str = "Quick add",
    ) -> DiaryEntry:
        """Calories with no food behind them.

        Kept as a first-class case rather than forcing a fake food row: someone eating
        out cannot find the dish, and making them invent a food to record it is how a
        diary stops being used.
        """
        return cls(
            id=uuid7(),
            user_id=user_id,
            local_date=local_date,
            meal_type=meal_type,
            quantity=Decimal(1),
            total_grams=_ZERO,
            macros=macros.rounded(),
            display_name=label.strip() or "Quick add",
        )


@dataclass(slots=True)
class WaterLog:
    """A hydration increment.

    Its own table rather than a column on a daily summary: users log through the day,
    and the timestamps are what drive reminder timing (docs/03 §7).
    """

    id: UUID
    user_id: UUID
    local_date: date
    millilitres: Decimal
    logged_at: datetime | None = None

    @classmethod
    def create(cls, *, user_id: UUID, local_date: date, millilitres: Decimal) -> WaterLog:
        if millilitres <= _ZERO:
            raise ValueError("Log an amount greater than zero.")
        return cls(id=uuid7(), user_id=user_id, local_date=local_date, millilitres=millilitres)


@dataclass(slots=True)
class RecipeIngredient:
    id: UUID
    recipe_id: UUID
    food_id: UUID
    grams: Decimal
    display_name: str = ""


@dataclass(slots=True)
class Recipe:
    """A composed dish, totalled from its ingredients.

    Ingredients reference foods rather than copying their macros, so a recipe stays
    correct as food data is corrected. That is the opposite of the diary's rule, and
    deliberately so: a recipe is a *definition*, a diary entry is a *record*.
    """

    id: UUID
    user_id: UUID
    name: str
    servings_count: Decimal
    ingredients: list[RecipeIngredient] = field(default_factory=list)
    notes: str | None = None

    @classmethod
    def create(cls, *, user_id: UUID, name: str, servings_count: Decimal) -> Recipe:
        if not name.strip():
            raise ValueError("A recipe needs a name.")
        if servings_count <= _ZERO:
            raise ValueError("A recipe makes at least part of a serving.")
        return cls(id=uuid7(), user_id=user_id, name=name.strip(), servings_count=servings_count)

    def total_macros(self, foods: dict[UUID, Food]) -> Macros:
        total = Macros()
        for ingredient in self.ingredients:
            food = foods.get(ingredient.food_id)
            if food is None:
                # A missing ingredient is skipped rather than counted as zero — the
                # recipe is incomplete, and silently under-reporting its calories would
                # be worse than the gap.
                continue
            total = total + food.macros_for(ingredient.grams)
        return total.rounded()

    def per_serving(self, foods: dict[UUID, Food]) -> Macros:
        return self.total_macros(foods).scaled(Decimal(1) / self.servings_count).rounded()
