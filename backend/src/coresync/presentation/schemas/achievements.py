"""Wire schemas for achievements."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from coresync.presentation.schemas.common import ApiModel


class AchievementResponse(ApiModel):
    code: str
    name: str
    description: str
    category: str
    tier: str
    threshold: Decimal
    earned: bool
    earned_at: datetime | None = None
    # 0..1. Carried on unearned entries so a client can show "7 of 10" rather than a
    # locked icon that says nothing about how close the user is.
    progress: Decimal
    current_value: Decimal


class AchievementListResponse(ApiModel):
    achievements: list[AchievementResponse]
    earned_count: int
    total_count: int


class NewlyEarnedResponse(ApiModel):
    newly_earned: list[AchievementResponse] = Field(default_factory=list)
