"""SQLAlchemy implementations of the catalog repository ports."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.catalog.entities import (
    Equipment,
    Exercise,
    ExerciseCategory,
    Muscle,
    MuscleGroup,
)
from coresync.domain.catalog.repositories import ExerciseFilter
from coresync.infrastructure.database.mappers import (
    EquipmentMapper,
    ExerciseCategoryMapper,
    ExerciseMapper,
    MuscleGroupMapper,
    MuscleMapper,
)
from coresync.infrastructure.database.models.catalog import (
    EquipmentModel,
    ExerciseCategoryModel,
    ExerciseEquipmentModel,
    ExerciseInstructionModel,
    ExerciseModel,
    ExerciseMuscleModel,
    MuscleGroupModel,
    MuscleModel,
    UserFavoriteExerciseModel,
)


class SqlAlchemyExerciseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _visible(self, user_id: UUID) -> Select[tuple[ExerciseModel]]:
        """Global catalog plus this user's own. Never anyone else's.

        Every read starts here, so there is no query shape in which one user's custom
        exercises can reach another.
        """
        return select(ExerciseModel).where(
            ExerciseModel.deleted_at.is_(None),
            or_(
                ExerciseModel.owner_user_id.is_(None),
                ExerciseModel.owner_user_id == user_id,
            ),
        )

    async def _favorite_ids(self, user_id: UUID, exercise_ids: list[UUID]) -> set[UUID]:
        if not exercise_ids:
            return set()
        stmt = select(UserFavoriteExerciseModel.exercise_id).where(
            UserFavoriteExerciseModel.user_id == user_id,
            UserFavoriteExerciseModel.exercise_id.in_(exercise_ids),
        )
        return set((await self._session.execute(stmt)).scalars().all())

    async def get(self, exercise_id: UUID, user_id: UUID) -> Exercise | None:
        stmt = self._visible(user_id).where(ExerciseModel.id == exercise_id)
        model = (await self._session.execute(stmt)).unique().scalar_one_or_none()
        if model is None:
            return None
        favorites = await self._favorite_ids(user_id, [exercise_id])
        return ExerciseMapper.to_entity(model, is_favorite=exercise_id in favorites)

    async def get_many(self, exercise_ids: list[UUID], user_id: UUID) -> list[Exercise]:
        if not exercise_ids:
            return []
        stmt = self._visible(user_id).where(ExerciseModel.id.in_(exercise_ids))
        models = (await self._session.execute(stmt)).unique().scalars().all()
        favorites = await self._favorite_ids(user_id, exercise_ids)
        return [ExerciseMapper.to_entity(m, is_favorite=m.id in favorites) for m in models]

    async def search(
        self,
        user_id: UUID,
        criteria: ExerciseFilter,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Exercise], int]:
        stmt = self._visible(user_id)

        if criteria.custom_only:
            stmt = stmt.where(ExerciseModel.owner_user_id == user_id)
        elif not criteria.include_custom:
            stmt = stmt.where(ExerciseModel.owner_user_id.is_(None))

        if criteria.query:
            # Trigram similarity rather than FTS alone: lifters type "bech pres" and
            # still expect the bench press. `ILIKE` seeds the cheap prefix case.
            pattern = f"%{criteria.query.strip()}%"
            stmt = stmt.where(
                or_(
                    ExerciseModel.name.ilike(pattern),
                    func.similarity(ExerciseModel.name, criteria.query) > 0.25,
                )
            )

        if criteria.difficulty:
            stmt = stmt.where(ExerciseModel.difficulty == criteria.difficulty)
        if criteria.logging_type:
            stmt = stmt.where(ExerciseModel.logging_type == criteria.logging_type)

        if criteria.category_slugs:
            stmt = stmt.where(
                ExerciseModel.category_id.in_(
                    select(ExerciseCategoryModel.id).where(
                        ExerciseCategoryModel.slug.in_(criteria.category_slugs)
                    )
                )
            )

        if criteria.muscle_group_slugs:
            # Primary movers only. Filtering on "chest" should not return every pressing
            # accessory that happens to involve the chest as a stabiliser.
            stmt = stmt.where(
                ExerciseModel.id.in_(
                    select(ExerciseMuscleModel.exercise_id)
                    .join(MuscleModel, MuscleModel.id == ExerciseMuscleModel.muscle_id)
                    .join(MuscleGroupModel, MuscleGroupModel.id == MuscleModel.muscle_group_id)
                    .where(
                        MuscleGroupModel.slug.in_(criteria.muscle_group_slugs),
                        ExerciseMuscleModel.role == "primary",
                    )
                )
            )

        if criteria.muscle_slugs:
            stmt = stmt.where(
                ExerciseModel.id.in_(
                    select(ExerciseMuscleModel.exercise_id)
                    .join(MuscleModel, MuscleModel.id == ExerciseMuscleModel.muscle_id)
                    .where(MuscleModel.slug.in_(criteria.muscle_slugs))
                )
            )

        if criteria.equipment_slugs:
            stmt = stmt.where(
                ExerciseModel.id.in_(
                    select(ExerciseEquipmentModel.exercise_id)
                    .join(
                        EquipmentModel,
                        EquipmentModel.id == ExerciseEquipmentModel.equipment_id,
                    )
                    .where(EquipmentModel.slug.in_(criteria.equipment_slugs))
                )
            )

        if criteria.favorites_only:
            stmt = stmt.where(
                ExerciseModel.id.in_(
                    select(UserFavoriteExerciseModel.exercise_id).where(
                        UserFavoriteExerciseModel.user_id == user_id
                    )
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()

        # A user's own exercises first — they created them because the catalog lacked
        # something, so burying them under 600 global entries would be perverse.
        page_stmt = (
            stmt.order_by(
                ExerciseModel.owner_user_id.is_(None),
                ExerciseModel.name,
            )
            .limit(limit)
            .offset(offset)
        )
        models = (await self._session.execute(page_stmt)).unique().scalars().all()
        favorites = await self._favorite_ids(user_id, [m.id for m in models])
        return (
            [ExerciseMapper.to_entity(m, is_favorite=m.id in favorites) for m in models],
            int(total),
        )

    async def add(self, exercise: Exercise) -> None:
        model = ExerciseMapper.to_model(exercise)
        model.muscles = [
            ExerciseMuscleModel(
                exercise_id=exercise.id,
                muscle_id=m.muscle_id,
                role=m.role.value,
                contribution_pct=m.contribution_pct,
            )
            for m in exercise.muscles
        ]
        model.equipment = [
            ExerciseEquipmentModel(exercise_id=exercise.id, equipment_id=equipment_id)
            for equipment_id in exercise.equipment_ids
        ]
        model.instructions = [
            ExerciseInstructionModel(
                id=_instruction_id(exercise.id, step),
                exercise_id=exercise.id,
                step_number=step,
                body=body,
            )
            for step, body in enumerate(exercise.instructions, start=1)
        ]
        self._session.add(model)
        await self._session.flush()

    async def update(self, exercise: Exercise) -> None:
        model = await self._session.get(ExerciseModel, exercise.id)
        if model is None:
            raise ValueError(f"exercise {exercise.id} does not exist")
        ExerciseMapper.apply(exercise, model)
        model.muscles = [
            ExerciseMuscleModel(
                exercise_id=exercise.id,
                muscle_id=m.muscle_id,
                role=m.role.value,
                contribution_pct=m.contribution_pct,
            )
            for m in exercise.muscles
        ]
        model.equipment = [
            ExerciseEquipmentModel(exercise_id=exercise.id, equipment_id=equipment_id)
            for equipment_id in exercise.equipment_ids
        ]
        await self._session.flush()

    async def soft_delete(self, exercise_id: UUID, user_id: UUID) -> None:
        model = await self._session.get(ExerciseModel, exercise_id)
        # Ownership is re-checked here rather than trusted from the caller: a soft delete
        # is the one write where getting scoping wrong is silent.
        if model is None or model.owner_user_id != user_id:
            raise ValueError(f"exercise {exercise_id} is not deletable by {user_id}")
        model.deleted_at = func.now()
        await self._session.flush()

    async def add_favorite(self, user_id: UUID, exercise_id: UUID) -> None:
        stmt = (
            pg_insert(UserFavoriteExerciseModel)
            .values(user_id=user_id, exercise_id=exercise_id)
            .on_conflict_do_nothing(index_elements=["user_id", "exercise_id"])
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def remove_favorite(self, user_id: UUID, exercise_id: UUID) -> None:
        model = await self._session.get(UserFavoriteExerciseModel, (user_id, exercise_id))
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()


class SqlAlchemyCatalogReferenceRepository:
    """Seeded reference data. Small, static, and read on nearly every catalog request."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_muscle_groups(self) -> list[MuscleGroup]:
        stmt = select(MuscleGroupModel).order_by(MuscleGroupModel.sort_order, MuscleGroupModel.name)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [MuscleGroupMapper.to_entity(m) for m in rows]

    async def list_muscles(self) -> list[Muscle]:
        stmt = select(MuscleModel).order_by(MuscleModel.name)
        rows = (await self._session.execute(stmt)).unique().scalars().all()
        return [MuscleMapper.to_entity(m) for m in rows]

    async def list_equipment(self) -> list[Equipment]:
        stmt = select(EquipmentModel).order_by(EquipmentModel.name)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [EquipmentMapper.to_entity(m) for m in rows]

    async def list_categories(self) -> list[ExerciseCategory]:
        stmt = select(ExerciseCategoryModel).order_by(
            ExerciseCategoryModel.sort_order, ExerciseCategoryModel.name
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [ExerciseCategoryMapper.to_entity(m) for m in rows]

    async def category_by_slug(self, slug: str) -> ExerciseCategory | None:
        stmt = select(ExerciseCategoryModel).where(ExerciseCategoryModel.slug == slug)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return ExerciseCategoryMapper.to_entity(model) if model else None

    async def muscle_ids_by_slug(self, slugs: list[str]) -> dict[str, UUID]:
        if not slugs:
            return {}
        stmt = select(MuscleModel.slug, MuscleModel.id).where(MuscleModel.slug.in_(slugs))
        return dict((await self._session.execute(stmt)).all())

    async def equipment_ids_by_slug(self, slugs: list[str]) -> dict[str, UUID]:
        if not slugs:
            return {}
        stmt = select(EquipmentModel.slug, EquipmentModel.id).where(EquipmentModel.slug.in_(slugs))
        return dict((await self._session.execute(stmt)).all())

    async def muscle_group_contributions(
        self, exercise_ids: list[UUID]
    ) -> dict[UUID, dict[str, Decimal]]:
        """Per-exercise muscle-group shares, normalised to sum to 1.

        Used to split a set's volume across the groups it trained. Where an exercise has
        no declared percentages, the roles supply defaults — a primary mover is worth
        three times a secondary and six times a stabiliser.
        """
        if not exercise_ids:
            return {}
        role_weight = {"primary": Decimal(6), "secondary": Decimal(2), "stabilizer": Decimal(1)}
        stmt = (
            select(
                ExerciseMuscleModel.exercise_id,
                MuscleGroupModel.slug,
                ExerciseMuscleModel.role,
                ExerciseMuscleModel.contribution_pct,
            )
            .join(MuscleModel, MuscleModel.id == ExerciseMuscleModel.muscle_id)
            .join(MuscleGroupModel, MuscleGroupModel.id == MuscleModel.muscle_group_id)
            .where(ExerciseMuscleModel.exercise_id.in_(exercise_ids))
        )
        raw: dict[UUID, dict[str, Decimal]] = {}
        for exercise_id, group_slug, role, pct in (await self._session.execute(stmt)).all():
            weight = Decimal(pct) if pct is not None else role_weight.get(role, Decimal(1))
            bucket = raw.setdefault(exercise_id, {})
            bucket[group_slug] = bucket.get(group_slug, Decimal(0)) + weight

        normalised: dict[UUID, dict[str, Decimal]] = {}
        for exercise_id, groups in raw.items():
            total = sum(groups.values(), Decimal(0))
            if total <= 0:
                continue
            normalised[exercise_id] = {g: v / total for g, v in groups.items()}
        return normalised

    async def primary_muscle_groups(self, exercise_ids: list[UUID]) -> dict[UUID, list[str]]:
        if not exercise_ids:
            return {}
        stmt = (
            select(ExerciseMuscleModel.exercise_id, MuscleGroupModel.slug)
            .join(MuscleModel, MuscleModel.id == ExerciseMuscleModel.muscle_id)
            .join(MuscleGroupModel, MuscleGroupModel.id == MuscleModel.muscle_group_id)
            .where(
                and_(
                    ExerciseMuscleModel.exercise_id.in_(exercise_ids),
                    ExerciseMuscleModel.role == "primary",
                )
            )
            .distinct()
        )
        out: dict[UUID, list[str]] = {}
        for exercise_id, group_slug in (await self._session.execute(stmt)).all():
            out.setdefault(exercise_id, []).append(group_slug)
        return out


def _instruction_id(exercise_id: UUID, step: int) -> UUID:
    """Deterministic id for an instruction step.

    Instructions are rewritten wholesale whenever an exercise is edited, and a
    deterministic id makes that an idempotent upsert rather than a delete-and-reinsert
    that churns the table on every seed run.
    """
    return uuid5(exercise_id, f"instruction:{step}")
