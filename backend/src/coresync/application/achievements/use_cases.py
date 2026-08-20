"""Achievement use cases.

Evaluation is cheap — a handful of aggregate queries and a pure comparison — so it runs
on demand rather than needing a scheduled worker. That also means a user never sees a
badge appear hours after they earned it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock
from coresync.domain.achievements.definitions import (
    DEFINITIONS,
    AchievementDefinition,
    evaluate,
    measured_value,
)
from coresync.domain.notifications.entities import NotificationCategory


@dataclass(frozen=True, slots=True)
class AchievementView:
    code: str
    name: str
    description: str
    category: str
    tier: str
    threshold: Decimal
    earned: bool
    earned_at: datetime | None
    # Shown on unearned achievements. A locked icon with no hint tells the user
    # nothing about whether they are close.
    progress: Decimal
    current_value: Decimal


class ListAchievementsUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> list[AchievementView]:
        async with self._uow:
            earned_at = await self._uow.achievements.earned_at(user_id)
            snapshot = await self._uow.achievements.snapshot(user_id)

        views: list[AchievementView] = []
        for definition in DEFINITIONS:
            value = measured_value(definition, snapshot)
            views.append(
                AchievementView(
                    code=definition.code,
                    name=definition.name,
                    description=definition.description,
                    category=definition.category.value,
                    tier=definition.tier.value,
                    threshold=definition.threshold,
                    earned=definition.code in earned_at,
                    earned_at=earned_at.get(definition.code),
                    progress=definition.progress(value),
                    current_value=value,
                )
            )

        # Earned first, then whatever the user is closest to finishing — the ordering
        # that answers "what could I get next?" without them hunting for it.
        views.sort(key=lambda v: (not v.earned, -float(v.progress)))
        return views


class EvaluateAchievementsUseCase:
    """Awards anything newly earned, and tells the user about it.

    Called after a session completes. The notification is published inside the same
    transaction as the award, so a crash cannot leave a badge granted silently.
    """

    def __init__(self, *, uow: UnitOfWork, clock: Clock, publisher: object | None = None) -> None:
        self._uow = uow
        self._clock = clock
        self._publisher = publisher

    async def execute(self, user_id: UUID, *, timezone: str = "UTC") -> list[AchievementDefinition]:
        now = self._clock.now()

        async with self._uow:
            already = await self._uow.achievements.earned_codes(user_id)
            snapshot = await self._uow.achievements.snapshot(user_id)

            newly_earned = evaluate(snapshot, already)
            if not newly_earned:
                return []

            # Only what this call actually inserted is announced. A concurrent
            # evaluator that won the race means fewer rows back, and nobody is told
            # twice about the same badge.
            inserted = await self._uow.achievements.award(
                user_id, [d.code for d in newly_earned], now
            )
            awarded = [d for d in newly_earned if d.code in set(inserted)]

            if self._publisher is not None:
                for definition in awarded:
                    await self._publisher.publish(  # type: ignore[attr-defined]
                        user_id=user_id,
                        category=NotificationCategory.PR_CELEBRATION,
                        title=definition.name,
                        body=definition.description,
                        deep_link="/achievements",
                        data={"achievement": definition.code},
                        timezone=timezone,
                    )

            await self._uow.commit()

        return awarded
