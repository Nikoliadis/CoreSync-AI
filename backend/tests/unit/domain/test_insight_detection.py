"""Insight detection.

Code finds the pattern; the model only phrases it. These tests pin the finding half —
the half that decides whether the feed is useful or noise. Every case asserts on a
specific pattern being present or absent for a specific history, because "roughly right"
detection is what a 85% precision gate is designed to catch (docs/10 §8).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from coresync.application.coaching.insights import MAX_PER_RUN, detect_patterns
from coresync.domain.coaching.context import (
    CoachContext,
    ContextFlag,
    CurrentContext,
    ProfileContext,
    StalledExercise,
    TrainingWindow,
)
from coresync.domain.coaching.entities import InsightSeverity, InsightType

TODAY = date(2026, 7, 31)


def _context(
    *,
    flags: list[ContextFlag],
    stalled: list[StalledExercise] | None = None,
    streak: int = 4,
    days_since: int | None = 3,
    by_muscle: dict[str, str] | None = None,
) -> CoachContext:
    return CoachContext(
        today=TODAY,
        profile=ProfileContext(
            display_name="Alex",
            age=30,
            gender="female",
            height_cm=Decimal("170"),
            experience="intermediate",
            activity_level="moderate",
            goal="gain_muscle",
            target_rate_kg_per_week=Decimal("0.25"),
        ),
        current=CurrentContext(
            weight_kg=Decimal("70"),
            trend_weight_kg=Decimal("70.2"),
            trend_kg_per_week=Decimal("0.2"),
            target_calories=Decimal("2600"),
            target_protein_g=Decimal("150"),
        ),
        training_7d=TrainingWindow(
            sessions=5,
            total_volume_kg=Decimal("42000"),
            total_sets=70,
            avg_duration_min=70,
            # `is None` rather than `or`: an explicitly empty breakdown is a case under
            # test, not a request for the default.
            volume_by_muscle_group={
                k: Decimal(v)
                for k, v in (
                    {"chest": "9000", "legs": "300"} if by_muscle is None else by_muscle
                ).items()
            },
        ),
        training_30d=TrainingWindow(
            sessions=16,
            total_volume_kg=Decimal("80000"),
            total_sets=240,
            avg_duration_min=65,
        ),
        stalled_exercises=stalled or [],
        flags=flags,
        days_since_last_workout=days_since,
        workout_streak=streak,
    )


class TestNothingToSay:
    def test_a_clean_context_produces_no_insights(self) -> None:
        """Silence is the correct output most days. An insight every day is noise."""
        assert detect_patterns(_context(flags=[])) == []

    def test_untracked_nutrition_is_context_not_an_interruption(self) -> None:
        patterns = detect_patterns(_context(flags=[ContextFlag.NUTRITION_NOT_TRACKED]))
        assert patterns == []

    def test_stale_data_alone_does_not_generate_an_insight(self) -> None:
        assert detect_patterns(_context(flags=[ContextFlag.NO_RECENT_DATA])) == []


class TestPlateau:
    def test_a_plateau_flag_with_a_stalled_lift_produces_an_insight(self) -> None:
        stalled = [StalledExercise("Barbell Back Squat", 7, Decimal("142.5"))]
        patterns = detect_patterns(_context(flags=[ContextFlag.SQUAT_PLATEAU], stalled=stalled))
        assert len(patterns) == 1
        assert patterns[0].insight_type is InsightType.PLATEAU
        assert patterns[0].severity is InsightSeverity.SUGGESTION

    def test_the_evidence_names_the_lift_and_the_duration(self) -> None:
        """An insight a user cannot interrogate is an assertion."""
        stalled = [StalledExercise("Barbell Back Squat", 7, Decimal("142.5"))]
        evidence = detect_patterns(_context(flags=[ContextFlag.SQUAT_PLATEAU], stalled=stalled))[
            0
        ].evidence
        assert evidence["exercise"] == "Barbell Back Squat"
        assert evidence["weeksWithoutProgress"] == 7
        assert evidence["lastBestEst1rm"] == "142.5"

    def test_the_fallback_wording_is_usable_without_a_model(self) -> None:
        stalled = [StalledExercise("Barbell Back Squat", 7, Decimal("142.5"))]
        pattern = detect_patterns(_context(flags=[ContextFlag.SQUAT_PLATEAU], stalled=stalled))[0]
        assert "Barbell Back Squat" in pattern.fallback_title
        assert "7 weeks" in pattern.fallback_body
        assert len(pattern.fallback_title) <= 60

    def test_the_flag_without_a_stalled_lift_produces_nothing(self) -> None:
        """Defensive: the two must not disagree without failing quietly."""
        assert detect_patterns(_context(flags=[ContextFlag.SQUAT_PLATEAU], stalled=[])) == []


class TestOverreaching:
    def test_overreaching_is_a_warning_not_a_suggestion(self) -> None:
        patterns = detect_patterns(_context(flags=[ContextFlag.OVERREACHING]))
        assert patterns[0].insight_type is InsightType.OVERREACHING
        assert patterns[0].severity is InsightSeverity.WARNING

    def test_the_evidence_carries_both_windows_for_comparison(self) -> None:
        evidence = detect_patterns(_context(flags=[ContextFlag.OVERREACHING]))[0].evidence
        assert evidence["weekVolumeKg"] == "42000"
        assert evidence["monthVolumeKg"] == "80000"


class TestImbalance:
    def test_the_neglected_group_is_the_one_named(self) -> None:
        patterns = detect_patterns(
            _context(
                flags=[ContextFlag.VOLUME_IMBALANCE],
                by_muscle={"chest": "9000", "back": "8000", "legs": "300"},
            )
        )
        assert patterns[0].evidence["neglectedGroup"] == "legs"
        assert "legs" in patterns[0].fallback_title

    def test_no_muscle_breakdown_produces_no_imbalance_insight(self) -> None:
        assert detect_patterns(_context(flags=[ContextFlag.VOLUME_IMBALANCE], by_muscle={})) == []


class TestStreak:
    def test_a_streak_at_risk_is_informational(self) -> None:
        patterns = detect_patterns(_context(flags=[ContextFlag.STREAK_AT_RISK], streak=6))
        assert patterns[0].insight_type is InsightType.STREAK_RISK
        assert patterns[0].severity is InsightSeverity.INFO
        assert patterns[0].evidence["streak"] == 6

    def test_no_streak_means_nothing_is_at_risk(self) -> None:
        assert detect_patterns(_context(flags=[ContextFlag.STREAK_AT_RISK], streak=0)) == []


class TestVolume:
    def test_at_most_three_insights_are_produced_in_one_run(self) -> None:
        """Four warnings at once is a wall of text nobody reads."""
        patterns = detect_patterns(
            _context(
                flags=[
                    ContextFlag.SQUAT_PLATEAU,
                    ContextFlag.OVERREACHING,
                    ContextFlag.VOLUME_IMBALANCE,
                    ContextFlag.STREAK_AT_RISK,
                ],
                stalled=[StalledExercise("Deadlift", 6, Decimal("200"))],
                by_muscle={"chest": "9000", "back": "8000", "legs": "300"},
            )
        )
        assert len(patterns) == MAX_PER_RUN

    def test_every_pattern_carries_a_usable_fallback(self) -> None:
        patterns = detect_patterns(
            _context(
                flags=[ContextFlag.OVERREACHING, ContextFlag.STREAK_AT_RISK],
                streak=5,
            )
        )
        for pattern in patterns:
            assert pattern.fallback_title
            assert len(pattern.fallback_body) > 40
            assert pattern.observation
