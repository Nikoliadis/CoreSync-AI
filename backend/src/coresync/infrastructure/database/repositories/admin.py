"""SQLAlchemy read model for the admin panel."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.admin.repositories import AdminUserRow, PlatformStats
from coresync.infrastructure.database.models.coaching import AiUsageLogModel
from coresync.infrastructure.database.models.identity import UserModel
from coresync.infrastructure.database.models.workout import WorkoutSessionModel


class SqlAlchemyAdminReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def platform_stats(self, *, since: date, cost_since: date) -> PlatformStats:
        live = UserModel.deleted_at.is_(None)

        total_users = (
            await self._session.execute(select(func.count(UserModel.id)).where(live))
        ).scalar_one()

        active_users = (
            await self._session.execute(
                select(func.count(UserModel.id)).where(live, UserModel.status == "active")
            )
        ).scalar_one()

        new_users = (
            await self._session.execute(
                select(func.count(UserModel.id)).where(
                    live, func.date(UserModel.created_at) >= since
                )
            )
        ).scalar_one()

        sessions = (
            await self._session.execute(
                select(func.count(WorkoutSessionModel.id)).where(
                    WorkoutSessionModel.local_date >= since
                )
            )
        ).scalar_one()

        # Cost and call count in one pass — two round trips for two numbers off the
        # same predicate is the sort of thing that makes an admin page feel slow.
        cost, calls = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(AiUsageLogModel.cost_usd), 0),
                    func.count(AiUsageLogModel.id),
                ).where(AiUsageLogModel.local_date >= cost_since)
            )
        ).one()

        return PlatformStats(
            total_users=int(total_users or 0),
            active_users=int(active_users or 0),
            new_users_since=int(new_users or 0),
            sessions_since=int(sessions or 0),
            ai_cost_usd=Decimal(cost or 0),
            ai_calls=int(calls or 0),
        )

    async def list_users(
        self, *, query: str | None, limit: int, offset: int
    ) -> tuple[list[AdminUserRow], int]:
        base = select(UserModel).where(UserModel.deleted_at.is_(None))
        if query:
            # ILIKE with a leading wildcard cannot use a b-tree index. Acceptable for
            # a support screen over an admin-sized result set; if the user table grows
            # past that, this becomes a trigram index rather than a bigger LIMIT.
            base = base.where(UserModel.email.ilike(f"%{query}%"))

        total = (
            await self._session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()

        rows = (
            await self._session.execute(
                base.order_by(UserModel.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars()

        return [
            AdminUserRow(
                id=user.id,
                email=user.email,
                role=user.role,
                status=user.status,
                created_at=user.created_at,
            )
            for user in rows
        ], int(total or 0)
