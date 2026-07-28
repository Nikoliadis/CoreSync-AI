"""Repository ports for the progress domain."""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from coresync.domain.progress.entities import WeightLog


class WeightLogRepository(Protocol):
    async def get_latest(self, user_id: UUID) -> WeightLog | None: ...

    async def get_for_date(self, user_id: UUID, on: date) -> WeightLog | None: ...

    async def list_range(self, user_id: UUID, start: date, end: date) -> list[WeightLog]: ...

    async def add(self, log: WeightLog) -> None: ...

    async def update(self, log: WeightLog) -> None: ...

    async def delete(self, log_id: UUID, user_id: UUID) -> None: ...
