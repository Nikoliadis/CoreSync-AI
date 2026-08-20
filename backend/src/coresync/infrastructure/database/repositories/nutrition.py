"""SQLAlchemy repositories for nutrition."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import Select, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.nutrition.entities import (
    DiaryEntry,
    Food,
    FoodServing,
    FoodSource,
    Macros,
    MealType,
    Recipe,
    RecipeIngredient,
    TrustTier,
    WaterLog,
)
from coresync.infrastructure.database.models.nutrition import (
    DiaryEntryModel,
    FoodBarcodeModel,
    FoodModel,
    FoodServingModel,
    RecipeIngredientModel,
    RecipeModel,
    WaterLogModel,
)

# Matches the generated column and the trigram index in migration 0008. Without the
# same wrapper on the query side, neither index is used and Greek searches typed
# without accents silently miss.
_UNACCENT = func.immutable_unaccent


def _serving_to_entity(model: FoodServingModel) -> FoodServing:
    return FoodServing(
        id=model.id,
        food_id=model.food_id,
        label=model.label,
        grams=model.grams,
        is_default=model.is_default,
    )


def _food_to_entity(model: FoodModel) -> Food:
    return Food(
        id=model.id,
        name=model.name,
        source=FoodSource(model.source),
        trust_tier=TrustTier(model.trust_tier),
        calories_per_100g=model.calories_per_100g,
        protein_per_100g=model.protein_per_100g,
        carbs_per_100g=model.carbs_per_100g,
        fat_per_100g=model.fat_per_100g,
        alcohol_per_100g=model.alcohol_per_100g,
        brand_id=model.brand_id,
        owner_user_id=model.owner_user_id,
        is_verified=model.is_verified,
        is_liquid=model.is_liquid,
        usage_count=model.usage_count,
        servings=[_serving_to_entity(s) for s in model.servings],
        created_at=model.created_at,
    )


def _diary_to_entity(model: DiaryEntryModel) -> DiaryEntry:
    return DiaryEntry(
        id=model.id,
        user_id=model.user_id,
        local_date=model.local_date,
        meal_type=MealType(model.meal_type),
        quantity=model.quantity,
        total_grams=model.total_grams,
        macros=Macros(
            calories=model.calories,
            protein_g=model.protein_g,
            carbs_g=model.carbs_g,
            fat_g=model.fat_g,
            alcohol_g=model.alcohol_g,
        ),
        food_id=model.food_id,
        recipe_id=model.recipe_id,
        serving_id=model.serving_id,
        display_name=model.display_name,
        micronutrients=model.micronutrients,
        logged_at=model.logged_at,
    )


class SqlAlchemyFoodRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _visible(self, user_id: UUID) -> Select[tuple[FoodModel]]:
        """Public foods plus this user's own. Never anyone else's custom foods."""
        return select(FoodModel).where(
            FoodModel.deleted_at.is_(None),
            or_(FoodModel.owner_user_id.is_(None), FoodModel.owner_user_id == user_id),
        )

    async def get(self, food_id: UUID, user_id: UUID) -> Food | None:
        stmt = self._visible(user_id).where(FoodModel.id == food_id)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _food_to_entity(model) if model else None

    async def get_many(self, food_ids: Sequence[UUID], user_id: UUID) -> dict[UUID, Food]:
        if not food_ids:
            return {}
        stmt = self._visible(user_id).where(FoodModel.id.in_(list(food_ids)))
        return {m.id: _food_to_entity(m) for m in (await self._session.execute(stmt)).scalars()}

    async def search(
        self, *, query: str, user_id: UUID, limit: int, offset: int
    ) -> tuple[list[Food], int]:
        cleaned = query.strip()
        base = self._visible(user_id)

        if cleaned:
            needle = _UNACCENT(cleaned)
            # Full-text for whole words, trigram for typos and partial words. Either
            # alone misses an obvious case: full-text will not match "yogur", and
            # trigram ranks poorly on multi-word names.
            base = base.where(
                or_(
                    FoodModel.search_vector.op("@@")(func.plainto_tsquery("simple", needle)),
                    _UNACCENT(FoodModel.name).op("%")(needle),
                )
            )

        total = (
            await self._session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()

        # Ranking, in this order and for this reason:
        #   1. a user's own foods — they made it deliberately, it is usually the one
        #   2. exact name match — "banana" must not return "banana bread" first
        #   3. trust tier — a wrong number is worse than an unfamiliar name
        #   4. popularity, then similarity, to break the remaining ties
        ordering = []
        if cleaned:
            needle = _UNACCENT(cleaned)
            ordering = [
                desc(FoodModel.owner_user_id == user_id),
                desc(func.lower(_UNACCENT(FoodModel.name)) == func.lower(needle)),
                FoodModel.trust_tier.asc(),
                desc(func.similarity(_UNACCENT(FoodModel.name), needle)),
                FoodModel.usage_count.desc(),
            ]
        else:
            ordering = [FoodModel.trust_tier.asc(), FoodModel.usage_count.desc()]

        stmt = base.order_by(*ordering).limit(limit).offset(offset)
        rows = list((await self._session.execute(stmt)).scalars())
        return [_food_to_entity(m) for m in rows], int(total or 0)

    async def by_barcode(self, barcode: str, user_id: UUID) -> Food | None:
        stmt = (
            self._visible(user_id)
            .join(FoodBarcodeModel, FoodBarcodeModel.food_id == FoodModel.id)
            .where(FoodBarcodeModel.barcode == barcode.strip())
        )
        model = (await self._session.execute(stmt)).scalars().first()
        return _food_to_entity(model) if model else None

    async def recent_for_user(self, user_id: UUID, *, limit: int) -> list[Food]:
        """Derived from the diary rather than a separate table (docs/03 §7)."""
        recent = (
            select(DiaryEntryModel.food_id, func.max(DiaryEntryModel.logged_at).label("last"))
            .where(
                DiaryEntryModel.user_id == user_id,
                DiaryEntryModel.food_id.is_not(None),
                DiaryEntryModel.deleted_at.is_(None),
            )
            .group_by(DiaryEntryModel.food_id)
            .order_by(desc("last"))
            .limit(limit)
            .subquery()
        )

        stmt = (
            select(FoodModel)
            .join(recent, recent.c.food_id == FoodModel.id)
            .where(FoodModel.deleted_at.is_(None))
            .order_by(desc(recent.c.last))
        )
        return [_food_to_entity(m) for m in (await self._session.execute(stmt)).scalars()]

    async def add(self, food: Food) -> None:
        self._session.add(
            FoodModel(
                id=food.id,
                name=food.name,
                brand_id=food.brand_id,
                owner_user_id=food.owner_user_id,
                source=food.source.value,
                trust_tier=int(food.trust_tier),
                calories_per_100g=food.calories_per_100g,
                protein_per_100g=food.protein_per_100g,
                carbs_per_100g=food.carbs_per_100g,
                fat_per_100g=food.fat_per_100g,
                alcohol_per_100g=food.alcohol_per_100g,
                is_verified=food.is_verified,
                is_liquid=food.is_liquid,
                usage_count=food.usage_count,
            )
        )
        await self._session.flush()

    async def add_servings(self, servings: Sequence[FoodServing]) -> None:
        if not servings:
            return
        self._session.add_all(
            [
                FoodServingModel(
                    id=s.id,
                    food_id=s.food_id,
                    label=s.label,
                    grams=s.grams,
                    is_default=s.is_default,
                )
                for s in servings
            ]
        )
        await self._session.flush()

    async def increment_usage(self, food_id: UUID) -> None:
        # In SQL rather than read-modify-write: two people logging the same food at the
        # same moment would otherwise each read the old count and store the same value.
        await self._session.execute(
            update(FoodModel)
            .where(FoodModel.id == food_id)
            .values(usage_count=FoodModel.usage_count + 1)
        )


class SqlAlchemyDiaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def entries_for_day(self, user_id: UUID, on: date) -> list[DiaryEntry]:
        stmt = (
            select(DiaryEntryModel)
            .where(
                DiaryEntryModel.user_id == user_id,
                DiaryEntryModel.local_date == on,
                DiaryEntryModel.deleted_at.is_(None),
            )
            .order_by(DiaryEntryModel.logged_at)
        )
        return [_diary_to_entity(m) for m in (await self._session.execute(stmt)).scalars()]

    async def entries_for_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[DiaryEntry]:
        stmt = (
            select(DiaryEntryModel)
            .where(
                DiaryEntryModel.user_id == user_id,
                DiaryEntryModel.local_date >= date_from,
                DiaryEntryModel.local_date <= date_to,
                DiaryEntryModel.deleted_at.is_(None),
            )
            .order_by(DiaryEntryModel.local_date, DiaryEntryModel.logged_at)
        )
        return [_diary_to_entity(m) for m in (await self._session.execute(stmt)).scalars()]

    async def get(self, entry_id: UUID, user_id: UUID) -> DiaryEntry | None:
        stmt = select(DiaryEntryModel).where(
            DiaryEntryModel.id == entry_id,
            DiaryEntryModel.user_id == user_id,
            DiaryEntryModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _diary_to_entity(model) if model else None

    async def add(self, entry: DiaryEntry) -> None:
        self._session.add(
            DiaryEntryModel(
                id=entry.id,
                user_id=entry.user_id,
                local_date=entry.local_date,
                meal_type=entry.meal_type.value,
                food_id=entry.food_id,
                recipe_id=entry.recipe_id,
                serving_id=entry.serving_id,
                quantity=entry.quantity,
                total_grams=entry.total_grams,
                display_name=entry.display_name,
                # The snapshot. Never recomputed on read.
                calories=entry.macros.calories,
                protein_g=entry.macros.protein_g,
                carbs_g=entry.macros.carbs_g,
                fat_g=entry.macros.fat_g,
                alcohol_g=entry.macros.alcohol_g,
                micronutrients=entry.micronutrients,
            )
        )
        await self._session.flush()

    async def update(self, entry: DiaryEntry) -> None:
        stmt = select(DiaryEntryModel).where(
            DiaryEntryModel.id == entry.id,
            DiaryEntryModel.user_id == entry.user_id,
            DiaryEntryModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return
        model.meal_type = entry.meal_type.value
        model.quantity = entry.quantity
        model.total_grams = entry.total_grams
        model.calories = entry.macros.calories
        model.protein_g = entry.macros.protein_g
        model.carbs_g = entry.macros.carbs_g
        model.fat_g = entry.macros.fat_g
        model.alcohol_g = entry.macros.alcohol_g
        await self._session.flush()

    async def delete(self, entry_id: UUID, user_id: UUID) -> None:
        await self._session.execute(
            update(DiaryEntryModel)
            .where(
                DiaryEntryModel.id == entry_id,
                DiaryEntryModel.user_id == user_id,
                DiaryEntryModel.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(tz=UTC))
        )
        await self._session.flush()


class SqlAlchemyWaterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def logs_for_day(self, user_id: UUID, on: date) -> list[WaterLog]:
        stmt = (
            select(WaterLogModel)
            .where(WaterLogModel.user_id == user_id, WaterLogModel.local_date == on)
            .order_by(WaterLogModel.logged_at)
        )
        return [
            WaterLog(
                id=m.id,
                user_id=m.user_id,
                local_date=m.local_date,
                millilitres=m.millilitres,
                logged_at=m.logged_at,
            )
            for m in (await self._session.execute(stmt)).scalars()
        ]

    async def add(self, log: WaterLog) -> None:
        self._session.add(
            WaterLogModel(
                id=log.id,
                user_id=log.user_id,
                local_date=log.local_date,
                millilitres=log.millilitres,
            )
        )
        await self._session.flush()

    async def delete(self, log_id: UUID, user_id: UUID) -> None:
        model = (
            await self._session.execute(
                select(WaterLogModel).where(
                    WaterLogModel.id == log_id, WaterLogModel.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()


class SqlAlchemyRecipeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, model: RecipeModel) -> Recipe:
        return Recipe(
            id=model.id,
            user_id=model.user_id,
            name=model.name,
            servings_count=model.servings_count,
            notes=model.notes,
            ingredients=[
                RecipeIngredient(id=i.id, recipe_id=i.recipe_id, food_id=i.food_id, grams=i.grams)
                for i in sorted(model.ingredients, key=lambda i: i.position)
            ],
        )

    async def get(self, recipe_id: UUID, user_id: UUID) -> Recipe | None:
        stmt = select(RecipeModel).where(
            RecipeModel.id == recipe_id,
            RecipeModel.user_id == user_id,
            RecipeModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_for_user(self, user_id: UUID) -> list[Recipe]:
        stmt = (
            select(RecipeModel)
            .where(RecipeModel.user_id == user_id, RecipeModel.deleted_at.is_(None))
            .order_by(RecipeModel.name)
        )
        return [self._to_entity(m) for m in (await self._session.execute(stmt)).scalars()]

    async def add(self, recipe: Recipe) -> None:
        self._session.add(
            RecipeModel(
                id=recipe.id,
                user_id=recipe.user_id,
                name=recipe.name,
                notes=recipe.notes,
                servings_count=recipe.servings_count,
            )
        )
        await self._session.flush()

    async def replace_ingredients(self, recipe: Recipe) -> None:
        existing = (
            await self._session.execute(
                select(RecipeIngredientModel).where(RecipeIngredientModel.recipe_id == recipe.id)
            )
        ).scalars()
        for row in existing:
            await self._session.delete(row)
        # Flushed before reinserting: without it the delete and the insert race inside
        # the same transaction and a unique constraint can fire on rows being replaced.
        await self._session.flush()

        self._session.add_all(
            [
                RecipeIngredientModel(
                    id=ingredient.id,
                    recipe_id=recipe.id,
                    food_id=ingredient.food_id,
                    grams=ingredient.grams,
                    position=position,
                )
                for position, ingredient in enumerate(recipe.ingredients)
            ]
        )
        await self._session.flush()

    async def delete(self, recipe_id: UUID, user_id: UUID) -> None:
        await self._session.execute(
            update(RecipeModel)
            .where(
                RecipeModel.id == recipe_id,
                RecipeModel.user_id == user_id,
                RecipeModel.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(tz=UTC))
        )
        await self._session.flush()


__all__ = [
    "SqlAlchemyDiaryRepository",
    "SqlAlchemyFoodRepository",
    "SqlAlchemyRecipeRepository",
    "SqlAlchemyWaterRepository",
]
