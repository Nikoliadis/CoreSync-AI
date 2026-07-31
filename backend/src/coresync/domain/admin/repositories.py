"""Read-model ports for the admin panel.

Aggregates only. There is deliberately no method here that returns a coaching
transcript, a weight history or a photo: staff have no business reading those, and the
cheapest way to guarantee that is to leave the capability unbuilt (docs/11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PlatformStats:
    total_users: int
    active_users: int
    new_users_since: int
    sessions_since: int
    ai_cost_usd: Decimal
    ai_calls: int


@dataclass(frozen=True, slots=True)
class AdminUserRow:
    """Identity and status only — nothing about what the user actually logged."""

    id: UUID
    email: str
    role: str
    status: str
    created_at: datetime | None


class AdminReadRepository(Protocol):
    async def platform_stats(self, *, since: date, cost_since: date) -> PlatformStats: ...

    async def list_users(
        self, *, query: str | None, limit: int, offset: int
    ) -> tuple[list[AdminUserRow], int]: ...
