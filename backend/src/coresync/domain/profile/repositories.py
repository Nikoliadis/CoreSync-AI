"""Repository ports for the profile domain.

Note that ``user_id`` is a required parameter on every read. There is deliberately no
``get(target_id)`` overload — an unscoped fetch is the shape of an IDOR bug, so the
interface does not offer one (docs/06 §7.2).
"""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from coresync.domain.profile.entities import Goal, NutritionTarget, Profile


class ProfileRepository(Protocol):
    async def get(self, user_id: UUID) -> Profile | None: ...

    async def add(self, profile: Profile) -> None: ...

    async def update(self, profile: Profile) -> None: ...


class GoalRepository(Protocol):
    async def get_current(self, user_id: UUID) -> Goal | None: ...

    async def list_for_user(self, user_id: UUID) -> list[Goal]: ...

    async def add(self, goal: Goal) -> None: ...

    async def update(self, goal: Goal) -> None: ...


class NutritionTargetRepository(Protocol):
    async def get_current(self, user_id: UUID) -> NutritionTarget | None: ...

    async def get_effective_on(self, user_id: UUID, on: date) -> NutritionTarget | None:
        """The target that applied on a given day.

        Used by nutrition adherence and by the AI coach, which must reason about the
        target that was in force at the time — not today's.
        """
        ...

    async def list_for_user(self, user_id: UUID) -> list[NutritionTarget]: ...

    async def add(self, target: NutritionTarget) -> None: ...

    async def update(self, target: NutritionTarget) -> None: ...


class UserSettingsRepository(Protocol):
    async def get(self, user_id: UUID) -> dict[str, object] | None: ...

    async def upsert(self, user_id: UUID, settings: dict[str, object]) -> None: ...
