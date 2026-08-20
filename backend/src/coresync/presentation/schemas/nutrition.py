"""Wire schemas for nutrition."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from coresync.presentation.schemas.common import ApiModel

MEAL_PATTERN = "^(breakfast|lunch|dinner|snack)$"


class MacrosResponse(ApiModel):
    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal


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
    calories_per_100g: Decimal
    protein_per_100g: Decimal
    carbs_per_100g: Decimal
    fat_per_100g: Decimal
    servings: list[FoodServingResponse] = Field(default_factory=list)


class FoodSearchResponse(ApiModel):
    items: list[FoodResponse]
    total: int


class CreateFoodServingRequest(ApiModel):
    label: str = Field(min_length=1, max_length=80)
    grams: Decimal = Field(gt=0, le=10_000)


class CreateFoodRequest(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    calories_per_100g: Decimal = Field(ge=0, le=1000)
    protein_per_100g: Decimal = Field(default=Decimal(0), ge=0, le=100)
    carbs_per_100g: Decimal = Field(default=Decimal(0), ge=0, le=100)
    fat_per_100g: Decimal = Field(default=Decimal(0), ge=0, le=100)
    is_liquid: bool = False
    servings: list[CreateFoodServingRequest] = Field(default_factory=list, max_length=10)


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
    label: str = Field(default="Quick add", max_length=120)
    local_date: date | None = None


class LogWaterRequest(ApiModel):
    millilitres: Decimal = Field(gt=0, le=5000)
    local_date: date | None = None


class WaterResponse(ApiModel):
    local_date: date
    total_ml: Decimal
