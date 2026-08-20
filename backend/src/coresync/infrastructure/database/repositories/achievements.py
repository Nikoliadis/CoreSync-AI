"""SQLAlchemy repository for achievements."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.achievements.definitions import AchievementSnapshot
from coresync.infrastructure.database.models.achievements import UserAchievementModel
from coresync.infrastructure.database.models.aggregates import UserStreakModel
from coresync.infrastructure.database.models.workout import (
    PersonalRecordModel,
    SessionExerciseModel,
    WorkoutSessionModel,
)


class SqlAlchemyAchievementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def earned_codes(self, user_id: UUID) -> set[str]:
        stmt = select(UserAchievementModel.code).where(UserAchievementModel.user_id == user_id)
        return set((await self._session.execute(stmt)).scalars())

    async def earned_at(self, user_id: UUID) -> dict[str, datetime]:
        stmt = select(UserAchievementModel.code, UserAchievementModel.earned_at).where(
            UserAchievementModel.user_id == user_id
        )
        return dict((await self._session.execute(stmt)).all())  # type: ignore[arg-type]

    async def award(self, user_id: UUID, codes: Sequence[str], at: datetime) -> list[str]:
        if not codes:
            return []

        # ON CONFLICT DO NOTHING plus RETURNING gives exactly the rows this call
        # inserted. A concurrent evaluator that got there first simply returns fewer,
        # so nobody is notified twice about the same badge.
        stmt = (
            pg_insert(UserAchievementModel)
            .values([{"user_id": user_id, "code": code, "earned_at": at} for code in codes])
            .on_conflict_do_nothing(index_elements=["user_id", "code"])
            .returning(UserAchievementModel.code)
        )
        inserted = list((await self._session.execute(stmt)).scalars())
        await self._session.flush()
        return inserted

    async def snapshot(self, user_id: UUID) -> AchievementSnapshot:
        completed = WorkoutSessionModel.status == "completed"
        owned = WorkoutSessionModel.user_id == user_id

        totals = (
            await self._session.execute(
                select(
                    func.count(WorkoutSessionModel.id),
                    func.coalesce(func.sum(WorkoutSessionModel.total_volume_kg), 0),
                    func.min(WorkoutSessionModel.local_date),
                ).where(owned, completed, WorkoutSessionModel.deleted_at.is_(None))
            )
        ).one()

        pr_count = (
            await self._session.execute(
                select(func.count(PersonalRecordModel.id)).where(
                    PersonalRecordModel.user_id == user_id
                )
            )
        ).scalar_one()

        heaviest = (
            await self._session.execute(
                select(func.coalesce(func.max(PersonalRecordModel.value), 0)).where(
                    PersonalRecordModel.user_id == user_id,
                    PersonalRecordModel.record_type == "max_weight",
                )
            )
        ).scalar_one()

        distinct_exercises = (
            await self._session.execute(
                select(func.count(func.distinct(SessionExerciseModel.exercise_id)))
                .select_from(SessionExerciseModel)
                .join(
                    WorkoutSessionModel, WorkoutSessionModel.id == SessionExerciseModel.session_id
                )
                .where(owned, completed)
            )
        ).scalar_one()

        streak = (
            await self._session.execute(
                select(UserStreakModel).where(UserStreakModel.user_id == user_id)
            )
        ).scalar_one_or_none()

        first_session_date = totals[2]
        weeks_since_first = 0
        if first_session_date is not None:
            newest = (
                await self._session.execute(
                    select(func.max(WorkoutSessionModel.local_date)).where(owned, completed)
                )
            ).scalar_one()
            if newest is not None:
                weeks_since_first = max(0, (newest - first_session_date).days // 7)

        return AchievementSnapshot(
            total_sessions=int(totals[0] or 0),
            total_volume_kg=Decimal(totals[1] or 0),
            longest_streak_weeks=int(getattr(streak, "workout_longest", 0) or 0),
            current_streak_weeks=int(getattr(streak, "workout_current", 0) or 0),
            total_prs=int(pr_count or 0),
            heaviest_lift_kg=Decimal(heaviest or 0),
            distinct_exercises=int(distinct_exercises or 0),
            weeks_since_first_session=weeks_since_first,
        )
