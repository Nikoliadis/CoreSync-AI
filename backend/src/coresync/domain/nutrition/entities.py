"""Nutrition entities.

Two decisions here shape everything else.

**Foods carry denormalised macros per 100 g** alongside a normalised micronutrient set.
Every diary read needs exactly those five numbers, and joining a nutrient table four
times per entry would be absurd; the micros live separately because they are read on the
food-detail screen, not on the diary list (docs/03 §7).

**Diary entries snapshot their nutrition.** They copy calories and macros rather than
computing them from the food on read. Food data gets corrected — by moderators, by
upstream imports, by a brand changing its recipe — and if yesterday's diary recalculated
from today's food row, a user's *history* would silently change under them. A diary entry
is a record of what was logged, so it stores what was true then.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import IntEnum, StrEnum
from uuid import UUID

from coresync.core.ids import uuid7

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class FoodSource(StrEnum):
    CURATED = "curated"
    USDA = "usda"
    OFF = "off"
    USER = "user"


class TrustTier(IntEnum):
    """Search ranks by trust. The UI badges tier 1 as "Verified".

    The ordering is the point: an in-house curated entry outranks a USDA reference
    entry, which outranks crowd-sourced Open Food Facts data, which outranks a stranger's
    custom food. A fast app with wrong calories is worthless, so the ranking exists to
    put the trustworthy number first.
    """

    CURATED = 1
    REFERENCE = 2
    COMMUNITY = 3
    USER = 4

    @classmethod
    def for_source(cls, source: FoodSource) -> TrustTier:
        return {
            FoodSource.CURATED: cls.CURATED,
            FoodSource.USDA: cls.REFERENCE,
            FoodSource.OFF: cls.COMMUNITY,
            FoodSource.USER: cls.USER,
        }[source]


class NutrientCategory(StrEnum):
    MACRO = "macro"
    VITAMIN = "vitamin"
    MINERAL = "mineral"
    OTHER = "other"


def _round(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------- reference
@dataclass(frozen=True, slots=True)
class Nutrient:
    id: UUID
    code: str
    name: str
    unit: str
    category: NutrientCategory
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class FoodBrand:
    id: UUID
    name: str


@dataclass(slots=True)
class FoodServing:
    """A household portion with its gram equivalent.

    Users log in cups and slices; nutrition maths happens in grams. Without this table
    every user re-derives portions by hand and the data becomes noise.
    """

    id: UUID
    label: str
    grams: Decimal
    is_default: bool = False

    @classmethod
    def create(cls, *, label: str, grams: Decimal, is_default: bool = False) -> FoodServing:
        if grams <= _ZERO:
            raise ValueError("a serving must weigh something")
        return cls(id=uuid7(), label=label.strip(), grams=grams, is_default=is_default)


@dataclass(frozen=True, slots=True)
class MacroNutrients:
    """Calories and the four numbers every diary row needs."""

    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    fiber_g: Decimal | None = None

    def scaled_to(self, grams: Decimal) -> MacroNutrients:
        """Scale per-100 g values to an arbitrary portion."""
        factor = grams / _HUNDRED
        return MacroNutrients(
            calories=_round(self.calories * factor),
            protein_g=_round(self.protein_g * factor, "0.001"),
            carbs_g=_round(self.carbs_g * factor, "0.001"),
            fat_g=_round(self.fat_g * factor, "0.001"),
            fiber_g=_round(self.fiber_g * factor, "0.001") if self.fiber_g is not None else None,
        )

    def __add__(self, other: MacroNutrients) -> MacroNutrients:
        return MacroNutrients(
            calories=self.calories + other.calories,
            protein_g=self.protein_g + other.protein_g,
            carbs_g=self.carbs_g + other.carbs_g,
            fat_g=self.fat_g + other.fat_g,
            fiber_g=(self.fiber_g or _ZERO) + (other.fiber_g or _ZERO),
        )

    @property
    def energy_from_macros(self) -> Decimal:
        """Atwater factors: 4 kcal/g protein and carbs, 9 kcal/g fat."""
        return self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9

    def is_energy_consistent(self, *, tolerance: Decimal = Decimal("0.25")) -> bool:
        """Whether the macros roughly reconcile with the stated calories.

        Mirrors ``ck_food_energy_sane`` on the table. Imported data is frequently wrong
        in exactly this way — a decimal point in the wrong place — and it is the single
        cheapest quality signal available.
        """
        if self.calories == _ZERO:
            return True
        drift = abs(self.calories - self.energy_from_macros)
        return drift <= max(Decimal("50"), self.calories * tolerance)


@dataclass(slots=True)
class Food:
    """A food, global or user-authored.

    Same single-table scoping as exercises: ``owner_user_id is None`` means public,
    non-NULL means that user's private custom food.
    """

    id: UUID
    name: str
    source: FoodSource
    trust_tier: TrustTier
    macros: MacroNutrients
    brand_id: UUID | None = None
    brand_name: str | None = None
    owner_user_id: UUID | None = None
    is_verified: bool = False
    is_liquid: bool = False
    usage_count: int = 0
    servings: list[FoodServing] = field(default_factory=list)
    barcodes: list[str] = field(default_factory=list)
    micronutrients: dict[str, Decimal] = field(default_factory=dict)
    is_favorite: bool = False

    @classmethod
    def create_custom(
        cls,
        *,
        owner_user_id: UUID,
        name: str,
        macros: MacroNutrients,
        brand_id: UUID | None = None,
        is_liquid: bool = False,
        servings: list[FoodServing] | None = None,
    ) -> Food:
        if not name.strip():
            raise ValueError("a food needs a name")
        if not macros.is_energy_consistent():
            raise ValueError(
                f"macros total {macros.energy_from_macros:.0f} kcal "
                f"against a stated {macros.calories:.0f} kcal"
            )
        return cls(
            id=uuid7(),
            name=name.strip(),
            source=FoodSource.USER,
            trust_tier=TrustTier.USER,
            macros=macros,
            brand_id=brand_id,
            owner_user_id=owner_user_id,
            # A user cannot mark their own food verified; the CHECK constraint agrees.
            is_verified=False,
            is_liquid=is_liquid,
            servings=servings or [],
        )

    @property
    def is_custom(self) -> bool:
        return self.owner_user_id is not None

    def is_editable_by(self, user_id: UUID) -> bool:
        return self.owner_user_id is not None and self.owner_user_id == user_id

    @property
    def default_serving(self) -> FoodServing | None:
        """The portion the UI pre-selects.

        Falls back to the first declared serving, and finally to None — in which case
        the client offers grams, which always works.
        """
        return next(
            (s for s in self.servings if s.is_default),
            self.servings[0] if self.servings else None,
        )

    def nutrition_for(
        self, *, quantity: Decimal, serving: FoodServing | None
    ) -> tuple[Decimal, MacroNutrients]:
        """Resolve a logged portion to grams and the macros it carries.

        ``serving is None`` means the quantity is already grams — the universal fallback
        when a food has no household portions.
        """
        if quantity <= _ZERO:
            raise ValueError("quantity must be positive")
        grams = quantity * serving.grams if serving else quantity
        return _round(grams, "0.001"), self.macros.scaled_to(grams)


# ----------------------------------------------------------------------- diary
@dataclass(slots=True)
class DiaryEntry:
    """One logged item. Carries its own nutrition, snapshotted at log time."""

    id: UUID
    user_id: UUID
    local_date: date
    meal_type: MealType
    quantity: Decimal
    total_grams: Decimal
    macros: MacroNutrients
    food_id: UUID | None = None
    recipe_id: UUID | None = None
    serving_id: UUID | None = None
    logged_at: datetime | None = None
    micronutrients: dict[str, Decimal] = field(default_factory=dict)
    # Display-only, resolved on read.
    display_name: str | None = None
    serving_label: str | None = None
    brand_name: str | None = None

    @classmethod
    def for_food(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        meal_type: MealType,
        food: Food,
        quantity: Decimal,
        serving: FoodServing | None,
        logged_at: datetime | None = None,
        entry_id: UUID | None = None,
    ) -> DiaryEntry:
        grams, macros = food.nutrition_for(quantity=quantity, serving=serving)
        return cls(
            id=entry_id or uuid7(),
            user_id=user_id,
            local_date=local_date,
            meal_type=meal_type,
            quantity=quantity,
            total_grams=grams,
            macros=macros,
            food_id=food.id,
            serving_id=serving.id if serving else None,
            logged_at=logged_at,
            micronutrients={
                code: _round(amount * grams / _HUNDRED, "0.001")
                for code, amount in food.micronutrients.items()
            },
            display_name=food.name,
            serving_label=serving.label if serving else "g",
            brand_name=food.brand_name,
        )

    @classmethod
    def quick_add(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        meal_type: MealType,
        macros: MacroNutrients,
        name: str = "Quick add",
        logged_at: datetime | None = None,
    ) -> DiaryEntry:
        """Calories with no food behind them.

        Deliberately supported: refusing to let someone log a restaurant meal they
        cannot find is how a diary stops being used.
        """
        return cls(
            id=uuid7(),
            user_id=user_id,
            local_date=local_date,
            meal_type=meal_type,
            quantity=Decimal("1"),
            total_grams=_ZERO,
            macros=macros,
            logged_at=logged_at,
            display_name=name.strip() or "Quick add",
        )

    @property
    def is_quick_add(self) -> bool:
        return self.food_id is None and self.recipe_id is None

    def rescale(self, *, quantity: Decimal, food: Food, serving: FoodServing | None) -> None:
        """Change the portion, recomputing from the food as it is *now*.

        An edit is a fresh statement about what was eaten, so it re-reads the food. That
        is different from a historical entry silently drifting, which is what the
        snapshot prevents.
        """
        grams, macros = food.nutrition_for(quantity=quantity, serving=serving)
        self.quantity = quantity
        self.total_grams = grams
        self.macros = macros
        self.serving_id = serving.id if serving else None
        self.serving_label = serving.label if serving else "g"


# --------------------------------------------------------------------- recipes
@dataclass(slots=True)
class RecipeIngredient:
    id: UUID
    food_id: UUID
    quantity: Decimal
    total_grams: Decimal
    macros: MacroNutrients
    serving_id: UUID | None = None
    food_name: str | None = None
    serving_label: str | None = None

    @classmethod
    def create(
        cls,
        *,
        food: Food,
        quantity: Decimal,
        serving: FoodServing | None,
    ) -> RecipeIngredient:
        grams, macros = food.nutrition_for(quantity=quantity, serving=serving)
        return cls(
            id=uuid7(),
            food_id=food.id,
            quantity=quantity,
            total_grams=grams,
            macros=macros,
            serving_id=serving.id if serving else None,
            food_name=food.name,
            serving_label=serving.label if serving else "g",
        )


@dataclass(slots=True)
class Recipe:
    """A user's composed dish. Totals are derived from ingredients, never stored loose."""

    id: UUID
    user_id: UUID
    name: str
    servings_count: Decimal
    notes: str | None = None
    is_public: bool = False
    ingredients: list[RecipeIngredient] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        name: str,
        servings_count: Decimal,
        notes: str | None = None,
        ingredients: list[RecipeIngredient] | None = None,
    ) -> Recipe:
        if not name.strip():
            raise ValueError("a recipe needs a name")
        if servings_count <= _ZERO:
            raise ValueError("a recipe must make at least one serving")
        return cls(
            id=uuid7(),
            user_id=user_id,
            name=name.strip(),
            servings_count=servings_count,
            notes=notes,
            ingredients=ingredients or [],
        )

    @property
    def total_macros(self) -> MacroNutrients:
        total = MacroNutrients(_ZERO, _ZERO, _ZERO, _ZERO, _ZERO)
        for ingredient in self.ingredients:
            total = total + ingredient.macros
        return total

    @property
    def total_grams(self) -> Decimal:
        return sum((i.total_grams for i in self.ingredients), _ZERO)

    @property
    def per_serving(self) -> MacroNutrients:
        """What one serving contains.

        This is the number the user actually logs, so it is derived rather than stored —
        editing an ingredient must not leave a stale per-serving figure behind.
        """
        total = self.total_macros
        count = self.servings_count
        return MacroNutrients(
            calories=_round(total.calories / count),
            protein_g=_round(total.protein_g / count, "0.001"),
            carbs_g=_round(total.carbs_g / count, "0.001"),
            fat_g=_round(total.fat_g / count, "0.001"),
            fiber_g=_round((total.fiber_g or _ZERO) / count, "0.001"),
        )

    @property
    def grams_per_serving(self) -> Decimal:
        return _round(self.total_grams / self.servings_count, "0.001")

    def as_diary_entry(
        self,
        *,
        user_id: UUID,
        local_date: date,
        meal_type: MealType,
        servings: Decimal,
        logged_at: datetime | None = None,
    ) -> DiaryEntry:
        if servings <= _ZERO:
            raise ValueError("quantity must be positive")
        single = self.per_serving
        return DiaryEntry(
            id=uuid7(),
            user_id=user_id,
            local_date=local_date,
            meal_type=meal_type,
            quantity=servings,
            total_grams=_round(self.grams_per_serving * servings, "0.001"),
            macros=MacroNutrients(
                calories=_round(single.calories * servings),
                protein_g=_round(single.protein_g * servings, "0.001"),
                carbs_g=_round(single.carbs_g * servings, "0.001"),
                fat_g=_round(single.fat_g * servings, "0.001"),
                fiber_g=_round((single.fiber_g or _ZERO) * servings, "0.001"),
            ),
            recipe_id=self.id,
            logged_at=logged_at,
            display_name=self.name,
            serving_label="serving",
        )


# ----------------------------------------------------------------------- water
@dataclass(slots=True)
class WaterLog:
    """Logged in increments through the day.

    A separate table rather than a column on the daily summary, because the timestamps
    are what drive hydration-reminder timing in Phase 6.
    """

    id: UUID
    user_id: UUID
    local_date: date
    amount_ml: Decimal
    logged_at: datetime | None = None

    MAX_SINGLE_ML = Decimal("5000")

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        amount_ml: Decimal,
        logged_at: datetime | None = None,
    ) -> WaterLog:
        if amount_ml <= _ZERO:
            raise ValueError("water amount must be positive")
        if amount_ml > cls.MAX_SINGLE_ML:
            raise ValueError("that is an implausible amount of water in one go")
        return cls(
            id=uuid7(),
            user_id=user_id,
            local_date=local_date,
            amount_ml=amount_ml,
            logged_at=logged_at,
        )
