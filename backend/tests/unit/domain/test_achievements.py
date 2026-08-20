"""Achievement rules.

Two properties matter more than any individual threshold: nothing is ever awarded
twice, and nothing can be taken away. Both are asserted directly, because an
achievement feed that double-posts or silently revokes is worse than none at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from coresync.domain.achievements.definitions import (
    BY_CODE,
    DEFINITIONS,
    MEASURES,
    AchievementSnapshot,
    evaluate,
)


def snapshot(**overrides: object) -> AchievementSnapshot:
    base = {
        "total_sessions": 0,
        "total_volume_kg": Decimal(0),
        "longest_streak_weeks": 0,
        "current_streak_weeks": 0,
        "total_prs": 0,
        "heaviest_lift_kg": Decimal(0),
        "distinct_exercises": 0,
        "weeks_since_first_session": 0,
    }
    base.update(overrides)
    return AchievementSnapshot(**base)  # type: ignore[arg-type]


class TestNothingForNothing:
    def test_a_brand_new_account_earns_nothing(self) -> None:
        assert evaluate(snapshot(), set()) == []

    def test_one_session_earns_only_the_first_milestone(self) -> None:
        earned = {d.code for d in evaluate(snapshot(total_sessions=1), set())}
        assert earned == {"first_session"}


class TestThresholds:
    @pytest.mark.parametrize(
        ("sessions", "expected"),
        [
            (9, {"first_session"}),
            (10, {"first_session", "ten_sessions"}),
            (50, {"first_session", "ten_sessions", "fifty_sessions"}),
        ],
    )
    def test_session_counts_award_in_order(self, sessions: int, expected: set[str]) -> None:
        earned = {d.code for d in evaluate(snapshot(total_sessions=sessions), set())}
        assert earned == expected

    def test_the_boundary_is_inclusive(self) -> None:
        """Hitting the number exactly earns it — 10 sessions is 'ten sessions'."""
        earned = {d.code for d in evaluate(snapshot(total_sessions=10), set())}
        assert "ten_sessions" in earned

    def test_one_short_earns_nothing_new(self) -> None:
        earned = {d.code for d in evaluate(snapshot(total_prs=24), set())}
        assert "twenty_five_prs" not in earned

    def test_volume_is_measured_in_kilograms(self) -> None:
        earned = {d.code for d in evaluate(snapshot(total_volume_kg=Decimal(100_000)), set())}
        assert "volume_100t" in earned


class TestNeverAwardedTwice:
    def test_an_earned_achievement_is_not_returned_again(self) -> None:
        state = snapshot(total_sessions=60)
        first = {d.code for d in evaluate(state, set())}
        second = evaluate(state, first)
        assert second == []

    def test_only_the_newly_crossed_one_is_returned(self) -> None:
        already = {"first_session", "ten_sessions"}
        earned = {d.code for d in evaluate(snapshot(total_sessions=50), already)}
        assert earned == {"fifty_sessions"}


class TestNeverPunitive:
    def test_streaks_are_judged_on_the_longest_not_the_current(self) -> None:
        """A week off must not revoke a badge.

        Measuring the current streak would mean the achievement quietly disappears the
        moment someone rests — the punitive design this product refuses (docs/09 §1).
        """
        lapsed = snapshot(longest_streak_weeks=12, current_streak_weeks=0)
        earned = {d.code for d in evaluate(lapsed, set())}
        assert "streak_4_weeks" in earned
        assert "streak_12_weeks" in earned

    def test_no_definition_measures_the_current_streak(self) -> None:
        assert "current_streak_weeks" not in MEASURES.values()

    def test_evaluation_is_monotonic(self) -> None:
        """More effort never earns less."""
        smaller = {d.code for d in evaluate(snapshot(total_sessions=10), set())}
        larger = {d.code for d in evaluate(snapshot(total_sessions=200), set())}
        assert smaller <= larger


class TestDefinitionsAreWellFormed:
    def test_every_definition_has_a_measure(self) -> None:
        """A definition with no measure would never award, silently."""
        missing = [d.code for d in DEFINITIONS if d.code not in MEASURES]
        assert missing == []

    def test_codes_are_unique(self) -> None:
        assert len(BY_CODE) == len(DEFINITIONS)

    def test_every_measure_names_a_real_snapshot_field(self) -> None:
        fields = set(AchievementSnapshot.__slots__)
        assert set(MEASURES.values()) <= fields

    def test_thresholds_are_positive(self) -> None:
        assert all(d.threshold > 0 for d in DEFINITIONS)

    def test_descriptions_never_shame(self) -> None:
        """Copy rule, enforced rather than trusted (docs/09 §10)."""
        banned = ("failed", "missed", "skipped", "lost", "broke")
        for definition in DEFINITIONS:
            text = f"{definition.name} {definition.description}".lower()
            assert not any(word in text for word in banned), definition.code


class TestProgress:
    def test_progress_is_a_fraction_of_the_threshold(self) -> None:
        definition = BY_CODE["ten_sessions"]
        assert definition.progress(Decimal(5)) == Decimal("0.5")

    def test_progress_clamps_at_one(self) -> None:
        definition = BY_CODE["ten_sessions"]
        assert definition.progress(Decimal(500)) == Decimal(1)

    def test_progress_of_nothing_is_zero(self) -> None:
        assert BY_CODE["ten_sessions"].progress(Decimal(0)) == Decimal(0)
