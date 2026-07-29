"""Repository ports for the exercise catalog.

Catalog reads take ``user_id`` even though most of the data is global: every query has
to union the global catalog with *that user's* custom exercises, and must never surface
another user's. Passing the scope explicitly is what makes that impossible to forget
(docs/05 §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from coresync.domain.catalog.entities import (
    Equipment,
    Exercise,
    ExerciseCategory,
    Muscle,
    MuscleGroup,
)


@dataclass(frozen=True, slots=True)
class ExerciseFilter:
    """Search and filter criteria for the catalog listing."""

    query: str | None = None
    muscle_group_slugs: tuple[str, ...] = ()
    muscle_slugs: tuple[str, ...] = ()
    equipment_slugs: tuple[str, ...] = ()
    category_slugs: tuple[str, ...] = ()
    difficulty: str | None = None
    logging_type: str | None = None
    favorites_only: bool = False
    custom_only: bool = False
    include_custom: bool = True


class ExerciseRepository(Protocol):
    async def get(self, exercise_id: UUID, user_id: UUID) -> Exercise | None:
        """One exercise, if it is global or owned by this user."""
        ...

    async def get_many(self, exercise_ids: list[UUID], user_id: UUID) -> list[Exercise]: ...

    async def search(
        self,
        user_id: UUID,
        criteria: ExerciseFilter,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Exercise], int]:
        """Returns the page and the total count for the filter."""
        ...

    async def add(self, exercise: Exercise) -> None: ...

    async def update(self, exercise: Exercise) -> None: ...

    async def soft_delete(self, exercise_id: UUID, user_id: UUID) -> None: ...

    async def add_favorite(self, user_id: UUID, exercise_id: UUID) -> None: ...

    async def remove_favorite(self, user_id: UUID, exercise_id: UUID) -> None: ...


class CatalogReferenceRepository(Protocol):
    """Muscles, equipment and categories: seeded, read-mostly, aggressively cacheable."""

    async def list_muscle_groups(self) -> list[MuscleGroup]: ...

    async def list_muscles(self) -> list[Muscle]: ...

    async def list_equipment(self) -> list[Equipment]: ...

    async def list_categories(self) -> list[ExerciseCategory]: ...

    async def category_by_slug(self, slug: str) -> ExerciseCategory | None: ...

    async def muscle_ids_by_slug(self, slugs: list[str]) -> dict[str, UUID]: ...

    async def equipment_ids_by_slug(self, slugs: list[str]) -> dict[str, UUID]: ...

    async def muscle_group_contributions(
        self, exercise_ids: list[UUID]
    ) -> dict[UUID, dict[str, Decimal]]:
        """Per-exercise muscle-group shares, normalised to sum to 1.

        Used to split a completed session's volume across the groups it trained. Lives on
        the catalog port rather than the workout one because the split is a property of
        the exercise, not of the workout that used it.
        """
        ...

    async def primary_muscle_groups(self, exercise_ids: list[UUID]) -> dict[UUID, list[str]]:
        """Primary movers only, for hard set counts per muscle group."""
        ...
