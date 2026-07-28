"""Time as an injected dependency.

Business rules that read the wall clock directly cannot be tested deterministically —
token expiry, lockout windows and streak boundaries all need controllable time. Every
component that needs "now" receives a ``Clock``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """The real clock. Always timezone-aware UTC — naive datetimes are banned by lint."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Test double. Advanceable, so expiry windows can be crossed explicitly."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires an aware datetime")
        self._now = at

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def set(self, at: datetime) -> None:
        self._now = at


def local_date_for(moment: datetime, timezone: str) -> date:
    """The calendar date a moment falls on in the user's timezone.

    A workout finished at 23:30 in Athens belongs to that day, not to the UTC next day.
    Every user-facing "day" in the system — diary dates, streaks, calendars — is
    computed through this function at write time and stored, never derived at read time.
    """
    try:
        zone = ZoneInfo(timezone)
    except Exception:
        zone = UTC  # type: ignore[assignment]
    return moment.astimezone(zone).date()
