"""Repository ports for achievements."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from coresync.domain.achievements.definitions import AchievementSnapshot


class AchievementRepository(Protocol):
    async def earned_codes(self, user_id: UUID) -> set[str]: ...

    async def earned_at(self, user_id: UUID) -> dict[str, datetime]:
        """Codes with their award times, for display."""
        ...

    async def award(self, user_id: UUID, codes: Sequence[str], at: datetime) -> list[str]:
        """Record newly earned achievements.

        Returns the codes that were actually inserted. The composite primary key makes
        a re-award a no-op rather than a duplicate, so a concurrent evaluator loses the
        race harmlessly — and the caller can safely notify only about what it inserted.
        """
        ...

    async def snapshot(self, user_id: UUID) -> AchievementSnapshot:
        """The totals every rule is evaluated against."""
        ...
