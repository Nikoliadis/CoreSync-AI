"""Nutrition target calculation.

Pure functions over domain objects: no database, no clock, no I/O. Every constant here
is a documented, reviewable decision rather than a magic number buried in a service.

Safety note: the floors in this module are one of three rings. The database enforces
`ck_targets_calorie_floor`, this calculator clamps, and the AI prompt is instructed.
The database is the ring that cannot be argued with — see docs/10 §7.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar

from coresync.domain.profile.entities import (
    ActivityLevel,
    Gender,
    Goal,
    GoalType,
    Profile,
)

_ZERO = Decimal("0")


def _round(value: Decimal, places: str = "1") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class MacroTargets:
    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    fiber_g: Decimal
    water_ml: Decimal
    # Surfaced to the user so the numbers are explicable rather than magic.
    bmr: Decimal
    tdee: Decimal
    was_clamped_to_floor: bool


class TdeeCalculator:
    """Mifflin-St Jeor BMR scaled by an activity multiplier, then a goal adjustment.

    Mifflin-St Jeor rather than Harris-Benedict: it is the more accurate of the two for
    modern populations and is what the dietetics literature has recommended since 2005.
    """

    ACTIVITY_MULTIPLIERS: ClassVar[dict[ActivityLevel, Decimal]] = {
        ActivityLevel.SEDENTARY: Decimal("1.2"),
        ActivityLevel.LIGHT: Decimal("1.375"),
        ActivityLevel.MODERATE: Decimal("1.55"),
        ActivityLevel.ACTIVE: Decimal("1.725"),
        ActivityLevel.VERY_ACTIVE: Decimal("1.9"),
    }

    # Conservative on purpose. Aggressive deficits are the main way a fitness app does
    # real harm, and a slower deficit is also more likely to be adhered to.
    GOAL_ADJUSTMENT_PCT: ClassVar[dict[GoalType, Decimal]] = {
        GoalType.LOSE_FAT: Decimal("-0.18"),
        GoalType.MAINTAIN: Decimal("0"),
        GoalType.GAIN_MUSCLE: Decimal("0.10"),
        GoalType.RECOMP: Decimal("-0.05"),
        GoalType.PERFORMANCE: Decimal("0.05"),
    }

    # Mirrors the database CHECK constraint. Anything below these is never written.
    CALORIE_FLOOR: ClassVar[dict[Gender, int]] = {
        Gender.MALE: 1500,
        Gender.FEMALE: 1200,
        Gender.OTHER: 1200,
        Gender.PREFER_NOT_TO_SAY: 1200,
    }
    ABSOLUTE_CALORIE_FLOOR = Decimal("1200")
    ABSOLUTE_CALORIE_CEILING = Decimal("6000")

    PROTEIN_G_PER_KG: ClassVar[dict[GoalType, Decimal]] = {
        GoalType.LOSE_FAT: Decimal("2.2"),
        GoalType.MAINTAIN: Decimal("1.8"),
        GoalType.GAIN_MUSCLE: Decimal("2.0"),
        GoalType.RECOMP: Decimal("2.2"),
        GoalType.PERFORMANCE: Decimal("1.8"),
    }
    PROTEIN_CEILING_G_PER_KG = Decimal("3.0")
    FAT_PCT_OF_CALORIES = Decimal("0.25")
    FAT_FLOOR_G_PER_KG = Decimal("0.6")  # below this, hormonal function suffers
    FIBER_G_PER_1000_KCAL = Decimal("14")
    WATER_ML_PER_KG = Decimal("35")
    WATER_MIN_ML = Decimal("2000")
    WATER_MAX_ML = Decimal("4000")

    # Rate limits as a fraction of bodyweight per week.
    MAX_LOSS_RATE_PCT = Decimal("0.01")
    MAX_GAIN_RATE_PCT = Decimal("0.005")

    def calculate(
        self,
        *,
        profile: Profile,
        weight_kg: Decimal,
        goal: Goal,
        on: date,
    ) -> MacroTargets:
        bmr = self.basal_metabolic_rate(profile=profile, weight_kg=weight_kg, on=on)
        tdee = bmr * self.ACTIVITY_MULTIPLIERS[profile.activity_level]

        adjustment = self.GOAL_ADJUSTMENT_PCT[goal.goal_type]
        calories = tdee * (Decimal(1) + adjustment)

        floor = self._calorie_floor(profile.gender)
        was_clamped = calories < floor
        calories = max(calories, floor)
        calories = min(calories, self.ABSOLUTE_CALORIE_CEILING)

        protein_g, carbs_g, fat_g = self._split_macros(
            calories=calories, weight_kg=weight_kg, goal_type=goal.goal_type
        )

        return MacroTargets(
            calories=_round(calories),
            protein_g=_round(protein_g),
            carbs_g=_round(carbs_g),
            fat_g=_round(fat_g),
            fiber_g=_round(calories / 1000 * self.FIBER_G_PER_1000_KCAL),
            water_ml=self._water_target(weight_kg),
            bmr=_round(bmr),
            tdee=_round(tdee),
            was_clamped_to_floor=was_clamped,
        )

    # ------------------------------------------------------------------ internals
    def basal_metabolic_rate(self, *, profile: Profile, weight_kg: Decimal, on: date) -> Decimal:
        if profile.height_cm is None:
            raise ValueError("height is required to calculate BMR")
        age = profile.age_at(on)
        if age is None:
            raise ValueError("date of birth is required to calculate BMR")

        base = Decimal(10) * weight_kg + Decimal("6.25") * profile.height_cm - Decimal(5) * age
        match profile.gender:
            case Gender.MALE:
                return base + 5
            case Gender.FEMALE:
                return base - 161
            case _:
                # Midpoint of the two published constants. Not a claim about the user —
                # simply the least-wrong estimate when the input is unavailable.
                return base - 78

    def _calorie_floor(self, gender: Gender | None) -> Decimal:
        if gender is None:
            return self.ABSOLUTE_CALORIE_FLOOR
        return Decimal(self.CALORIE_FLOOR[gender])

    def _split_macros(
        self, *, calories: Decimal, weight_kg: Decimal, goal_type: GoalType
    ) -> tuple[Decimal, Decimal, Decimal]:
        protein_g = weight_kg * self.PROTEIN_G_PER_KG[goal_type]
        protein_g = min(protein_g, weight_kg * self.PROTEIN_CEILING_G_PER_KG)

        fat_g = calories * self.FAT_PCT_OF_CALORIES / 9
        fat_g = max(fat_g, weight_kg * self.FAT_FLOOR_G_PER_KG)

        remaining = calories - (protein_g * 4) - (fat_g * 9)

        # At a low calorie target with a heavy user, protein and fat alone can exceed
        # the budget. Rather than emit negative carbs, walk protein back toward the
        # floor — carbohydrate is the most expendable of the three, but a non-negative
        # result matters more than any of them.
        if remaining < _ZERO:
            protein_floor = weight_kg * Decimal("1.6")
            available_for_protein = (calories - fat_g * 9) / 4
            protein_g = max(min(protein_g, available_for_protein), protein_floor)
            remaining = calories - (protein_g * 4) - (fat_g * 9)
            if remaining < _ZERO:
                fat_g = max((calories - protein_g * 4) / 9, _ZERO)
                remaining = _ZERO

        return protein_g, max(remaining / 4, _ZERO), fat_g

    def _water_target(self, weight_kg: Decimal) -> Decimal:
        target = weight_kg * self.WATER_ML_PER_KG
        return _round(min(max(target, self.WATER_MIN_ML), self.WATER_MAX_ML), "1")

    # -------------------------------------------------------------------- helpers
    def clamp_weekly_rate(
        self, *, weekly_rate_kg: Decimal, weight_kg: Decimal, goal_type: GoalType
    ) -> Decimal:
        """Bound a user-requested rate of change to something defensible.

        Requesting 2 kg/week is common and is not something we will help with.
        """
        if goal_type in (GoalType.LOSE_FAT, GoalType.RECOMP):
            limit = -(weight_kg * self.MAX_LOSS_RATE_PCT)
            return max(weekly_rate_kg, limit)
        if goal_type is GoalType.GAIN_MUSCLE:
            limit = weight_kg * self.MAX_GAIN_RATE_PCT
            return min(weekly_rate_kg, limit)
        return _ZERO
