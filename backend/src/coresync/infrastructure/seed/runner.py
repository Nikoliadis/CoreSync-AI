"""Idempotent reference-data seeder: the exercise catalog and the curated food table.

Run at deploy time, not on application startup — startup seeding races across replicas.
Every row is upserted on its deterministic id, so running it twice changes nothing and
running it after adding exercises or foods adds only those.

    python -m coresync.infrastructure.seed.runner
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.core.config import Settings, get_settings
from coresync.core.logging import configure_logging, get_logger
from coresync.domain.nutrition.entities import FoodSource, TrustTier
from coresync.infrastructure.database.models.catalog import (
    EquipmentModel,
    ExerciseCategoryModel,
    ExerciseEquipmentModel,
    ExerciseModel,
    ExerciseMuscleModel,
    MuscleGroupModel,
    MuscleModel,
)
from coresync.infrastructure.database.models.nutrition import FoodModel, FoodServingModel
from coresync.infrastructure.database.session import Database
from coresync.infrastructure.seed.exercises import EXERCISES
from coresync.infrastructure.seed.foods import GREEK_STAPLES, as_seed
from coresync.infrastructure.seed.reference import (
    CATEGORIES,
    EQUIPMENT,
    MUSCLE_GROUPS,
    MUSCLES,
    catalog_id,
)

logger = get_logger(__name__)

# Role weights when an exercise does not declare explicit percentages. A primary mover
# is worth three times a secondary; the seeder writes these so volume attribution has
# real numbers rather than implicit defaults scattered through query code.
PRIMARY_PCT = 60
SECONDARY_PCT = 20


class SeedError(RuntimeError):
    """A row referenced a slug that does not exist. Fail loudly, never silently skip."""


async def seed_catalog(session: AsyncSession) -> dict[str, int]:
    counts = {
        "muscle_groups": await _seed_muscle_groups(session),
        "muscles": await _seed_muscles(session),
        "equipment": await _seed_equipment(session),
        "categories": await _seed_categories(session),
    }
    counts["exercises"] = await _seed_exercises(session)
    counts["foods"] = await _seed_foods(session)
    await session.commit()
    return counts


async def _upsert(session: AsyncSession, model: type, rows: list[dict[str, Any]], key: str) -> int:
    if not rows:
        return 0
    stmt = pg_insert(model).values(rows)
    update = {c: stmt.excluded[c] for c in rows[0] if c not in ("id", key)}
    stmt = stmt.on_conflict_do_update(index_elements=[key], set_=update)
    await session.execute(stmt)
    return len(rows)


async def _seed_muscle_groups(session: AsyncSession) -> int:
    return await _upsert(
        session,
        MuscleGroupModel,
        [
            {
                "id": catalog_id("muscle_group", slug),
                "slug": slug,
                "name": name,
                "sort_order": order,
            }
            for slug, name, order in MUSCLE_GROUPS
        ],
        "slug",
    )


async def _seed_muscles(session: AsyncSession) -> int:
    groups = {slug for slug, _, _ in MUSCLE_GROUPS}
    rows = []
    for slug, name, group_slug in MUSCLES:
        if group_slug not in groups:
            raise SeedError(f"muscle '{slug}' references unknown group '{group_slug}'")
        rows.append(
            {
                "id": catalog_id("muscle", slug),
                "slug": slug,
                "name": name,
                "muscle_group_id": catalog_id("muscle_group", group_slug),
            }
        )
    return await _upsert(session, MuscleModel, rows, "slug")


async def _seed_equipment(session: AsyncSession) -> int:
    return await _upsert(
        session,
        EquipmentModel,
        [
            {
                "id": catalog_id("equipment", slug),
                "slug": slug,
                "name": name,
                "is_home_available": home,
            }
            for slug, name, home in EQUIPMENT
        ],
        "slug",
    )


async def _seed_categories(session: AsyncSession) -> int:
    return await _upsert(
        session,
        ExerciseCategoryModel,
        [
            {"id": catalog_id("category", slug), "slug": slug, "name": name, "sort_order": order}
            for slug, name, order in CATEGORIES
        ],
        "slug",
    )


async def _seed_exercises(session: AsyncSession) -> int:
    known_muscles = {slug for slug, _, _ in MUSCLES}
    known_equipment = {slug for slug, _, _ in EQUIPMENT}
    known_categories = {slug for slug, _, _ in CATEGORIES}

    exercise_rows: list[dict[str, Any]] = []
    muscle_links: list[dict[str, Any]] = []
    equipment_links: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    for row in EXERCISES:
        (
            slug,
            name,
            category,
            force,
            mechanic,
            difficulty,
            logging_type,
            unilateral,
            primary,
            secondary,
            equipment,
        ) = row

        if slug in seen_slugs:
            raise SeedError(f"duplicate exercise slug '{slug}'")
        seen_slugs.add(slug)
        if category not in known_categories:
            raise SeedError(f"exercise '{slug}' references unknown category '{category}'")

        exercise_id = catalog_id("exercise", slug)
        exercise_rows.append(
            {
                "id": exercise_id,
                "slug": slug,
                "name": name,
                "category_id": catalog_id("category", category),
                "owner_user_id": None,
                "force_type": force or None,
                "mechanic": mechanic or None,
                "difficulty": difficulty,
                "logging_type": logging_type or "weight_reps",
                "is_unilateral": unilateral,
                "is_verified": True,
            }
        )

        for role, column, pct in (
            ("primary", primary, PRIMARY_PCT),
            ("secondary", secondary, SECONDARY_PCT),
        ):
            for muscle_slug in filter(None, column.split("|")):
                if muscle_slug not in known_muscles:
                    raise SeedError(f"exercise '{slug}' references unknown muscle '{muscle_slug}'")
                muscle_links.append(
                    {
                        "exercise_id": exercise_id,
                        "muscle_id": catalog_id("muscle", muscle_slug),
                        "role": role,
                        "contribution_pct": pct,
                    }
                )

        for equipment_slug in filter(None, equipment.split("|")):
            if equipment_slug not in known_equipment:
                raise SeedError(
                    f"exercise '{slug}' references unknown equipment '{equipment_slug}'"
                )
            equipment_links.append(
                {
                    "exercise_id": exercise_id,
                    "equipment_id": catalog_id("equipment", equipment_slug),
                }
            )

    # Exercises first: the link tables have foreign keys into this one.
    stmt = pg_insert(ExerciseModel).values(exercise_rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["slug"],
            index_where=ExerciseModel.owner_user_id.is_(None),
            set_={
                c: stmt.excluded[c]
                for c in exercise_rows[0]
                if c not in ("id", "slug", "owner_user_id")
            },
        )
    )
    await session.flush()

    if muscle_links:
        link_stmt = pg_insert(ExerciseMuscleModel).values(muscle_links)
        await session.execute(
            link_stmt.on_conflict_do_update(
                index_elements=["exercise_id", "muscle_id"],
                set_={
                    "role": link_stmt.excluded.role,
                    "contribution_pct": link_stmt.excluded.contribution_pct,
                },
            )
        )
    if equipment_links:
        equip_stmt = pg_insert(ExerciseEquipmentModel).values(equipment_links)
        await session.execute(
            equip_stmt.on_conflict_do_nothing(index_elements=["exercise_id", "equipment_id"])
        )

    await session.flush()
    return len(exercise_rows)


async def _seed_foods(session: AsyncSession) -> int:
    """Curated tier-1 foods and their household servings.

    Ids are derived from the name, so re-running updates the numbers in place rather
    than creating a second Γιαούρτι. That also means renaming a food in the table
    creates a new row: intentional, since the diary snapshots what it logged and the
    old row stays valid for anyone who already ate it.
    """
    food_rows: list[dict[str, Any]] = []
    serving_rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in GREEK_STAPLES:
        food = as_seed(raw)
        if food.name in seen:
            raise SeedError(f"duplicate food name '{food.name}'")
        seen.add(food.name)

        food_id = catalog_id("food", food.name)
        food_rows.append(
            {
                "id": food_id,
                "name": food.name,
                "brand_id": None,
                "owner_user_id": None,
                "source": FoodSource.CURATED.value,
                "trust_tier": int(TrustTier.CURATED),
                "calories_per_100g": food.calories,
                "protein_per_100g": food.protein,
                "carbs_per_100g": food.carbs,
                "fat_per_100g": food.fat,
                "alcohol_per_100g": food.alcohol,
                "is_verified": True,
                "is_liquid": food.is_liquid,
            }
        )
        for index, (label, grams) in enumerate(food.servings):
            serving_rows.append(
                {
                    "id": catalog_id("food_serving", f"{food.name}|{label}"),
                    "food_id": food_id,
                    "label": label,
                    "grams": grams,
                    "is_default": index == 0,
                }
            )

    stmt = pg_insert(FoodModel).values(food_rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"],
            # `usage_count` is deliberately absent: it is earned by people logging the
            # food and feeds search ranking. A redeploy must not reset it to zero.
            set_={
                c: stmt.excluded[c]
                for c in food_rows[0]
                if c not in ("id", "owner_user_id", "brand_id")
            },
        )
    )
    await session.flush()

    serving_stmt = pg_insert(FoodServingModel).values(serving_rows)
    await session.execute(
        serving_stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "label": serving_stmt.excluded.label,
                "grams": serving_stmt.excluded.grams,
                "is_default": serving_stmt.excluded.is_default,
            },
        )
    )

    # Drop servings that used to be curated but are no longer in the table. The diary
    # holds its own gram snapshot and the reference is ON DELETE SET NULL, so an entry
    # logged against a retired serving keeps its numbers.
    await session.execute(
        delete(FoodServingModel).where(
            FoodServingModel.food_id.in_([row["id"] for row in food_rows]),
            FoodServingModel.id.notin_([row["id"] for row in serving_rows]),
        )
    )

    await session.flush()
    return len(food_rows)


async def catalog_is_seeded(session: AsyncSession) -> bool:
    stmt = select(ExerciseModel.id).where(ExerciseModel.owner_user_id.is_(None)).limit(1)
    return (await session.execute(stmt)).first() is not None


async def _main(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    configure_logging()
    database = Database(resolved)
    async with database.session_factory() as session:
        counts = await seed_catalog(session)
    await database.dispose()
    logger.info("catalog_seeded", **counts)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
