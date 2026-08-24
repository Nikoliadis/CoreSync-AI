"""Wire schemas for nutrition."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field, field_serializer

from coresync.presentation.schemas.common import ApiModel

MEAL_PATTERN = "^(breakfast|lunch|dinner|snack)$"


# Pydantic's camel-case generator reads the digit boundary in `calories_per_100g` as a
# word break and emits `caloriesPer100G`. The capital G is a typo waiting to happen in
# every client that touches nutrition, so these fields carry explicit aliases. Fixed now
# because no client consumes them yet; after release it would be a breaking change.
def per_100g(**kwargs: object) -> Any:
    field = kwargs.pop("field_name")
    return Field(alias=f"{field}Per100g", **kwargs)  # type: ignore[arg-type]


_MACRO_PLACES = Decimal("0.01")


class MacrosResponse(ApiModel):
    """Macros on the wire, always at two decimal places.

    Without normalising, the same quantity is serialised differently depending on where
    it came from: freshly computed the domain rounds to two places, while a value read
    back from a Numeric(9,3) column arrives with three. A client comparing the strings —
    to spot a change, or to key a cache — would see "11.00" and "11.000" as different
    numbers. One value, one wire form.
    """

    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    # Ethanol, at 7 kcal/g. Reported because it is where the calories in a drink come
    # from; a client that only renders the three macros can ignore it and still add up.
    alcohol_g: Decimal = Decimal(0)

    @field_serializer("calories", "protein_g", "carbs_g", "fat_g", "alcohol_g")
    def _two_places(self, value: Decimal) -> Decimal:
        return value.quantize(_MACRO_PLACES)


class FoodServingResponse(ApiModel):
    id: UUID
    label: str
    grams: Decimal
    is_default: bool


class FoodResponse(ApiModel):
    id: UUID
    name: str
    source: str
    # 1 = curated, 2 = official, 3 = community, 4 = user. Clients badge tier 1.
    trust_tier: int
    is_verified: bool
    is_custom: bool
    is_liquid: bool
    calories_per_100g: Decimal = per_100g(field_name="calories")
    protein_per_100g: Decimal = per_100g(field_name="protein")
    carbs_per_100g: Decimal = per_100g(field_name="carbs")
    fat_per_100g: Decimal = per_100g(field_name="fat")
    alcohol_per_100g: Decimal = per_100g(field_name="alcohol", default=Decimal(0))
    servings: list[FoodServingResponse] = Field(default_factory=list)


class NutrientResponse(ApiModel):
    code: str
    name: str
    # 'g', 'mg', 'mcg' or 'IU' — the unit a label prints, so the client renders the
    # number without doing arithmetic.
    unit: str
    amount_per_100g: Decimal


class FoodDetailResponse(ApiModel):
    """A food and everything measured about it.

    Separate from the search response on purpose: a search returning the full nutrient
    breakdown for twenty-five results would be an order of magnitude more bytes for data
    nobody is looking at yet.
    """

    food: FoodResponse
    nutrients: list[NutrientResponse] = Field(default_factory=list)


class FoodSearchResponse(ApiModel):
    items: list[FoodResponse]
    total: int


class CreateFoodServingRequest(ApiModel):
    label: str = Field(min_length=1, max_length=80)
    grams: Decimal = Field(gt=0, le=10_000)


class CreateFoodRequest(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    calories_per_100g: Decimal = per_100g(field_name="calories", ge=0, le=1000)
    protein_per_100g: Decimal = per_100g(field_name="protein", default=Decimal(0), ge=0, le=100)
    carbs_per_100g: Decimal = per_100g(field_name="carbs", default=Decimal(0), ge=0, le=100)
    fat_per_100g: Decimal = per_100g(field_name="fat", default=Decimal(0), ge=0, le=100)
    # Needed for spirits: without it a homemade τσίπουρο fails the energy check, since
    # its calories reconcile against nothing the other three fields can express.
    alcohol_per_100g: Decimal = per_100g(field_name="alcohol", default=Decimal(0), ge=0, le=100)
    is_liquid: bool = False
    servings: list[CreateFoodServingRequest] = Field(default_factory=list, max_length=10)


class EditDiaryEntryRequest(ApiModel):
    """Every field optional: this is a correction, not a re-log.

    Sending only `quantity` moves the amount and leaves the meal and the day alone.
    """

    quantity: Decimal | None = Field(default=None, gt=0, le=10_000)
    meal_type: str | None = Field(default=None, pattern=MEAL_PATTERN)
    serving_id: UUID | None = None
    local_date: date | None = None


class CopyDayRequest(ApiModel):
    source_date: date
    target_date: date
    # Null copies the whole day; a meal name copies just that meal.
    meal_type: str | None = Field(default=None, pattern=MEAL_PATTERN)


class CopyDayResponse(ApiModel):
    copied: int
    target_date: date


class DiaryEntryResponse(ApiModel):
    id: UUID
    local_date: date
    meal_type: str
    display_name: str
    quantity: Decimal
    total_grams: Decimal
    macros: MacrosResponse
    food_id: UUID | None = None
    recipe_id: UUID | None = None
    serving_id: UUID | None = None
    logged_at: datetime | None = None


class MealTotalsResponse(ApiModel):
    meal_type: str
    entries: int
    macros: MacrosResponse


class DiaryResponse(ApiModel):
    """A day's diary, its totals, and how they sit against the targets."""

    local_date: date
    totals: MacrosResponse
    water_ml: Decimal
    by_meal: list[MealTotalsResponse]
    entries: list[DiaryEntryResponse]
    # The targets in force on *that* day, not today's — they are versioned so history
    # stays answerable. Null when the user has never set any.
    targets: MacrosResponse | None = None
    remaining: MacrosResponse | None = None


class LogFoodRequest(ApiModel):
    food_id: UUID
    meal_type: str = Field(pattern=MEAL_PATTERN)
    # Servings when `servingId` is given, grams otherwise.
    quantity: Decimal = Field(gt=0, le=10_000)
    serving_id: UUID | None = None
    local_date: date | None = None


class QuickAddRequest(ApiModel):
    """Calories with no food behind them.

    A first-class case, not a workaround: someone eating out cannot find the dish, and
    forcing them to invent a food to record it is how a diary stops being used.
    """

    meal_type: str = Field(pattern=MEAL_PATTERN)
    calories: Decimal = Field(ge=0, le=20_000)
    protein_g: Decimal = Field(default=Decimal(0), ge=0, le=2000)
    carbs_g: Decimal = Field(default=Decimal(0), ge=0, le=2000)
    fat_g: Decimal = Field(default=Decimal(0), ge=0, le=2000)
    alcohol_g: Decimal = Field(default=Decimal(0), ge=0, le=2000)
    label: str = Field(default="Quick add", max_length=120)
    local_date: date | None = None


class LogWaterRequest(ApiModel):
    millilitres: Decimal = Field(gt=0, le=5000)
    local_date: date | None = None


class WaterResponse(ApiModel):
    local_date: date
    total_ml: Decimal


# ---------------------------------------------------------------------- recipes
class RecipeIngredientResponse(ApiModel):
    id: UUID
    food_id: UUID
    food_name: str
    grams: Decimal


class RecipeResponse(ApiModel):
    id: UUID
    name: str
    servings_count: Decimal
    notes: str | None = None
    ingredients: list[RecipeIngredientResponse] = Field(default_factory=list)
    total: MacrosResponse
    per_serving: MacrosResponse
    # True when an ingredient's food no longer exists. The totals under-report while it
    # is set, and a client that hides this shows a confidently wrong number.
    has_missing_ingredients: bool = False


class RecipeListResponse(ApiModel):
    items: list[RecipeResponse]


class RecipeIngredientRequest(ApiModel):
    food_id: UUID
    grams: Decimal = Field(gt=0, le=10_000)


class SaveRecipeRequest(ApiModel):
    """The whole recipe, every time.

    Ingredients are sent as a complete list rather than a diff: editing a recipe is a
    session of several changes, and reconciling them client-side is the least reliable
    place to put that logic.
    """

    name: str = Field(min_length=1, max_length=200)
    servings_count: Decimal = Field(gt=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)
    ingredients: list[RecipeIngredientRequest] = Field(default_factory=list, max_length=60)


class LogRecipeRequest(ApiModel):
    meal_type: str = Field(pattern=MEAL_PATTERN)
    servings: Decimal = Field(gt=0, le=100)
    local_date: date | None = None


# ------------------------------------------------------------------- summaries
class DailySummaryResponse(ApiModel):
    local_date: date
    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    alcohol_g: Decimal
    water_ml: Decimal
    # How the streak counts this day. Zero means nothing was logged.
    entry_count: int
    target_calories: Decimal | None = None
    target_protein_g: Decimal | None = None


class NutritionHistoryResponse(ApiModel):
    items: list[DailySummaryResponse]


class NutritionStreakResponse(ApiModel):
    """Days in a row with something logged.

    Counted over logged days rather than calories: a fasting day, or a day of nothing
    but black coffee, is still a day the person showed up.
    """

    current: int
    longest: int
    last_date: date | None = None


# ------------------------------------------------------------------ moderation
class SubmitFoodRequest(ApiModel):
    note: str | None = Field(default=None, max_length=500)


class FoodSubmissionResponse(ApiModel):
    id: UUID
    food_id: UUID
    status: str
    note: str | None = None
    created_at: datetime | None = None
    reviewed_at: datetime | None = None


class QueuedSubmissionResponse(ApiModel):
    """A queue row with the numbers attached, so a reviewer never has to go look them up."""

    submission: FoodSubmissionResponse
    food: FoodResponse
    # False when the macros only just cleared the energy tolerance. Not a blocker —
    # the database already refused anything outside it — but it is where a reviewer's
    # attention is worth most.
    energy_is_consistent: bool


class SubmissionQueueResponse(ApiModel):
    items: list[QueuedSubmissionResponse]


class ReviewSubmissionRequest(ApiModel):
    note: str | None = Field(default=None, max_length=500)
