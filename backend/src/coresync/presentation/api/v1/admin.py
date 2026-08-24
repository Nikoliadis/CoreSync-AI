"""/v1/admin — internal operations.

Every route on this router carries a role guard at the router level rather than per
endpoint. A guard applied route by route is one someone forgets to add to the route
they write next, and the failure is silent: the endpoint simply works for everyone.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from coresync.application.admin.use_cases import GetPlatformStatsUseCase, ListUsersUseCase
from coresync.application.nutrition.moderation import (
    ListSubmissionQueueUseCase,
    QueuedSubmission,
    ReviewSubmissionUseCase,
)
from coresync.domain.nutrition.entities import FoodSubmission, SubmissionStatus
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.admin import (
    AdminUserListResponse,
    AdminUserResponse,
    PlatformStatsResponse,
)
from coresync.presentation.schemas.common import ErrorResponse
from coresync.presentation.schemas.nutrition import (
    FoodResponse,
    FoodSubmissionResponse,
    QueuedSubmissionResponse,
    ReviewSubmissionRequest,
    SubmissionQueueResponse,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(deps.require_role("admin"))],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "Not an administrator."},
    },
)


@router.get(
    "/stats",
    response_model=PlatformStatsResponse,
    summary="Platform statistics",
    description=(
        "Counts and spend, never content. AI figures are aggregates — no endpoint here "
        "returns a coaching transcript."
    ),
)
async def get_stats(
    use_case: Annotated[GetPlatformStatsUseCase, Depends(deps.platform_stats_use_case)],
) -> PlatformStatsResponse:
    stats = await use_case.execute()
    return PlatformStatsResponse(
        total_users=stats.total_users,
        active_users=stats.active_users,
        new_users_last_week=stats.new_users_since,
        sessions_last_week=stats.sessions_since,
        ai_cost_last_month_usd=stats.ai_cost_usd,
        ai_calls_last_month=stats.ai_calls,
    )


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="Search users",
    description="Identity and status only — no training, body or conversation data.",
)
async def list_users(
    use_case: Annotated[ListUsersUseCase, Depends(deps.list_users_use_case)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUserListResponse:
    users, total = await use_case.execute(query=q, limit=limit, offset=offset)
    return AdminUserListResponse(
        users=[
            AdminUserResponse(
                id=user.id,
                email=user.email,
                role=user.role,
                status=user.status,
                created_at=user.created_at,
            )
            for user in users
        ],
        total=total,
    )


@router.get(
    "/food-submissions",
    response_model=SubmissionQueueResponse,
    summary="Foods awaiting review",
    description=(
        "Oldest first. A queue that surfaces the newest item is one where the awkward "
        "submissions sink and never get looked at."
    ),
)
async def list_food_submissions(
    use_case: Annotated[ListSubmissionQueueUseCase, Depends(deps.submission_queue_use_case)],
    status_filter: Annotated[
        str, Query(alias="status", pattern="^(pending|approved|rejected)$")
    ] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SubmissionQueueResponse:
    queued = await use_case.execute(status=SubmissionStatus(status_filter), limit=limit)
    return SubmissionQueueResponse(items=[_queued_response(item) for item in queued])


@router.post(
    "/food-submissions/{submission_id}/approve",
    response_model=FoodSubmissionResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Publish a submitted food",
    description=(
        "Promotes it to trust tier 2 — official, not curated. Tier 1 means a curator "
        "wrote those numbers; tier 2 means a reviewer checked somebody else's. The "
        "energy check is re-run here, because publishing to everyone is the worst "
        "possible moment to discover the macros do not add up."
    ),
)
async def approve_food_submission(
    submission_id: UUID,
    body: ReviewSubmissionRequest,
    user: deps.CurrentUser,
    use_case: Annotated[ReviewSubmissionUseCase, Depends(deps.review_submission_use_case)],
) -> FoodSubmissionResponse:
    return _submission_response(await use_case.approve(submission_id, user.id, note=body.note))


@router.post(
    "/food-submissions/{submission_id}/reject",
    response_model=FoodSubmissionResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Decline a submitted food",
    description=(
        "The food itself is untouched — it stays private and usable by its owner, who "
        "has lost nothing but the promotion."
    ),
)
async def reject_food_submission(
    submission_id: UUID,
    body: ReviewSubmissionRequest,
    user: deps.CurrentUser,
    use_case: Annotated[ReviewSubmissionUseCase, Depends(deps.review_submission_use_case)],
) -> FoodSubmissionResponse:
    return _submission_response(await use_case.reject(submission_id, user.id, note=body.note))


def _submission_response(submission: FoodSubmission) -> FoodSubmissionResponse:
    return FoodSubmissionResponse(
        id=submission.id,
        food_id=submission.food_id,
        status=submission.status.value,
        note=submission.note,
        created_at=submission.created_at,
        reviewed_at=submission.reviewed_at,
    )


def _queued_response(item: QueuedSubmission) -> QueuedSubmissionResponse:
    return QueuedSubmissionResponse(
        submission=_submission_response(item.submission),
        food=FoodResponse(
            id=item.food.id,
            name=item.food.name,
            source=item.food.source.value,
            trust_tier=int(item.food.trust_tier),
            is_verified=item.food.is_verified,
            is_custom=item.food.is_custom,
            is_liquid=item.food.is_liquid,
            calories_per_100g=item.food.calories_per_100g,
            protein_per_100g=item.food.protein_per_100g,
            carbs_per_100g=item.food.carbs_per_100g,
            fat_per_100g=item.food.fat_per_100g,
            alcohol_per_100g=item.food.alcohol_per_100g,
        ),
        energy_is_consistent=item.energy_is_consistent,
    )
