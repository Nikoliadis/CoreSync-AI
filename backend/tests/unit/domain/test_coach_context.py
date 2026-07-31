"""The deterministic detectors.

These are the reason insight precision can be held to 85% (docs/10 §8): every flag is a
function of numbers, so it can be pinned to a known history and asserted exactly. A
detector that fires on the wrong input is a coach that tells someone their squat has
plateaued when it has not — the failure that makes the whole feature ignorable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from coresync.domain.coaching.context import (
    CoachContext,
    ContextFlag,
    CurrentContext,
    FlagDetector,
    ProfileContext,
    StalledExercise,
    TrainingWindow,
)

TODAY = date(2026, 7, 31)
detector = FlagDetector()


def _profile(goal: str | None = "lose_fat", age: int | None = 30) -> ProfileContext:
    return ProfileContext(
        display_name="Alex",
        age=age,
        gender="male",
        height_cm=Decimal("180"),
        experience="intermediate",
        activity_level="moderate",
        goal=goal,
        target_rate_kg_per_week=Decimal("-0.5"),
    )


def _window(
    *,
    sessions: int = 4,
    volume: str = "20000",
    sets: int = 60,
    by_muscle: dict[str, str] | None = None,
    set_counts: dict[str, int] | None = None,
) -> TrainingWindow:
    return TrainingWindow(
        sessions=sessions,
        total_volume_kg=Decimal(volume),
        total_sets=sets,
        avg_duration_min=60,
        volume_by_muscle_group={k: Decimal(v) for k, v in (by_muscle or {}).items()},
        set_counts_by_muscle_group=set_counts or {},
    )


def _context(
    *,
    week: TrainingWindow | None = None,
    month: TrainingWindow | None = None,
    rate: str | None = None,
    days_since: int | None = 1,
    streak: int = 3,
    stalled: list[StalledExercise] | None = None,
    goal: str | None = "lose_fat",
) -> CoachContext:
    return CoachContext(
        today=TODAY,
        profile=_profile(goal=goal),
        current=CurrentContext(
            weight_kg=Decimal("82"),
            trend_weight_kg=Decimal("82.4"),
            trend_kg_per_week=Decimal(rate) if rate is not None else None,
            target_calories=Decimal("2400"),
            target_protein_g=Decimal("165"),
        ),
        training_7d=week or _window(),
        training_30d=month or _window(sessions=16, volume="80000", sets=240),
        stalled_exercises=stalled or [],
        days_since_last_workout=days_since,
        workout_streak=streak,
    )


class TestTrainingLoad:
    def test_a_normal_week_raises_no_load_flag(self) -> None:
        flags = detector.detect(_context())
        assert ContextFlag.OVERREACHING not in flags
        assert ContextFlag.TRAINING_DROPOFF not in flags

    def test_a_volume_spike_is_overreaching(self) -> None:
        # 40,000kg against a 20,000kg weekly average — a ratio of 2.0.
        week = _window(volume="40000")
        assert ContextFlag.OVERREACHING in detector.detect(_context(week=week))

    def test_a_collapse_in_volume_is_a_dropoff(self) -> None:
        week = _window(sessions=1, volume="5000", sets=15)
        assert ContextFlag.TRAINING_DROPOFF in detector.detect(_context(week=week))

    def test_too_little_history_produces_no_load_verdict(self) -> None:
        """A first fortnight would otherwise look like a permanent spike."""
        month = _window(sessions=2, volume="8000", sets=24)
        flags = detector.detect(_context(week=_window(volume="8000"), month=month))
        assert ContextFlag.OVERREACHING not in flags
        assert ContextFlag.TRAINING_DROPOFF not in flags


class TestImbalance:
    def test_an_evenly_trained_week_is_not_imbalanced(self) -> None:
        week = _window(set_counts={"chest": 12, "back": 14, "legs": 16})
        assert ContextFlag.VOLUME_IMBALANCE not in detector.detect(_context(week=week))

    def test_a_starved_muscle_group_is_flagged_on_set_counts(self) -> None:
        week = _window(set_counts={"chest": 20, "back": 22, "legs": 1})
        assert ContextFlag.VOLUME_IMBALANCE in detector.detect(_context(week=week))

    def test_volume_share_is_the_fallback_when_set_counts_are_absent(self) -> None:
        """The daily aggregates carry tonnage but not sets per group today."""
        week = _window(sets=40, by_muscle={"chest": "8000", "back": "9000", "legs": "100"})
        assert ContextFlag.VOLUME_IMBALANCE in detector.detect(_context(week=week))

    def test_the_volume_fallback_tolerates_ordinary_programme_structure(self) -> None:
        """Tonnage shares are naturally skewed; a light day is not an imbalance."""
        week = _window(sets=40, by_muscle={"chest": "5000", "back": "9000", "legs": "12000"})
        assert ContextFlag.VOLUME_IMBALANCE not in detector.detect(_context(week=week))

    def test_a_two_group_week_is_not_judged(self) -> None:
        week = _window(set_counts={"chest": 20, "back": 1})
        assert ContextFlag.VOLUME_IMBALANCE not in detector.detect(_context(week=week))


class TestWeight:
    def test_a_rate_within_the_safe_ceiling_is_not_flagged(self) -> None:
        assert ContextFlag.RAPID_WEIGHT_CHANGE not in detector.detect(_context(rate="-0.6"))

    def test_losing_faster_than_a_kilo_a_week_is_flagged(self) -> None:
        assert ContextFlag.RAPID_WEIGHT_CHANGE in detector.detect(_context(rate="-1.4"))

    def test_rapid_gain_is_flagged_too(self) -> None:
        """The ceiling is on magnitude: gaining 1.5kg a week is not muscle."""
        assert ContextFlag.RAPID_WEIGHT_CHANGE in detector.detect(_context(rate="1.5"))

    def test_a_flat_trend_against_an_active_goal_is_stalled(self) -> None:
        assert ContextFlag.WEIGHT_STALLED in detector.detect(_context(rate="0.01"))

    def test_a_flat_trend_with_no_goal_is_not_stalled(self) -> None:
        """Maintaining is not failing when maintenance is the point."""
        assert ContextFlag.WEIGHT_STALLED not in detector.detect(_context(rate="0.01", goal=None))

    def test_no_weigh_ins_produce_no_weight_verdict(self) -> None:
        flags = detector.detect(_context(rate=None))
        assert ContextFlag.RAPID_WEIGHT_CHANGE not in flags
        assert ContextFlag.WEIGHT_STALLED not in flags


class TestRecency:
    def test_a_recent_session_raises_nothing(self) -> None:
        flags = detector.detect(_context(days_since=1))
        assert ContextFlag.NO_RECENT_DATA not in flags
        assert ContextFlag.STREAK_AT_RISK not in flags

    def test_a_gap_with_a_live_streak_is_a_risk(self) -> None:
        assert ContextFlag.STREAK_AT_RISK in detector.detect(_context(days_since=3, streak=5))

    def test_a_gap_without_a_streak_is_not_a_risk(self) -> None:
        assert ContextFlag.STREAK_AT_RISK not in detector.detect(_context(days_since=3, streak=0))

    def test_a_long_absence_is_stale_data_not_a_streak_risk(self) -> None:
        flags = detector.detect(_context(days_since=40, streak=5))
        assert ContextFlag.NO_RECENT_DATA in flags
        assert ContextFlag.STREAK_AT_RISK not in flags

    def test_never_having_trained_is_stale_data(self) -> None:
        assert ContextFlag.NO_RECENT_DATA in detector.detect(_context(days_since=None))


class TestPlateau:
    def test_stalled_exercises_raise_the_plateau_flag(self) -> None:
        stalled = [StalledExercise("Barbell Back Squat", 7, Decimal("142.5"))]
        assert ContextFlag.SQUAT_PLATEAU in detector.detect(_context(stalled=stalled))

    def test_no_stalled_exercises_means_no_plateau(self) -> None:
        assert ContextFlag.SQUAT_PLATEAU not in detector.detect(_context())


class TestNutritionHonesty:
    def test_nutrition_is_always_reported_as_untracked(self) -> None:
        """Phase 3 does not exist. The coach is told so rather than shown zeros."""
        assert ContextFlag.NUTRITION_NOT_TRACKED in detector.detect(_context())

    def test_the_prompt_bundle_states_nutrition_is_null_not_zero(self) -> None:
        bundle = _context().to_prompt_dict()
        assert bundle["nutrition"] is None

    def test_the_bundle_keeps_decimals_exact_as_strings(self) -> None:
        bundle = _context(rate="-0.55").to_prompt_dict()
        assert bundle["current"]["trendKgPerWeek"] == "-0.55"
        assert bundle["current"]["targets"]["calories"] == "2400"

    def test_the_bundle_stays_small(self) -> None:
        """Under ~3,000 tokens of aggregates; a fat bundle buries the signal."""
        import json

        rendered = json.dumps(_context().to_prompt_dict())
        assert len(rendered) < 4000, len(rendered)
