"""Repository ports for the nutrition domain.

As everywhere, ``user_id`` is a required parameter on every read that can touch user
content. Food reads take it because the result set is the public catalog unioned with
*that user's* private custom foods, and must never include anyone else's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from coresync.domain.nutrition.entities import (
    DiaryEntry,
    Food,
    FoodBrand,
    MacroNutrients,
    MealType,
    Nutrient,
    Recipe,
    WaterLog,
)


@dataclass(frozen=True, slots=True)
class FoodSearchCriteria:
    query: str | None = None
    brand_id: UUID | None = None
    verified_only: bool = False
    favorites_only: bool = False
    custom_only: bool = False
    exclude_custom: bool = False


@dataclass(frozen=True, slots=True)
class DailyNutritionSummary:
    local_date: date
    macros: MacroNutrients
    water_ml: Decimal
    entry_count: int
    target_calories: Decimal | None
    is_complete: bool


@dataclass(frozen=True, slots=True)
class NutritionStreak:
    current: int
    longest: int
    last_date: date | None


class FoodRepository(Protocol):
    async def get(self, food_id: UUID, user_id: UUID) -> Food | None: ...

    async def get_many(self, food_ids: list[UUID], user_id: UUID) -> list[Food]: ...

    async def search(
        self,
        user_id: UUID,
        criteria: FoodSearchCriteria,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Food], int]:
        """Ranked search.

        Ordering is recents, then favourites, then trust tier, then popularity — the
        order in which a user is likely to want the answer. Implemented in SQL because
        the ranking is a sort over an index, not a rule worth pulling into Python.
        """
        ...

    async def find_by_barcode(self, barcode: str, user_id: UUID) -> Food | None: ...

    async def recent_for_user(self, user_id: UUID, *, limit: int) -> list[Food]: ...

    async def frequent_for_user(self, user_id: UUID, *, limit: int) -> list[Food]: ...

    async def add(self, food: Food) -> None: ...

    async def update(self, food: Food) -> None: ...

    async def soft_delete(self, food_id: UUID, user_id: UUID) -> None: ...

    async def increment_usage(self, food_ids: list[UUID]) -> None:
        """Popularity, which feeds search ranking. Fire-and-forget on the log path."""
        ...

    async def add_favorite(self, user_id: UUID, food_id: UUID) -> None: ...

    async def remove_favorite(self, user_id: UUID, food_id: UUID) -> None: ...

    async def upsert_imported(self, food: Food, *, barcodes: list[str]) -> Food:
        """Insert or refresh a food that came from an external source.

        Keyed on the barcode rather than the name: the same product arrives repeatedly
        from Open Food Facts, and a name-keyed upsert would fork on punctuation.
        """
        ...


class NutrientRepository(Protocol):
    async def list_all(self) -> list[Nutrient]: ...

    async def codes_to_ids(self, codes: list[str]) -> dict[str, UUID]: ...


class FoodBrandRepository(Protocol):
    async def get_or_create(self, name: str) -> FoodBrand: ...

    async def search(self, query: str, *, limit: int) -> list[FoodBrand]: ...


class DiaryRepository(Protocol):
    async def get(self, entry_id: UUID, user_id: UUID) -> DiaryEntry | None: ...

    async def list_for_date(self, user_id: UUID, on: date) -> list[DiaryEntry]: ...

    async def list_for_meal(
        self, user_id: UUID, on: date, meal_type: MealType
    ) -> list[DiaryEntry]: ...

    async def list_for_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[DiaryEntry]: ...

    async def add(self, entry: DiaryEntry) -> None: ...

    async def add_many(self, entries: list[DiaryEntry]) -> None: ...

    async def update(self, entry: DiaryEntry) -> None: ...

    async def soft_delete(self, entry_id: UUID, user_id: UUID) -> None: ...


class RecipeRepository(Protocol):
    async def get(self, recipe_id: UUID, user_id: UUID) -> Recipe | None: ...

    async def list_for_user(self, user_id: UUID) -> list[Recipe]: ...

    async def add(self, recipe: Recipe) -> None: ...

    async def update(self, recipe: Recipe) -> None: ...

    async def replace_ingredients(self, recipe: Recipe) -> None: ...

    async def soft_delete(self, recipe_id: UUID, user_id: UUID) -> None: ...


class WaterRepository(Protocol):
    async def list_for_date(self, user_id: UUID, on: date) -> list[WaterLog]: ...

    async def total_for_date(self, user_id: UUID, on: date) -> Decimal: ...

    async def totals_for_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> dict[date, Decimal]: ...

    async def add(self, entry: WaterLog) -> None: ...

    async def delete(self, entry_id: UUID, user_id: UUID) -> None: ...


class NutritionSummaryRepository(Protocol):
    """Incrementally maintained daily totals — the diary history never scans raw rows."""

    async def rebuild_day(
        self,
        *,
        user_id: UUID,
        local_date: date,
        macros: MacroNutrients,
        water_ml: Decimal,
        entry_count: int,
        target_calories: Decimal | None,
    ) -> None:
        """Write the day's totals from freshly computed values.

        A full rewrite rather than a delta: a diary day holds tens of rows, recomputing
        it is one indexed read, and deltas drift the moment an edit is mis-signed.
        """
        ...

    async def get_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[DailyNutritionSummary]: ...

    async def register_complete_day(self, user_id: UUID, local_date: date) -> NutritionStreak: ...


class BarcodeLookupPort(Protocol):
    """External barcode resolution — Open Food Facts in production.

    Declared in the domain and implemented in infrastructure, so the use case can stay
    honest about the failure mode: an upstream that is slow, wrong, or absent.
    """

    async def lookup(self, barcode: str) -> ImportedFood | None: ...


@dataclass(frozen=True, slots=True)
class ImportedFood:
    """An external food, before it has been trusted enough to store."""

    barcode: str
    name: str
    brand_name: str | None
    macros: MacroNutrients
    serving_grams: Decimal | None = None
    serving_label: str | None = None
    is_liquid: bool = False
    micronutrients: dict[str, Decimal] | None = None
    source_updated_at: datetime | None = None
