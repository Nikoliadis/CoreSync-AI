"""Nutrition rules.

These are the numbers a user makes decisions about, so the portion maths, the energy
reconciliation and the search ranking are all pinned directly. Food data quality is a
*fatal* risk in docs/15 — the ranking tests are part of that mitigation, not polish.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from coresync.domain.nutrition.entities import (
    DiaryEntry,
    Food,
    FoodServing,
    FoodSource,
    Macros,
    MealType,
    Recipe,
    RecipeIngredient,
    TrustTier,
    WaterLog,
)
from coresync.domain.nutrition.services import (
    EnergyVerdict,
    NutritionStreak,
    check_energy,
    macro_split,
    nutrition_streak,
    search_rank,
    summarise_day,
)

USER = uuid4()
TODAY = date(2026, 8, 1)


def food(
    name: str = "Chicken breast",
    *,
    calories: str = "165",
    protein: str = "31",
    carbs: str = "0",
    fat: str = "3.6",
    source: FoodSource = FoodSource.CURATED,
    owner: object = None,
    usage: int = 0,
) -> Food:
    built = Food.create(
        name=name,
        source=source,
        calories_per_100g=Decimal(calories),
        protein_per_100g=Decimal(protein),
        carbs_per_100g=Decimal(carbs),
        fat_per_100g=Decimal(fat),
        owner_user_id=owner,  # type: ignore[arg-type]
    )
    built.usage_count = usage
    return built


class TestTrustTiers:
    @pytest.mark.parametrize(
        ("source", "tier"),
        [
            (FoodSource.CURATED, TrustTier.CURATED),
            (FoodSource.USDA, TrustTier.OFFICIAL),
            (FoodSource.OFF, TrustTier.COMMUNITY),
            (FoodSource.USER, TrustTier.USER),
        ],
    )
    def test_the_tier_follows_the_source(self, source: FoodSource, tier: TrustTier) -> None:
        assert (
            Food.create(
                name="x", source=source, calories_per_100g=Decimal(100), carbs_per_100g=Decimal(25)
            ).trust_tier
            is tier
        )

    def test_only_curated_data_is_badged_verified(self) -> None:
        """The badge means a human checked it, not that the row exists."""
        assert food(source=FoodSource.CURATED).is_verified is True
        assert food(source=FoodSource.OFF).is_verified is False
        assert food(source=FoodSource.USER).is_verified is False


class TestPortionMaths:
    def test_one_hundred_grams_is_the_reference(self) -> None:
        assert food().macros_for(Decimal(100)).calories == Decimal("165.00")

    def test_portions_scale_linearly(self) -> None:
        assert food().macros_for(Decimal(200)).protein_g == Decimal("62.00")

    def test_a_partial_portion_rounds_to_two_places(self) -> None:
        macros = food().macros_for(Decimal("37.5"))
        assert macros.calories == Decimal("61.88")

    def test_zero_grams_is_zero(self) -> None:
        assert food().macros_for(_zero()).calories == Decimal("0.00")

    def test_a_negative_portion_is_refused(self) -> None:
        with pytest.raises(ValueError):
            food().macros_for(Decimal(-10))


def ingredient(recipe_id, food_id, grams: int) -> RecipeIngredient:
    return RecipeIngredient(id=uuid4(), recipe_id=recipe_id, food_id=food_id, grams=Decimal(grams))


def _zero() -> Decimal:
    return Decimal(0)


class TestServings:
    def test_logging_in_servings_converts_to_grams(self) -> None:
        # Users log "one medium banana", not "118 g".
        banana = food("Banana", **BANANA)
        serving = FoodServing.create(
            food_id=banana.id, label="1 medium", grams=Decimal(118), is_default=True
        )
        banana.servings.append(serving)

        entry = DiaryEntry.for_food(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.BREAKFAST,
            food=banana,
            quantity=Decimal(2),
            serving=serving,
        )

        assert entry.total_grams == Decimal("236.00")
        assert entry.macros.calories == Decimal("210.04")

    def test_without_a_serving_the_quantity_is_grams(self) -> None:
        entry = DiaryEntry.for_food(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.LUNCH,
            food=food(),
            quantity=Decimal(150),
        )
        assert entry.total_grams == Decimal("150.00")

    def test_a_serving_must_weigh_something(self) -> None:
        with pytest.raises(ValueError):
            FoodServing.create(food_id=uuid4(), label="1 nothing", grams=_zero())

    def test_the_default_serving_is_preferred(self) -> None:
        item = food()
        item.servings = [
            FoodServing.create(food_id=item.id, label="100 g", grams=Decimal(100)),
            FoodServing.create(
                food_id=item.id, label="1 fillet", grams=Decimal(174), is_default=True
            ),
        ]
        assert item.default_serving().label == "1 fillet"  # type: ignore[union-attr]


class TestEnergyReconciliation:
    def test_consistent_macros_pass(self) -> None:
        assert check_energy(food().per_100g).verdict is EnergyVerdict.OK

    def test_a_misplaced_decimal_point_is_caught(self) -> None:
        # 31 g protein entered as 310 g implies 1240 kcal against a stated 165.
        wrong = Macros(
            calories=Decimal(165),
            protein_g=Decimal(310),
            carbs_g=_zero(),
            fat_g=Decimal("3.6"),
        )
        assert check_energy(wrong).verdict is EnergyVerdict.INCONSISTENT

    def test_a_zero_calorie_food_is_not_flagged(self) -> None:
        """Water, black coffee and most spices are legitimately zero."""
        assert check_energy(Macros()).verdict is EnergyVerdict.OK

    def test_small_foods_get_an_absolute_tolerance(self) -> None:
        # 25% of 20 kcal is 5 kcal, which label rounding alone can breach.
        nearly = Macros(calories=Decimal(20), protein_g=Decimal(1), carbs_g=Decimal(2))
        assert check_energy(nearly).verdict is EnergyVerdict.OK

    def test_label_rounding_is_tolerated(self) -> None:
        # Fibre and sugar alcohols mean the two numbers legitimately differ a little.
        close = Macros(
            calories=Decimal(250), protein_g=Decimal(10), carbs_g=Decimal(30), fat_g=Decimal(9)
        )
        assert check_energy(close).is_ok

    def test_the_check_reports_both_numbers(self) -> None:
        result = check_energy(food().per_100g)
        assert result.stated == Decimal(165)
        assert result.implied > _zero()


class TestDailyTotals:
    def test_an_empty_day_totals_zero(self) -> None:
        totals = summarise_day([], [])
        assert totals.macros.calories == Decimal("0.00")
        assert totals.entry_count == 0

    def test_entries_sum_across_meals(self) -> None:
        entries = [
            DiaryEntry.for_food(
                user_id=USER,
                local_date=TODAY,
                meal_type=MealType.BREAKFAST,
                food=food(),
                quantity=Decimal(100),
            ),
            DiaryEntry.for_food(
                user_id=USER,
                local_date=TODAY,
                meal_type=MealType.DINNER,
                food=food(),
                quantity=Decimal(200),
            ),
        ]
        totals = summarise_day(entries, [])
        assert totals.macros.calories == Decimal("495.00")
        assert totals.entry_count == 2

    def test_meals_appear_in_eating_order_not_logging_order(self) -> None:
        """Someone adding breakfast at 3pm still expects to see it first."""
        entries = [
            DiaryEntry.quick_add(
                user_id=USER, local_date=TODAY, meal_type=MealType.DINNER, macros=Macros()
            ),
            DiaryEntry.quick_add(
                user_id=USER, local_date=TODAY, meal_type=MealType.BREAKFAST, macros=Macros()
            ),
        ]
        totals = summarise_day(entries, [])
        assert [m.meal_type for m in totals.by_meal] == [MealType.BREAKFAST, MealType.DINNER]

    def test_water_totals_separately(self) -> None:
        logs = [
            WaterLog.create(user_id=USER, local_date=TODAY, millilitres=Decimal(500)),
            WaterLog.create(user_id=USER, local_date=TODAY, millilitres=Decimal(250)),
        ]
        assert summarise_day([], logs).water_ml == Decimal(750)

    def test_remaining_goes_negative_when_over(self) -> None:
        # Over-target is a fact, not an error — clamping it at zero would hide it.
        entries = [
            DiaryEntry.quick_add(
                user_id=USER,
                local_date=TODAY,
                meal_type=MealType.SNACK,
                macros=Macros(calories=Decimal(2600)),
            )
        ]
        remaining = summarise_day(entries, []).remaining(Macros(calories=Decimal(2400)))
        assert remaining.calories == Decimal(-200)


class TestQuickAdd:
    def test_calories_can_be_logged_with_no_food_behind_them(self) -> None:
        """Making someone invent a food to record a restaurant meal kills the diary."""
        entry = DiaryEntry.quick_add(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.DINNER,
            macros=Macros(calories=Decimal(700), protein_g=Decimal(30)),
            label="Restaurant curry",
        )
        assert entry.food_id is None
        assert entry.recipe_id is None
        assert entry.display_name == "Restaurant curry"


class TestMacroSplit:
    def test_the_split_sums_to_about_a_hundred(self) -> None:
        split = macro_split(
            Macros(
                calories=Decimal(500),
                protein_g=Decimal(30),
                carbs_g=Decimal(50),
                fat_g=Decimal(15),
            )
        )
        assert abs(sum(split.values()) - Decimal(100)) < Decimal("0.5")

    def test_an_empty_day_splits_to_zero_rather_than_dividing_by_it(self) -> None:
        assert macro_split(Macros()) == {"protein": _zero(), "carbs": _zero(), "fat": _zero()}

    def test_fat_carries_nine_calories_a_gram(self) -> None:
        split = macro_split(Macros(fat_g=Decimal(10)))
        assert split["fat"] == Decimal("100.0")


BANANA = {"calories": "89", "protein": "1.1", "carbs": "23", "fat": "0.3"}
OATS = {"calories": "389", "protein": "17", "carbs": "66", "fat": "7"}
OAT_MILK = {"calories": "46", "protein": "1", "carbs": "7", "fat": "1.5"}
SHAKE = {"calories": "120", "protein": "24", "carbs": "3", "fat": "1"}
BANANA_BREAD = {"calories": "326", "protein": "4", "carbs": "54", "fat": "11"}


class TestSearchRanking:
    def test_an_exact_match_wins_regardless_of_tier(self) -> None:
        """Typing 'banana' and getting 'banana bread' first is how search loses trust."""
        exact = food("Banana", source=FoodSource.OFF, **BANANA)
        prefixed = food("Banana bread", source=FoodSource.CURATED, **BANANA_BREAD)

        ranked = sorted(
            [prefixed, exact], key=lambda f: search_rank(f, query="banana", is_owner=False)
        )
        assert ranked[0].name == "Banana"

    def test_trust_tier_breaks_ties(self) -> None:
        # A wrong number is worse than an unfamiliar name.
        community = food("Oat milk", source=FoodSource.OFF, **OAT_MILK)
        curated = food("Oat milk", source=FoodSource.CURATED, **OAT_MILK)

        ranked = sorted(
            [community, curated], key=lambda f: search_rank(f, query="oat milk", is_owner=False)
        )
        assert ranked[0].trust_tier is TrustTier.CURATED

    def test_popularity_breaks_the_remaining_ties(self) -> None:
        rare = food("Oats", source=FoodSource.OFF, usage=2, **OATS)
        common = food("Oats", source=FoodSource.OFF, usage=900, **OATS)

        ranked = sorted([rare, common], key=lambda f: search_rank(f, query="oats", is_owner=False))
        assert ranked[0].usage_count == 900

    def test_a_users_own_food_outranks_community_data(self) -> None:
        mine = food("Protein shake", source=FoodSource.USER, owner=USER, **SHAKE)
        theirs = food("Protein shake", source=FoodSource.OFF, **SHAKE)

        ranked = sorted(
            [theirs, mine], key=lambda f: search_rank(f, query="protein shake", is_owner=True)
        )
        assert ranked[0].is_custom is True


class TestRecipes:
    def test_a_recipe_totals_its_ingredients(self) -> None:
        chicken = food()
        rice = food("Rice", calories="130", protein="2.7", carbs="28", fat="0.3")

        recipe = Recipe.create(user_id=USER, name="Chicken and rice", servings_count=Decimal(2))
        recipe.ingredients = [
            ingredient(recipe.id, chicken.id, 200),
            ingredient(recipe.id, rice.id, 300),
        ]

        total = recipe.total_macros({chicken.id: chicken, rice.id: rice})
        assert total.calories == Decimal("720.00")

    def test_per_serving_divides_the_total(self) -> None:
        chicken = food()
        recipe = Recipe.create(user_id=USER, name="Batch", servings_count=Decimal(4))
        recipe.ingredients = [ingredient(recipe.id, chicken.id, 400)]
        assert recipe.per_serving({chicken.id: chicken}).calories == Decimal("165.00")

    def test_a_missing_ingredient_is_skipped_not_counted_as_zero(self) -> None:
        """An incomplete recipe is better than one that silently under-reports."""
        chicken = food()
        recipe = Recipe.create(user_id=USER, name="Partial", servings_count=Decimal(1))
        recipe.ingredients = [
            ingredient(recipe.id, chicken.id, 100),
            ingredient(recipe.id, uuid4(), 100),
        ]
        assert recipe.total_macros({chicken.id: chicken}).calories == Decimal("165.00")

    def test_a_recipe_needs_at_least_part_of_a_serving(self) -> None:
        with pytest.raises(ValueError):
            Recipe.create(user_id=USER, name="Nothing", servings_count=_zero())


class TestLoggingARecipe:
    """Where a definition becomes a record.

    The recipe keeps referencing its ingredients so it tracks corrections to food data.
    The entry it produces keeps a snapshot, so nothing that happens afterwards can
    rewrite what was eaten. Both halves are load-bearing.
    """

    def _recipe(self, chicken: Food, *, servings: int = 2, grams: int = 400) -> Recipe:
        recipe = Recipe.create(user_id=USER, name="Batch cook", servings_count=Decimal(servings))
        recipe.ingredients = [ingredient(recipe.id, chicken.id, grams)]
        return recipe

    def test_one_serving_takes_the_per_serving_macros(self) -> None:
        chicken = food()
        recipe = self._recipe(chicken)

        entry = DiaryEntry.for_recipe(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.DINNER,
            recipe=recipe,
            servings=Decimal(1),
            foods={chicken.id: chicken},
        )
        # 400 g of chicken at 165 kcal/100 g is 660, halved across two servings.
        assert entry.macros.calories == Decimal("330.00")
        assert entry.total_grams == Decimal("200.000")

    def test_two_servings_double_it(self) -> None:
        chicken = food()
        recipe = self._recipe(chicken)

        entry = DiaryEntry.for_recipe(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.DINNER,
            recipe=recipe,
            servings=Decimal(2),
            foods={chicken.id: chicken},
        )
        assert entry.macros.calories == Decimal("660.00")

    def test_half_a_serving_halves_it(self) -> None:
        chicken = food()
        recipe = self._recipe(chicken)

        entry = DiaryEntry.for_recipe(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.LUNCH,
            recipe=recipe,
            servings=Decimal("0.5"),
            foods={chicken.id: chicken},
        )
        assert entry.macros.calories == Decimal("165.00")

    def test_the_entry_points_at_the_recipe_not_a_food(self) -> None:
        chicken = food()
        recipe = self._recipe(chicken)

        entry = DiaryEntry.for_recipe(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.DINNER,
            recipe=recipe,
            servings=Decimal(1),
            foods={chicken.id: chicken},
        )
        assert entry.recipe_id == recipe.id
        assert entry.food_id is None
        assert entry.display_name == "Batch cook"

    def test_editing_the_recipe_afterwards_does_not_move_the_entry(self) -> None:
        """The snapshot rule, stated as a test.

        Doubling tonight's batch must not retroactively double what last night's dinner
        is reported to have been.
        """
        chicken = food()
        recipe = self._recipe(chicken)

        entry = DiaryEntry.for_recipe(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.DINNER,
            recipe=recipe,
            servings=Decimal(1),
            foods={chicken.id: chicken},
        )
        eaten = entry.macros.calories

        recipe.ingredients = [ingredient(recipe.id, chicken.id, 800)]
        assert entry.macros.calories == eaten

    def test_a_missing_ingredient_under_reports_rather_than_inventing(self) -> None:
        chicken = food()
        recipe = self._recipe(chicken)
        recipe.ingredients.append(ingredient(recipe.id, uuid4(), 400))

        entry = DiaryEntry.for_recipe(
            user_id=USER,
            local_date=TODAY,
            meal_type=MealType.DINNER,
            recipe=recipe,
            servings=Decimal(1),
            foods={chicken.id: chicken},
        )
        assert entry.macros.calories == Decimal("330.00")

    def test_zero_servings_is_refused(self) -> None:
        chicken = food()
        recipe = self._recipe(chicken)
        with pytest.raises(ValueError):
            DiaryEntry.for_recipe(
                user_id=USER,
                local_date=TODAY,
                meal_type=MealType.DINNER,
                recipe=recipe,
                servings=_zero(),
                foods={chicken.id: chicken},
            )


class TestValidation:
    def test_a_food_needs_a_name(self) -> None:
        with pytest.raises(ValueError):
            Food.create(name="   ", source=FoodSource.USER, calories_per_100g=Decimal(10))

    def test_negative_macros_are_refused(self) -> None:
        with pytest.raises(ValueError):
            Food.create(
                name="Impossible",
                source=FoodSource.USER,
                calories_per_100g=Decimal(100),
                protein_per_100g=Decimal(-5),
            )

    def test_water_must_be_a_positive_amount(self) -> None:
        with pytest.raises(ValueError):
            WaterLog.create(user_id=USER, local_date=TODAY, millilitres=_zero())

    def test_a_diary_entry_needs_a_positive_quantity(self) -> None:
        with pytest.raises(ValueError):
            DiaryEntry.for_food(
                user_id=USER,
                local_date=TODAY,
                meal_type=MealType.LUNCH,
                food=food(),
                quantity=_zero(),
            )


class TestAlcohol:
    """Ethanol is a fourth energy source, at 7 kcal/g.

    Without it the reconciliation rejects every beer and wine as a data-entry error —
    and a bulk import of European food data would silently drop the whole category.
    """

    def test_wine_reconciles_once_alcohol_is_counted(self) -> None:
        wine = Macros(
            calories=Decimal(85),
            protein_g=Decimal("0.1"),
            carbs_g=Decimal("2.6"),
            alcohol_g=Decimal("10.6"),
        )
        assert check_energy(wine).is_ok

    def test_wine_fails_when_alcohol_is_ignored(self) -> None:
        # The bug this column exists to fix: 85 kcal against 11 implied.
        without = Macros(calories=Decimal(85), protein_g=Decimal("0.1"), carbs_g=Decimal("2.6"))
        assert check_energy(without).verdict is EnergyVerdict.INCONSISTENT

    def test_alcohol_carries_seven_calories_a_gram(self) -> None:
        assert Macros(alcohol_g=Decimal(10)).energy_from_macros == Decimal(70)

    def test_alcohol_scales_with_the_portion(self) -> None:
        wine = Food.create(
            name="Κρασί",
            source=FoodSource.CURATED,
            calories_per_100g=Decimal(85),
            carbs_per_100g=Decimal("2.6"),
            alcohol_per_100g=Decimal("10.6"),
        )
        glass = wine.macros_for(Decimal(150))
        assert glass.alcohol_g == Decimal("15.90")

    def test_alcohol_sums_across_a_day(self) -> None:
        entries = [
            DiaryEntry.quick_add(
                user_id=USER,
                local_date=TODAY,
                meal_type=MealType.DINNER,
                macros=Macros(calories=Decimal(85), alcohol_g=Decimal(10)),
            ),
            DiaryEntry.quick_add(
                user_id=USER,
                local_date=TODAY,
                meal_type=MealType.DINNER,
                macros=Macros(calories=Decimal(85), alcohol_g=Decimal(10)),
            ),
        ]
        assert summarise_day(entries, []).macros.alcohol_g == Decimal("20.00")

    def test_negative_alcohol_is_refused(self) -> None:
        with pytest.raises(ValueError):
            Food.create(
                name="Impossible",
                source=FoodSource.USER,
                calories_per_100g=Decimal(100),
                carbs_per_100g=Decimal(25),
                alcohol_per_100g=Decimal(-1),
            )


class TestCuratedSeed:
    def test_every_curated_food_reconciles(self) -> None:
        """The seed must satisfy the database constraint before it is ever inserted."""
        from coresync.infrastructure.seed.foods import GREEK_STAPLES, as_seed

        for raw in GREEK_STAPLES:
            item = as_seed(raw)
            result = check_energy(
                Macros(
                    calories=item.calories,
                    protein_g=item.protein,
                    carbs_g=item.carbs,
                    fat_g=item.fat,
                    alcohol_g=item.alcohol,
                )
            )
            assert result.is_ok, f"{item.name}: stated {item.calories}, implied {result.implied}"

    def test_every_curated_food_has_a_serving(self) -> None:
        """Logging in grams alone is not how anyone eats."""
        from coresync.infrastructure.seed.foods import GREEK_STAPLES, as_seed

        for raw in GREEK_STAPLES:
            assert as_seed(raw).servings, as_seed(raw).name


class TestNutritionStreak:
    """Consecutive logged days.

    Counted over days that have an entry, never over calories: a genuine fasting day, or
    a day of nothing but black coffee, must not break a run the person believes they
    kept. A streak that punishes honest logging teaches people to log dishonestly.
    """

    def _days(self, *offsets: int, anchor: date = date(2026, 8, 24)) -> list[date]:
        return [anchor - timedelta(days=n) for n in offsets]

    def test_no_days_logged(self) -> None:
        result = nutrition_streak([], today=date(2026, 8, 24))
        assert result == NutritionStreak(current=0, longest=0, last_date=None)

    def test_a_single_day_today(self) -> None:
        result = nutrition_streak(self._days(0), today=date(2026, 8, 24))
        assert result.current == 1
        assert result.longest == 1

    def test_consecutive_days_ending_today(self) -> None:
        result = nutrition_streak(self._days(0, 1, 2, 3), today=date(2026, 8, 24))
        assert result.current == 4
        assert result.longest == 4

    def test_today_not_logged_yet_does_not_break_it(self) -> None:
        """The day is still in progress. Breaking the streak at 00:01 would be absurd."""
        result = nutrition_streak(self._days(1, 2, 3), today=date(2026, 8, 24))
        assert result.current == 3

    def test_a_missed_yesterday_breaks_it(self) -> None:
        result = nutrition_streak(self._days(2, 3, 4), today=date(2026, 8, 24))
        assert result.current == 0
        assert result.longest == 3

    def test_the_longest_run_survives_a_break(self) -> None:
        """A broken streak is still a record worth keeping."""
        older = self._days(10, 11, 12, 13, 14)
        recent = self._days(0, 1)
        result = nutrition_streak(older + recent, today=date(2026, 8, 24))
        assert result.current == 2
        assert result.longest == 5

    def test_duplicate_days_count_once(self) -> None:
        """Three meals on one day is one logged day."""
        anchor = date(2026, 8, 24)
        result = nutrition_streak([anchor, anchor, anchor], today=anchor)
        assert result.current == 1

    def test_days_arrive_in_any_order(self) -> None:
        result = nutrition_streak(self._days(2, 0, 3, 1), today=date(2026, 8, 24))
        assert result.current == 4

    def test_the_last_date_is_the_most_recent_logged_day(self) -> None:
        result = nutrition_streak(self._days(1, 2), today=date(2026, 8, 24))
        assert result.last_date == date(2026, 8, 23)

    def test_a_long_abandoned_streak_reports_zero_current(self) -> None:
        result = nutrition_streak(self._days(90, 91, 92), today=date(2026, 8, 24))
        assert result.current == 0
        assert result.longest == 3
        assert result.last_date == date(2026, 8, 24) - timedelta(days=90)

    def test_a_streak_across_a_month_boundary(self) -> None:
        result = nutrition_streak(
            [date(2026, 8, 1), date(2026, 7, 31), date(2026, 7, 30)],
            today=date(2026, 8, 1),
        )
        assert result.current == 3
