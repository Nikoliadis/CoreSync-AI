"""Repository ports for nutrition."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from coresync.domain.nutrition.entities import (
    DiaryEntry,
    Food,
    FoodServing,
    FoodSubmission,
    Recipe,
    WaterLog,
)


class FoodRepository(Protocol):
    async def get(self, food_id: UUID, user_id: UUID) -> Food | None:
        """One food, if it is public or owned by this user.

        ``user_id`` is required rather than optional: a custom food is private, and a
        lookup that forgets to scope it leaks one user's food list to another.
        """
        ...

    async def get_many(self, food_ids: Sequence[UUID], user_id: UUID) -> dict[UUID, Food]: ...

    async def search(
        self, *, query: str, user_id: UUID, limit: int, offset: int
    ) -> tuple[list[Food], int]:
        """Ranked search over public foods plus this user's own.

        Ranking is trust tier first, then exactness, then popularity — a wrong number
        is worse than an unfamiliar name (docs/15, food data quality).
        """
        ...

    async def by_barcode(self, barcode: str, user_id: UUID) -> Food | None: ...

    async def recent_for_user(self, user_id: UUID, *, limit: int) -> list[Food]:
        """What this user logs often, from the diary rather than a separate table."""
        ...

    async def add(self, food: Food) -> None: ...

    async def update(self, food: Food) -> None:
        """Only a food the caller owns. Curated rows are never editable here."""
        ...

    async def delete(self, food_id: UUID, user_id: UUID) -> None: ...

    async def add_servings(self, servings: Sequence[FoodServing]) -> None: ...

    async def add_barcode(self, food_id: UUID, barcode: str) -> None: ...

    async def nutrients_for(self, food_id: UUID) -> list[tuple[str, str, str, Decimal]]: ...

    async def replace_servings(self, food_id: UUID, servings: Sequence[FoodServing]) -> None: ...

    async def list_favourites(self, user_id: UUID) -> list[Food]: ...

    async def add_favourite(self, user_id: UUID, food_id: UUID) -> None: ...

    async def remove_favourite(self, user_id: UUID, food_id: UUID) -> None: ...

    async def increment_usage(self, food_id: UUID) -> None:
        """Popularity, which breaks search ties below trust tier."""
        ...


class DiaryRepository(Protocol):
    async def entries_for_day(self, user_id: UUID, on: date) -> list[DiaryEntry]: ...

    async def entries_for_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[DiaryEntry]: ...

    async def get(self, entry_id: UUID, user_id: UUID) -> DiaryEntry | None: ...

    async def add(self, entry: DiaryEntry) -> None: ...

    async def update(self, entry: DiaryEntry) -> None: ...

    async def delete(self, entry_id: UUID, user_id: UUID) -> None:
        """Soft delete — history is corrected by replacement, never by removal."""
        ...


class WaterRepository(Protocol):
    async def logs_for_day(self, user_id: UUID, on: date) -> list[WaterLog]: ...

    async def logs_for_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[WaterLog]: ...

    async def add(self, log: WaterLog) -> None: ...

    async def delete(self, log_id: UUID, user_id: UUID) -> None: ...


class RecipeRepository(Protocol):
    async def get(self, recipe_id: UUID, user_id: UUID) -> Recipe | None: ...

    async def list_for_user(self, user_id: UUID) -> list[Recipe]: ...

    async def add(self, recipe: Recipe) -> None: ...

    async def update(self, recipe: Recipe) -> None: ...

    async def replace_ingredients(self, recipe: Recipe) -> None: ...

    async def delete(self, recipe_id: UUID, user_id: UUID) -> None: ...


class NutritionSummaryRepository(Protocol):
    """Derived per-day totals. Nothing here is a source of truth.

    `DailySummary` lives in the application layer, so it is passed in rather than
    imported: the port describes the shape of the store, not the shape of the caller.
    """

    async def upsert(self, user_id: UUID, summary: object) -> None: ...

    async def range(self, user_id: UUID, *, date_from: date, date_to: date) -> list[Any]: ...

    async def logged_days(self, user_id: UUID, *, since: date) -> list[date]:
        """Days with at least one diary entry. The streak's raw material."""
        ...

    async def days_with_activity(self, user_id: UUID, *, since: date) -> list[date]:
        """Every day a rebuild would need to touch — diary or water."""
        ...


class FoodSubmissionRepository(Protocol):
    """The moderation queue. Admin-scoped: these reads deliberately take no user id."""

    async def add(self, submission: FoodSubmission) -> None: ...

    async def update(self, submission: FoodSubmission) -> None: ...

    async def get(self, submission_id: UUID) -> FoodSubmission | None: ...

    async def pending_for_food(self, food_id: UUID) -> FoodSubmission | None: ...

    async def queue(self, *, status: Any, limit: int) -> list[Any]: ...

    async def food_for(self, food_id: UUID) -> Food | None:
        """Unscoped read — the reviewer is not the owner, by definition."""
        ...

    async def publish(self, food_id: UUID, *, trust_tier: Any) -> None:
        """Make a private food public at the given tier."""
        ...
