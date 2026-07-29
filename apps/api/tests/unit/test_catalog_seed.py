"""Integrity of the seeded catalog.

The seed is data, and data rots quietly: a typo'd muscle slug produces an exercise that
no filter can find, and a duplicate slug breaks the partial unique index only once it
reaches a database. Both are caught here, in a test that needs no infrastructure.
"""

from __future__ import annotations

from coresync.domain.catalog.entities import Difficulty, ForceType, LoggingType, Mechanic
from coresync.infrastructure.seed.exercises import EXERCISES
from coresync.infrastructure.seed.reference import (
    CATEGORIES,
    EQUIPMENT,
    MUSCLE_GROUPS,
    MUSCLES,
    catalog_id,
)

MUSCLE_SLUGS = {slug for slug, _, _ in MUSCLES}
EQUIPMENT_SLUGS = {slug for slug, _, _ in EQUIPMENT}
CATEGORY_SLUGS = {slug for slug, _, _ in CATEGORIES}
GROUP_SLUGS = {slug for slug, _, _ in MUSCLE_GROUPS}


def _split(column: str) -> list[str]:
    return [part for part in column.split("|") if part]


class TestReferenceData:
    def test_slugs_are_unique_within_each_table(self) -> None:
        for name, rows in (
            ("muscle_groups", MUSCLE_GROUPS),
            ("muscles", MUSCLES),
            ("equipment", EQUIPMENT),
            ("categories", CATEGORIES),
        ):
            slugs = [row[0] for row in rows]
            assert len(slugs) == len(set(slugs)), f"duplicate slug in {name}"

    def test_every_muscle_belongs_to_a_real_group(self) -> None:
        for slug, _, group in MUSCLES:
            assert group in GROUP_SLUGS, f"muscle '{slug}' references unknown group '{group}'"

    def test_ids_are_deterministic_across_runs(self) -> None:
        """A rebuilt database must not re-key the catalog and orphan logged workouts."""
        assert catalog_id("exercise", "barbell-bench-press") == catalog_id(
            "exercise", "barbell-bench-press"
        )

    def test_ids_are_namespaced_by_kind(self) -> None:
        assert catalog_id("muscle", "biceps") != catalog_id("equipment", "biceps")


class TestExerciseCatalog:
    def test_catalog_is_substantial(self) -> None:
        assert len(EXERCISES) >= 250

    def test_slugs_are_unique(self) -> None:
        slugs = [row[0] for row in EXERCISES]
        duplicates = {s for s in slugs if slugs.count(s) > 1}
        assert not duplicates, f"duplicate exercise slugs: {sorted(duplicates)}"

    def test_names_are_unique(self) -> None:
        names = [row[1] for row in EXERCISES]
        duplicates = {n for n in names if names.count(n) > 1}
        assert not duplicates, f"duplicate exercise names: {sorted(duplicates)}"

    def test_every_reference_resolves(self) -> None:
        for row in EXERCISES:
            slug, _, category, force, mechanic, difficulty, logging_type = row[:7]
            primary, secondary, equipment = row[8], row[9], row[10]

            assert category in CATEGORY_SLUGS, f"{slug}: unknown category '{category}'"
            for muscle in _split(primary) + _split(secondary):
                assert muscle in MUSCLE_SLUGS, f"{slug}: unknown muscle '{muscle}'"
            for item in _split(equipment):
                assert item in EQUIPMENT_SLUGS, f"{slug}: unknown equipment '{item}'"

            assert difficulty in {d.value for d in Difficulty}, f"{slug}: bad difficulty"
            if force:
                assert force in {f.value for f in ForceType}, f"{slug}: bad force type"
            if mechanic:
                assert mechanic in {m.value for m in Mechanic}, f"{slug}: bad mechanic"
            if logging_type:
                assert logging_type in {t.value for t in LoggingType}, f"{slug}: bad logging type"

    def test_every_exercise_has_at_least_one_primary_muscle(self) -> None:
        """Without a primary mover an exercise is invisible to muscle-group filtering
        and contributes nothing to per-muscle volume."""
        for row in EXERCISES:
            assert _split(row[8]), f"{row[0]} has no primary muscle"

    def test_every_exercise_declares_equipment(self) -> None:
        """The "what can I do at home?" filter depends on this being complete."""
        for row in EXERCISES:
            assert _split(row[10]), f"{row[0]} declares no equipment"

    def test_weight_logging_exercises_are_not_bodyweight_only(self) -> None:
        """A weight_reps exercise tagged only 'bodyweight' would ask for a load the user
        cannot add, which is how NULL-riddled set rows start."""
        for row in EXERCISES:
            slug, logging_type, equipment = row[0], row[6], _split(row[10])
            if (logging_type or "weight_reps") == "weight_reps":
                assert equipment != ["bodyweight"], f"{slug}: weight_reps but bodyweight-only"

    def test_cardio_exercises_use_a_time_or_distance_logging_type(self) -> None:
        for row in EXERCISES:
            slug, category, logging_type = row[0], row[2], row[6]
            if category == "cardio":
                assert logging_type in ("time", "distance_time"), f"{slug}: bad cardio logging"

    def test_every_muscle_group_has_exercises_targeting_it(self) -> None:
        """A group with no primary exercises is a dead filter in the UI."""
        muscle_to_group = {slug: group for slug, _, group in MUSCLES}
        covered = {muscle_to_group[muscle] for row in EXERCISES for muscle in _split(row[8])}
        assert GROUP_SLUGS - covered == set()

    def test_every_equipment_item_is_used(self) -> None:
        """Unused equipment is a filter that always returns nothing."""
        used = {item for row in EXERCISES for item in _split(row[10])}
        assert EQUIPMENT_SLUGS - used == set()
