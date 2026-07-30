"""Nutrition target calculation.

The safety properties here are the ones that matter most in the whole codebase: this is
the code that tells a real person how much to eat.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from coresync.core.ids import uuid7
from coresync.domain.profile.entities import (
    ActivityLevel,
    ExperienceLevel,
    Gender,
    Goal,
    GoalType,
    Profile,
)
from coresync.domain.profile.services import TdeeCalculator

TODAY = date(2026, 7, 29)


def make_profile(
    *,
    gender: Gender = Gender.MALE,
    height_cm: int = 181,
    birth_year: int = 2002,
    activity: ActivityLevel = ActivityLevel.MODERATE,
) -> Profile:
    return Profile(
        user_id=uuid7(),
        display_name="T",
        date_of_birth=date(birth_year, 1, 1),
        gender=gender,
        height_cm=Decimal(height_cm),
        activity_level=activity,
        experience_level=ExperienceLevel.INTERMEDIATE,
    )


def make_goal(goal_type: GoalType = GoalType.MAINTAIN) -> Goal:
    return Goal.create(
        user_id=uuid7(),
        goal_type=goal_type,
        target_weight_kg=None,
        weekly_rate_kg=None,
        target_date=None,
        on=TODAY,
    )


class TestBasalMetabolicRate:
    def test_matches_mifflin_st_jeor_for_men(self) -> None:
        # 10(82) + 6.25(181) - 5(24) + 5 = 1836.25
        bmr = TdeeCalculator().basal_metabolic_rate(
            profile=make_profile(), weight_kg=Decimal("82"), on=TODAY
        )
        assert bmr == pytest.approx(Decimal("1836.25"))

    def test_matches_mifflin_st_jeor_for_women(self) -> None:
        # 10(65) + 6.25(165) - 5(24) - 161 = 1400.25
        bmr = TdeeCalculator().basal_metabolic_rate(
            profile=make_profile(gender=Gender.FEMALE, height_cm=165),
            weight_kg=Decimal("65"),
            on=TODAY,
        )
        assert bmr == pytest.approx(Decimal("1400.25"))

    def test_unstated_gender_falls_between_the_two_formulas(self) -> None:
        calc = TdeeCalculator()
        args = {"weight_kg": Decimal("75"), "on": TODAY}
        male = calc.basal_metabolic_rate(profile=make_profile(gender=Gender.MALE), **args)
        female = calc.basal_metabolic_rate(profile=make_profile(gender=Gender.FEMALE), **args)
        other = calc.basal_metabolic_rate(
            profile=make_profile(gender=Gender.PREFER_NOT_TO_SAY), **args
        )
        assert female < other < male

    def test_requires_height(self) -> None:
        profile = make_profile()
        profile.height_cm = None
        with pytest.raises(ValueError, match="height"):
            TdeeCalculator().basal_metabolic_rate(
                profile=profile, weight_kg=Decimal("82"), on=TODAY
            )


class TestGoalAdjustment:
    def test_fat_loss_produces_a_deficit(self) -> None:
        calc = TdeeCalculator()
        maintain = calc.calculate(
            profile=make_profile(), weight_kg=Decimal("82"), goal=make_goal(), on=TODAY
        )
        cut = calc.calculate(
            profile=make_profile(),
            weight_kg=Decimal("82"),
            goal=make_goal(GoalType.LOSE_FAT),
            on=TODAY,
        )
        assert cut.calories < maintain.calories
        # 18% is the documented adjustment — conservative on purpose.
        assert cut.calories == pytest.approx(
            maintain.calories * Decimal("0.82"), rel=Decimal("0.01")
        )

    def test_muscle_gain_produces_a_surplus(self) -> None:
        calc = TdeeCalculator()
        maintain = calc.calculate(
            profile=make_profile(), weight_kg=Decimal("82"), goal=make_goal(), on=TODAY
        )
        bulk = calc.calculate(
            profile=make_profile(),
            weight_kg=Decimal("82"),
            goal=make_goal(GoalType.GAIN_MUSCLE),
            on=TODAY,
        )
        assert bulk.calories > maintain.calories

    def test_activity_level_scales_the_target(self) -> None:
        calc = TdeeCalculator()
        results = [
            calc.calculate(
                profile=make_profile(activity=level),
                weight_kg=Decimal("82"),
                goal=make_goal(),
                on=TODAY,
            ).calories
            for level in ActivityLevel
        ]
        assert results == sorted(results), "targets must increase with activity level"


class TestSafetyFloors:
    """These are the tests that stop the product from hurting someone."""

    def test_small_woman_cutting_never_drops_below_the_floor(self) -> None:
        result = TdeeCalculator().calculate(
            profile=make_profile(
                gender=Gender.FEMALE,
                height_cm=150,
                birth_year=1970,
                activity=ActivityLevel.SEDENTARY,
            ),
            weight_kg=Decimal("45"),
            goal=make_goal(GoalType.LOSE_FAT),
            on=TODAY,
        )
        assert result.calories >= Decimal("1200")
        assert result.was_clamped_to_floor is True

    def test_clamping_is_reported_so_the_ui_can_explain_it(self) -> None:
        normal = TdeeCalculator().calculate(
            profile=make_profile(), weight_kg=Decimal("82"), goal=make_goal(), on=TODAY
        )
        assert normal.was_clamped_to_floor is False

    @pytest.mark.parametrize(
        "goal_type,requested,weight,expected_sign",
        [
            (GoalType.LOSE_FAT, Decimal("-2.0"), Decimal("80"), -1),
            (GoalType.GAIN_MUSCLE, Decimal("2.0"), Decimal("80"), 1),
        ],
    )
    def test_absurd_weekly_rates_are_clamped(
        self, goal_type: GoalType, requested: Decimal, weight: Decimal, expected_sign: int
    ) -> None:
        clamped = TdeeCalculator().clamp_weekly_rate(
            weekly_rate_kg=requested, weight_kg=weight, goal_type=goal_type
        )
        assert abs(clamped) < abs(requested), "an unsafe rate must be reduced"
        assert (clamped > 0) == (expected_sign > 0)
        # 1% of bodyweight for loss, 0.5% for gain.
        limit = weight * (Decimal("0.01") if expected_sign < 0 else Decimal("0.005"))
        assert abs(clamped) <= limit


class TestMacroSplit:
    def test_macros_reconcile_with_the_calorie_target(self) -> None:
        result = TdeeCalculator().calculate(
            profile=make_profile(),
            weight_kg=Decimal("82"),
            goal=make_goal(GoalType.LOSE_FAT),
            on=TODAY,
        )
        energy = result.protein_g * 4 + result.carbs_g * 4 + result.fat_g * 9
        assert energy == pytest.approx(result.calories, rel=Decimal("0.02"))

    def test_protein_scales_with_bodyweight(self) -> None:
        calc = TdeeCalculator()
        light = calc.calculate(
            profile=make_profile(),
            weight_kg=Decimal("60"),
            goal=make_goal(GoalType.LOSE_FAT),
            on=TODAY,
        )
        heavy = calc.calculate(
            profile=make_profile(),
            weight_kg=Decimal("100"),
            goal=make_goal(GoalType.LOSE_FAT),
            on=TODAY,
        )
        assert heavy.protein_g > light.protein_g

    def test_water_target_is_bounded(self) -> None:
        calc = TdeeCalculator()
        tiny = calc.calculate(
            profile=make_profile(), weight_kg=Decimal("40"), goal=make_goal(), on=TODAY
        )
        huge = calc.calculate(
            profile=make_profile(), weight_kg=Decimal("200"), goal=make_goal(), on=TODAY
        )
        assert tiny.water_ml >= Decimal("2000")
        assert huge.water_ml <= Decimal("4000")


class TestSafetyProperties:
    """Property-based: explores the input space we would not enumerate by hand.

    A safety violation, if one exists, hides in a combination nobody thought to write a
    test for — which is exactly what Hypothesis is for.
    """

    @hypothesis_settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @given(
        weight=st.decimals(min_value=Decimal("35"), max_value=Decimal("250"), places=1),
        height=st.integers(min_value=130, max_value=220),
        birth_year=st.integers(min_value=1930, max_value=2012),
        gender=st.sampled_from(list(Gender)),
        activity=st.sampled_from(list(ActivityLevel)),
        goal_type=st.sampled_from(list(GoalType)),
    )
    def test_no_input_combination_produces_an_unsafe_target(
        self,
        weight: Decimal,
        height: int,
        birth_year: int,
        gender: Gender,
        activity: ActivityLevel,
        goal_type: GoalType,
    ) -> None:
        result = TdeeCalculator().calculate(
            profile=make_profile(
                gender=gender, height_cm=height, birth_year=birth_year, activity=activity
            ),
            weight_kg=weight,
            goal=make_goal(goal_type),
            on=TODAY,
        )

        # Mirrors the ck_nutrition_targets_calorie_floor CHECK constraint. If this
        # property ever fails, the database would reject the write — which is the
        # backstop working, but the user would see an error instead of a target.
        assert result.calories >= Decimal("1000")
        assert result.calories <= Decimal("10000")

        assert result.protein_g >= 0
        assert result.carbs_g >= 0, "carbohydrate must never go negative"
        assert result.fat_g >= 0
        assert result.protein_g <= weight * Decimal("3.0"), "protein ceiling"

        energy = result.protein_g * 4 + result.carbs_g * 4 + result.fat_g * 9
        assert energy <= result.calories * Decimal("1.10")
