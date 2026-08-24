"""How logged intake reaches the coach.

The arithmetic here is one division, and it is the whole point of the file: the average
divides by the days the user logged, not by the days that elapsed. Getting that backwards
turns partial logging into a fabricated deficit, and the coach acts on it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest

from coresync.application.coaching.context_assembler import ContextAssembler
from coresync.core.ids import uuid7
from coresync.domain.nutrition.entities import DiaryEntry, Macros, MealType, WaterLog

TODAY = date(2026, 8, 21)
USER = uuid7()


class StubDiary:
    def __init__(self, entries: list[DiaryEntry]) -> None:
        self._entries = entries

    async def entries_for_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[DiaryEntry]:
        return [e for e in self._entries if date_from <= e.local_date <= date_to]


class StubWater:
    def __init__(self, logs: list[WaterLog]) -> None:
        self._logs = logs

    async def logs_for_range(
        self, user_id: UUID, *, date_from: date, date_to: date
    ) -> list[WaterLog]:
        return [log for log in self._logs if date_from <= log.local_date <= date_to]


class StubUow:
    """Only the two repositories the nutrition window touches.

    A full fake unit of work would be forty stub methods to exercise one division.
    """

    def __init__(self, entries: list[DiaryEntry], logs: list[WaterLog] | None = None) -> None:
        self.diary = StubDiary(entries)
        self.water = StubWater(logs or [])


def entry(*, on: date, calories: str, protein: str = "0") -> DiaryEntry:
    return DiaryEntry(
        id=uuid7(),
        user_id=USER,
        local_date=on,
        meal_type=MealType.LUNCH,
        display_name="Test food",
        quantity=Decimal("100"),
        total_grams=Decimal("100"),
        macros=Macros(
            calories=Decimal(calories),
            protein_g=Decimal(protein),
            carbs_g=Decimal(0),
            fat_g=Decimal(0),
        ),
        logged_at=datetime(on.year, on.month, on.day, 13, 0, tzinfo=UTC),
    )


def water(*, on: date, millilitres: str) -> WaterLog:
    return WaterLog(
        id=uuid7(),
        user_id=USER,
        local_date=on,
        millilitres=Decimal(millilitres),
        logged_at=datetime(on.year, on.month, on.day, 13, 0, tzinfo=UTC),
    )


def assembler(entries: list[DiaryEntry], logs: list[WaterLog] | None = None) -> ContextAssembler:
    return ContextAssembler(uow=cast(Any, StubUow(entries, logs)))


async def window(entries: list[DiaryEntry], logs: list[WaterLog] | None = None) -> Any:
    return await assembler(entries, logs)._nutrition(USER, today=TODAY)


class TestNutritionWindow:
    async def test_no_entries_means_untracked(self) -> None:
        assert await window([]) is None

    async def test_averages_divide_by_days_logged_not_days_elapsed(self) -> None:
        """Three logged days at 2,100 kcal is a 2,100 kcal average, not 900.

        Dividing by the seven-day window instead would tell the coach this person eats
        900 kcal a day. It would then, correctly given that input, urge them to eat more
        — advice built entirely on days they simply did not open the app.
        """
        entries = [
            entry(on=TODAY, calories="2100"),
            entry(on=TODAY.replace(day=20), calories="2100"),
            entry(on=TODAY.replace(day=19), calories="2100"),
        ]
        result = await window(entries)
        assert result.days_logged == 3
        assert result.days_in_window == 7
        assert result.avg_calories == Decimal("2100.0")

    async def test_several_entries_on_one_day_are_still_one_day(self) -> None:
        """Breakfast, lunch and dinner are one day of logging, not three."""
        entries = [
            entry(on=TODAY, calories="500"),
            entry(on=TODAY, calories="700"),
            entry(on=TODAY, calories="900"),
        ]
        result = await window(entries)
        assert result.days_logged == 1
        assert result.avg_calories == Decimal("2100.0")

    async def test_entries_outside_the_window_are_excluded(self) -> None:
        entries = [
            entry(on=TODAY, calories="2000"),
            entry(on=date(2026, 7, 1), calories="9000"),
        ]
        result = await window(entries)
        assert result.days_logged == 1
        assert result.avg_calories == Decimal("2000.0")

    async def test_the_window_starts_seven_days_back_inclusive(self) -> None:
        """Seven days means today plus six, matching `training_7d`."""
        entries = [
            entry(on=TODAY, calories="2000"),
            entry(on=date(2026, 8, 15), calories="2000"),  # the seventh day
            entry(on=date(2026, 8, 14), calories="9000"),  # one day too far
        ]
        result = await window(entries)
        assert result.days_logged == 2
        assert result.avg_calories == Decimal("2000.0")

    async def test_macros_are_averaged_over_the_same_denominator(self) -> None:
        entries = [
            entry(on=TODAY, calories="2000", protein="150"),
            entry(on=TODAY.replace(day=20), calories="2000", protein="170"),
        ]
        result = await window(entries)
        assert result.avg_protein_g == Decimal("160.0")

    async def test_water_uses_the_diary_denominator(self) -> None:
        """A logged day with no water recorded is a day they told us about no water."""
        entries = [
            entry(on=TODAY, calories="2000"),
            entry(on=TODAY.replace(day=20), calories="2000"),
        ]
        logs = [water(on=TODAY, millilitres="2000")]
        result = await window(entries, logs)
        assert result.avg_water_ml == Decimal("1000.0")

    async def test_water_alone_does_not_make_a_tracked_week(self) -> None:
        """Hydration is not intake. Drinking water tells the coach nothing about eating."""
        logs = [water(on=TODAY, millilitres="2000")]
        assert await window([], logs) is None


@pytest.mark.parametrize("days", [1, 2, 3, 7])
async def test_days_logged_counts_distinct_dates(days: int) -> None:
    entries = [entry(on=date(2026, 8, 21 - offset), calories="2000") for offset in range(days)]
    result = await window(entries)
    assert result.days_logged == days
