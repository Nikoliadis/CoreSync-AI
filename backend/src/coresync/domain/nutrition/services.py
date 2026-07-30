"""Nutrition domain services.

Pure rules over foods and diary entries: what a day adds up to, whether an imported food
is plausible, and how close a user came to their targets.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from coresync.domain.nutrition.entities import (
    DiaryEntry,
    MacroNutrients,
    MealType,
)

_ZERO = Decimal("0")


def _round(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class MealTotals:
    meal_type: MealType
    macros: MacroNutrients
    entry_count: int


@dataclass(frozen=True, slots=True)
class DayTotals:
    """What the diary screen renders above the meal list."""

    macros: MacroNutrients
    entry_count: int
    water_ml: Decimal
    by_meal: list[MealTotals]


@dataclass(frozen=True, slots=True)
class TargetProgress:
    """Consumed against target, with what is left.

    ``remaining`` is allowed to go negative — telling someone they have "0 left" when
    they are 400 over is a lie the user can see through, and the number they need is the
    overage.
    """

    consumed: Decimal
    target: Decimal | None
    remaining: Decimal | None
    percent: Decimal | None

    @classmethod
    def of(cls, consumed: Decimal, target: Decimal | None) -> TargetProgress:
        if target is None or target <= _ZERO:
            return cls(consumed=consumed, target=target, remaining=None, percent=None)
        return cls(
            consumed=consumed,
            target=target,
            remaining=_round(target - consumed),
            percent=_round(consumed / target * 100),
        )


class DiaryCalculator:
    """Totals for a day. Every number the diary screen shows comes from here."""

    def day_totals(self, entries: Sequence[DiaryEntry], *, water_ml: Decimal = _ZERO) -> DayTotals:
        by_meal: list[MealTotals] = []
        for meal in MealType:
            meal_entries = [e for e in entries if e.meal_type is meal]
            by_meal.append(
                MealTotals(
                    meal_type=meal,
                    macros=self.sum_macros(e.macros for e in meal_entries),
                    entry_count=len(meal_entries),
                )
            )
        return DayTotals(
            macros=self.sum_macros(e.macros for e in entries),
            entry_count=len(entries),
            water_ml=water_ml,
            by_meal=by_meal,
        )

    @staticmethod
    def sum_macros(macros: Iterable[MacroNutrients]) -> MacroNutrients:
        total = MacroNutrients(_ZERO, _ZERO, _ZERO, _ZERO, _ZERO)
        for entry in macros:
            total = total + entry
        return MacroNutrients(
            calories=_round(total.calories),
            protein_g=_round(total.protein_g, "0.001"),
            carbs_g=_round(total.carbs_g, "0.001"),
            fat_g=_round(total.fat_g, "0.001"),
            fiber_g=_round(total.fiber_g or _ZERO, "0.001"),
        )

    @staticmethod
    def sum_micronutrients(entries: Sequence[DiaryEntry]) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for entry in entries:
            for code, amount in entry.micronutrients.items():
                totals[code] = totals.get(code, _ZERO) + amount
        return {code: _round(value, "0.001") for code, value in totals.items()}

    # A day counts toward adherence once it has enough entries to be a real record
    # rather than someone logging their morning coffee and forgetting.
    COMPLETE_DAY_MIN_ENTRIES = 3

    @classmethod
    def is_complete_day(cls, entry_count: int) -> bool:
        return entry_count >= cls.COMPLETE_DAY_MIN_ENTRIES


class FoodQualityChecker:
    """Plausibility rules for imported and user-submitted foods.

    Open Food Facts is crowd-sourced and frequently wrong in mechanical ways — a decimal
    point out of place, macros that cannot fit in the stated calories, energy given per
    serving instead of per 100 g. These checks catch the mechanical errors cheaply so
    they never reach a diary.
    """

    # Nothing edible exceeds this per 100 g: pure fat is 900 kcal.
    MAX_CALORIES_PER_100G = Decimal("902")
    MAX_GRAMS_PER_100G = Decimal("100")

    def rejection_reason(self, macros: MacroNutrients) -> str | None:
        """None when the food is plausible, otherwise why it is not."""
        if macros.calories < _ZERO:
            return "negative_calories"
        if macros.calories > self.MAX_CALORIES_PER_100G:
            return "calories_exceed_pure_fat"
        for label, value in (
            ("protein", macros.protein_g),
            ("carbs", macros.carbs_g),
            ("fat", macros.fat_g),
        ):
            if value < _ZERO:
                return f"negative_{label}"
            if value > self.MAX_GRAMS_PER_100G:
                return f"{label}_exceeds_100g"
        # 100 g of food cannot contain more than 100 g of macronutrients.
        if macros.protein_g + macros.carbs_g + macros.fat_g > self.MAX_GRAMS_PER_100G:
            return "macros_exceed_total_mass"
        if not macros.is_energy_consistent():
            return "energy_inconsistent_with_macros"
        return None

    def is_plausible(self, macros: MacroNutrients) -> bool:
        return self.rejection_reason(macros) is None


class NutritionStreakCalculator:
    """Consecutive days of logging.

    A day counts once it is *complete* — three or more entries. Counting a single logged
    coffee would make the streak meaningless as a signal of adherence, which is the only
    thing it is for.
    """

    def apply(
        self,
        *,
        logged_date: date,
        last_date: date | None,
        current: int,
        longest: int,
    ) -> tuple[int, int, date]:
        if last_date is None:
            new_current = 1
        elif logged_date == last_date:
            new_current = max(current, 1)
        elif logged_date == last_date + timedelta(days=1):
            new_current = current + 1
        elif logged_date < last_date:
            # A backfilled day from before the streak: leave it alone rather than
            # corrupting the count with an out-of-order write.
            return current, longest, last_date
        else:
            new_current = 1

        newest = max(logged_date, last_date) if last_date else logged_date
        return new_current, max(longest, new_current), newest
