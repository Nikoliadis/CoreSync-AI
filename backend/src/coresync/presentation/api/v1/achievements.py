"""/v1/achievements — milestones worth marking."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from coresync.application.achievements.use_cases import (
    EvaluateAchievementsUseCase,
    ListAchievementsUseCase,
)
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.achievements import (
    AchievementListResponse,
    AchievementResponse,
    NewlyEarnedResponse,
)

router = APIRouter(prefix="/achievements", tags=["achievements"])


@router.get(
    "",
    response_model=AchievementListResponse,
    summary="Every achievement, earned or not",
    description=(
        "Earned first, then whatever you are closest to. Unearned entries carry their "
        "progress, because a locked icon with no hint says nothing about how close you "
        "are."
    ),
)
async def list_achievements(
    user: deps.CurrentUser,
    use_case: Annotated[ListAchievementsUseCase, Depends(deps.list_achievements_use_case)],
) -> AchievementListResponse:
    items = await use_case.execute(user.id)
    return AchievementListResponse(
        achievements=[AchievementResponse.model_validate(item) for item in items],
        earned_count=sum(1 for item in items if item.earned),
        total_count=len(items),
    )


@router.post(
    "/evaluate",
    response_model=NewlyEarnedResponse,
    status_code=status.HTTP_200_OK,
    summary="Check for newly earned achievements",
    description=(
        "Normally run after a session completes. Safe to call repeatedly — the "
        "composite primary key means an achievement cannot be awarded twice, so a "
        "second call returns an empty list rather than re-announcing anything."
    ),
)
async def evaluate_achievements(
    user: deps.CurrentUser,
    use_case: Annotated[EvaluateAchievementsUseCase, Depends(deps.evaluate_achievements_use_case)],
) -> NewlyEarnedResponse:
    awarded = await use_case.execute(user.id, timezone=user.timezone)
    return NewlyEarnedResponse(
        newly_earned=[
            AchievementResponse(
                code=d.code,
                name=d.name,
                description=d.description,
                category=d.category.value,
                tier=d.tier.value,
                threshold=d.threshold,
                earned=True,
                earned_at=None,
                progress=1,
                current_value=d.threshold,
            )
            for d in awarded
        ]
    )
