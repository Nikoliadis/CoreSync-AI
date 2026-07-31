"""Wire schemas for the admin panel."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from coresync.presentation.schemas.common import ApiModel


class PlatformStatsResponse(ApiModel):
    """Windows are named rather than numbered.

    `new_users_7d` would serialise as `newUsers7D` through the camelCase alias
    generator — the digit stops the following letter being folded — so the fields say
    "last week" and "last month" instead.
    """

    total_users: int
    active_users: int
    new_users_last_week: int
    sessions_last_week: int
    ai_cost_last_month_usd: Decimal
    ai_calls_last_month: int


class AdminUserResponse(ApiModel):
    """Deliberately narrow: identity and status, nothing the user logged."""

    id: UUID
    email: str
    role: str
    status: str
    created_at: datetime | None = None


class AdminUserListResponse(ApiModel):
    users: list[AdminUserResponse]
    total: int
