"""Nutrition rules.

Pure functions over foods and diary entries. Nothing here touches a database, so every
edge case is unit-testable — which matters because these are the numbers a user makes
decisions about.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from coresync.domain.nutrition.entities import (
    DiaryEntry,
    Food,
    Macros,
    MealType,
    WaterLog,
)

_ZERO = Decimal("0")

# The database enforces the same rule as `ck_food_energy_sane`. Duplicated here so a
# bad row is rejected with an explanation the user can act on rather than a constraint
# violation, and so an import can filter before it writes (docs/03 §7).
ENERGY_TOLERANCE_RATIO = Decimal("0.25")
ENERGY_TOLERANCE_FLOOR = Decimal("50")


class EnergyVerdict(StrEnum):
    OK = "ok"
    # The macros do not add up to the stated calories. Almost always a data-entry
    # error — a decimal point, or grams entered as ounces.
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True, slots=True)
class EnergyCheck:
    verdict: EnergyVerdict
    stated: Decimal
    implied: Decimal
    difference: Decimal
    tolerance: Decimal

    @property
    def is_ok(self) -> bool:
        return self.verdict is EnergyVerdict.OK


def check_energy(macros: Macros) -> EnergyCheck:
    """Whether the calories and the macros agree, within tolerance.

    The tolerance has a floor as well as a ratio because a 25 % band around a 20 kcal
    food is 5 kcal, which rounding alone can breach. Fibre, sugar alcohols and rounding
    on the label all mean the two numbers legitimately differ a little.
    """
    stated = macros.calories
    implied = macros.energy_from_macros
    tolerance = max(ENERGY_TOLERANCE_FLOOR, stated * ENERGY_TOLERANCE_RATIO)
    difference = abs(stated - implied)

    # A food with no stated calories is not checked: zero-calorie items — water, black
    # coffee, most spices — are legitimate and their macros are all zero too.
    if stated == _ZERO:
        return EnergyCheck(EnergyVerdict.OK, stated, implied, difference, tolerance)

    verdict = EnergyVerdict.OK if difference <= tolerance else EnergyVerdict.INCONSISTENT
    return EnergyCheck(verdict, stated, implied, difference, tolerance)


@dataclass(frozen=True, slots=True)
class MealTotals:
    meal_type: MealType
    entries: int
    macros: Macros


@dataclass(frozen=True, slots=True)
class DayTotals:
    """A day's intake, and how it sits against the user's targets."""

    macros: Macros
    water_ml: Decimal
    by_meal: list[MealTotals]
    entry_count: int

    def remaining(self, target: Macros) -> Macros:
        """What is left of the targets. Negative means over."""
        return Macros(
            calories=target.calories - self.macros.calories,
            protein_g=target.protein_g - self.macros.protein_g,
            carbs_g=target.carbs_g - self.macros.carbs_g,
            fat_g=target.fat_g - self.macros.fat_g,
        )


def summarise_day(entries: list[DiaryEntry], water: list[WaterLog]) -> DayTotals:
    """Total a day from its entries.

    Meals appear in the order they are eaten, not the order they were logged — someone
    adding breakfast at 3pm still expects to see it first.
    """
    total = Macros()
    per_meal: dict[MealType, tuple[int, Macros]] = {}

    for entry in entries:
        total = total + entry.macros
        count, macros = per_meal.get(entry.meal_type, (0, Macros()))
        per_meal[entry.meal_type] = (count + 1, macros + entry.macros)

    ordered = [
        MealTotals(meal_type=meal, entries=per_meal[meal][0], macros=per_meal[meal][1].rounded())
        for meal in MealType
        if meal in per_meal
    ]

    return DayTotals(
        macros=total.rounded(),
        water_ml=sum((log.millilitres for log in water), _ZERO),
        by_meal=ordered,
        entry_count=len(entries),
    )


def macro_split(macros: Macros) -> dict[str, Decimal]:
    """Share of energy from each macronutrient, as percentages.

    Computed from the macros rather than the stated calories: the two can disagree, and
    a split that does not sum to 100 % is visibly wrong in a way a user will notice.
    """
    energy = macros.energy_from_macros
    if energy <= _ZERO:
        return {"protein": _ZERO, "carbs": _ZERO, "fat": _ZERO}

    def share(grams: Decimal, factor: Decimal) -> Decimal:
        return ((grams * factor) / energy * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    return {
        "protein": share(macros.protein_g, Decimal("4")),
        "carbs": share(macros.carbs_g, Decimal("4")),
        "fat": share(macros.fat_g, Decimal("9")),
    }


def search_rank(food: Food, *, query: str, is_owner: bool) -> tuple[int, int, int]:
    """Sort key for search results. Lower sorts first.

    Trust tier dominates, because a wrong number is worse than an unfamiliar name. An
    exact name match jumps ahead of the tier ordering — someone typing "banana" who
    gets "banana bread" first will not type it again — and popularity breaks the
    remaining ties.
    """
    normalised = query.strip().lower()
    name = food.name.lower()

    if name == normalised:
        exactness = 0
    elif name.startswith(normalised):
        exactness = 1
    else:
        exactness = 2

    # A user's own foods outrank community data of the same exactness: they created it
    # deliberately, and it is usually the thing they meant.
    tier = 0 if is_owner and food.is_custom else int(food.trust_tier)

    return (exactness, tier, -food.usage_count)
