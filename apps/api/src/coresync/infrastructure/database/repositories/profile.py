"""SQLAlchemy implementations of the profile repository ports."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.profile.entities import Goal, NutritionTarget, Profile
from coresync.infrastructure.database.mappers import (
    GoalMapper,
    NutritionTargetMapper,
    ProfileMapper,
)
from coresync.infrastructure.database.models.identity import UserSettingsModel
from coresync.infrastructure.database.models.profile import (
    GoalModel,
    NutritionTargetModel,
    ProfileModel,
)


class SqlAlchemyProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> Profile | None:
        model = await self._session.get(ProfileModel, user_id)
        return ProfileMapper.to_entity(model) if model else None

    async def add(self, profile: Profile) -> None:
        self._session.add(ProfileMapper.to_model(profile))
        await self._session.flush()

    async def update(self, profile: Profile) -> None:
        model = await self._session.get(ProfileModel, profile.user_id)
        if model is None:
            raise ValueError(f"profile for user {profile.user_id} does not exist")
        ProfileMapper.apply(profile, model)
        await self._session.flush()


class SqlAlchemyGoalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current(self, user_id: UUID) -> Goal | None:
        stmt = select(GoalModel).where(
            GoalModel.user_id == user_id,
            GoalModel.ended_on.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return GoalMapper.to_entity(model) if model else None

    async def list_for_user(self, user_id: UUID) -> list[Goal]:
        stmt = (
            select(GoalModel)
            .where(GoalModel.user_id == user_id)
            .order_by(GoalModel.started_on.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [GoalMapper.to_entity(m) for m in rows]

    async def add(self, goal: Goal) -> None:
        self._session.add(GoalMapper.to_model(goal))
        await self._session.flush()

    async def update(self, goal: Goal) -> None:
        model = await self._session.get(GoalModel, goal.id)
        if model is None:
            raise ValueError(f"goal {goal.id} does not exist")
        model.goal_type = goal.goal_type.value
        model.target_weight_kg = goal.target_weight_kg
        model.weekly_rate_kg = goal.weekly_rate_kg
        model.target_date = goal.target_date
        model.ended_on = goal.ended_on
        await self._session.flush()


class SqlAlchemyNutritionTargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current(self, user_id: UUID) -> NutritionTarget | None:
        stmt = select(NutritionTargetModel).where(
            NutritionTargetModel.user_id == user_id,
            NutritionTargetModel.effective_to.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return NutritionTargetMapper.to_entity(model) if model else None

    async def get_effective_on(self, user_id: UUID, on: date) -> NutritionTarget | None:
        """The target in force on a given day.

        Nutrition adherence and the AI coach must reason about the target that applied
        at the time, not today's — which is the whole reason these rows are versioned.
        """
        stmt = select(NutritionTargetModel).where(
            NutritionTargetModel.user_id == user_id,
            NutritionTargetModel.effective_from <= on,
            or_(
                NutritionTargetModel.effective_to.is_(None),
                NutritionTargetModel.effective_to >= on,
            ),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return NutritionTargetMapper.to_entity(model) if model else None

    async def list_for_user(self, user_id: UUID) -> list[NutritionTarget]:
        stmt = (
            select(NutritionTargetModel)
            .where(NutritionTargetModel.user_id == user_id)
            .order_by(NutritionTargetModel.effective_from.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [NutritionTargetMapper.to_entity(m) for m in rows]

    async def add(self, target: NutritionTarget) -> None:
        self._session.add(NutritionTargetMapper.to_model(target))
        await self._session.flush()

    async def update(self, target: NutritionTarget) -> None:
        model = await self._session.get(NutritionTargetModel, target.id)
        if model is None:
            raise ValueError(f"target {target.id} does not exist")
        model.effective_to = target.effective_to
        model.calories = target.calories
        model.protein_g = target.protein_g
        model.carbs_g = target.carbs_g
        model.fat_g = target.fat_g
        model.fiber_g = target.fiber_g
        model.water_ml = target.water_ml
        model.source = target.source.value
        model.rationale = target.rationale
        await self._session.flush()


class SqlAlchemyUserSettingsRepository:
    _FIELDS = (
        "unit_system",
        "theme",
        "language",
        "profile_visibility",
        "ai_training_opt_in",
        "marketing_email_opt_in",
    )

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> dict[str, Any] | None:
        model = await self._session.get(UserSettingsModel, user_id)
        if model is None:
            return None
        return {field: getattr(model, field) for field in self._FIELDS}

    async def upsert(self, user_id: UUID, settings: dict[str, Any]) -> None:
        values = {k: v for k, v in settings.items() if k in self._FIELDS and v is not None}
        stmt = pg_insert(UserSettingsModel).values(user_id=user_id, **values)
        if values:
            stmt = stmt.on_conflict_do_update(index_elements=["user_id"], set_=values)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=["user_id"])
        await self._session.execute(stmt)
        await self._session.flush()
