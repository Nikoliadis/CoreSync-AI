"""/v1/admin — internal operations.

Every route on this router carries a role guard at the router level rather than per
endpoint. A guard applied route by route is one someone forgets to add to the route
they write next, and the failure is silent: the endpoint simply works for everyone.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from coresync.application.admin.use_cases import GetPlatformStatsUseCase, ListUsersUseCase
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.admin import (
    AdminUserListResponse,
    AdminUserResponse,
    PlatformStatsResponse,
)
from coresync.presentation.schemas.common import ErrorResponse

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
