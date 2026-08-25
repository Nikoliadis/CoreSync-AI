"""The exercise-media importer, and above all what it refuses to do.

The interesting behaviour here is negative. It would be easy to reach 100% coverage with
fuzzy name matching and ship a catalogue where "Barbell Row" shows a photograph of a rear
delt row. Someone learning the movement would copy what they saw, under load. These tests
pin the strictness in place so a later "improvement" to the matcher has to argue with
them first.
"""

from __future__ import annotations

from coresync.infrastructure.seed.exercise_media import ALIASES, _normalise


class TestNormalisation:
    def test_ignores_case_punctuation_and_separators(self) -> None:
        assert _normalise("Close-Grip Bench Press") == _normalise("close grip bench press")
        assert _normalise("Captain's Chair Leg Raise") == "captain s chair leg raise"

    def test_collapses_repeated_whitespace(self) -> None:
        assert _normalise("Barbell   Squat") == "barbell squat"

    def test_treats_slashes_as_separators(self) -> None:
        # Their catalogue uses "Bradford/Rocky Presses"; ours would never guess the slash.
        assert _normalise("Bradford/Rocky Presses") == "bradford rocky presses"

    def test_is_stable_on_an_already_normal_name(self) -> None:
        assert _normalise("barbell squat") == "barbell squat"


class TestTheAliasTable:
    def test_maps_slugs_not_names(self) -> None:
        # Keyed by our slug because our display names may be reworded; the slug is the
        # stable identifier and changing it is already a migration.
        for key in ALIASES:
            assert key == key.lower()
            assert " " not in key

    def test_never_maps_two_of_our_slugs_to_conflicting_movements(self) -> None:
        # Several of ours legitimately share one photograph — a high-bar and a low-bar
        # squat look near enough alike. This just pins that sharing is deliberate and
        # bounded rather than the matcher having collapsed everything onto one entry.
        from collections import Counter

        most_reused = Counter(ALIASES.values()).most_common(1)
        assert most_reused, "the alias table should not be empty"
        assert most_reused[0][1] <= 3

    def test_does_not_pair_a_push_with_a_pull(self) -> None:
        # The specific mistake this suite exists for: an earlier draft mapped
        # "weighted-push-up" onto "Weighted Pull Ups".
        for slug, target in ALIASES.items():
            if "push-up" in slug:
                assert "pull" not in target.lower(), f"{slug} -> {target}"

    def test_does_not_pair_a_squat_with_a_press(self) -> None:
        for slug, target in ALIASES.items():
            if slug.endswith("-squat"):
                assert "press" not in target.lower(), f"{slug} -> {target}"

    def test_covers_the_movements_people_actually_log(self) -> None:
        # A catalogue that has pictures for obscure work and none for the big lifts would
        # be worse than useless. These five are the spine of most programmes.
        for slug in ("back-squat", "deadlift", "barbell-bench-press", "barbell-row", "pull-up"):
            assert slug in ALIASES, slug
