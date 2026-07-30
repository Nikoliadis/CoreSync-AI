"""Personal record detection, volume and 1RM maths.

These are the rules a lifter notices immediately when they are wrong: a PR that fires on
a warm-up, a celebration for matching last week, or tonnage that does not match the sets
on screen. All pure, so they are unit tests rather than integration ones.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from coresync.core.ids import uuid7
from coresync.domain.workout.entities import (
    PersonalRecord,
    RecordType,
    SessionSet,
    SetType,
    estimated_one_rep_max,
)
from coresync.domain.workout.services import (
    PersonalRecordDetector,
    VolumeCalculator,
)

EXERCISE = uuid7()
OTHER_EXERCISE = uuid7()
USER = uuid7()
TODAY = date(2026, 7, 29)


def make_set(
    *,
    reps: int | None = 8,
    weight: str | None = "100",
    set_type: SetType = SetType.NORMAL,
    is_completed: bool = True,
    duration: int | None = None,
    distance: str | None = None,
    exercise_id: UUID = EXERCISE,
) -> SessionSet:
    return SessionSet(
        id=uuid7(),
        session_exercise_id=uuid7(),
        set_number=1,
        set_type=set_type,
        reps=reps,
        weight_kg=Decimal(weight) if weight is not None else None,
        duration_seconds=duration,
        distance_m=Decimal(distance) if distance is not None else None,
        is_completed=is_completed,
        exercise_id=exercise_id,
    )


def existing(record_type: RecordType, value: str) -> PersonalRecord:
    return PersonalRecord.create(
        user_id=USER,
        exercise_id=EXERCISE,
        record_type=record_type,
        value=Decimal(value),
        achieved_on=TODAY,
    )


# ------------------------------------------------------------------ 1RM formula
class TestEstimatedOneRepMax:
    def test_epley_at_eight_reps(self) -> None:
        # 100 x (1 + 8/30) = 126.67
        assert estimated_one_rep_max(Decimal("100"), 8) == Decimal("126.67")

    def test_single_rep_is_the_weight_itself(self) -> None:
        assert estimated_one_rep_max(Decimal("140"), 1) == Decimal("144.67")

    @pytest.mark.parametrize("reps", [16, 20, 30, 100])
    def test_high_rep_sets_produce_no_estimate(self, reps: int) -> None:
        """Epley diverges past ~15 reps, so a 30-rep set is noise rather than a 1RM."""
        assert estimated_one_rep_max(Decimal("60"), reps) is None

    @pytest.mark.parametrize(
        ("weight", "reps"),
        [(None, 8), (Decimal("100"), None), (Decimal("0"), 5), (Decimal("100"), 0)],
    )
    def test_missing_or_zero_inputs_produce_no_estimate(
        self, weight: Decimal | None, reps: int | None
    ) -> None:
        assert estimated_one_rep_max(weight, reps) is None

    @given(
        weight=st.decimals(min_value=Decimal("0.5"), max_value=Decimal("500"), places=2),
        reps=st.integers(min_value=1, max_value=15),
    )
    def test_estimate_is_never_below_the_weight_lifted(self, weight: Decimal, reps: int) -> None:
        """A 1RM estimate lower than a weight actually lifted would be incoherent."""
        estimate = estimated_one_rep_max(weight, reps)
        assert estimate is not None
        assert estimate >= weight


# ------------------------------------------------------------------- detection
class TestPersonalRecordDetector:
    def setup_method(self) -> None:
        self.detector = PersonalRecordDetector()

    def test_first_ever_session_sets_every_applicable_record(self) -> None:
        detected = self.detector.detect([make_set()], {})
        types = {d.record_type for d in detected}
        assert types == {
            RecordType.MAX_WEIGHT,
            RecordType.MAX_REPS,
            RecordType.MAX_VOLUME_SET,
            RecordType.EST_1RM,
        }
        assert all(d.is_first_ever for d in detected)

    def test_warmups_never_count(self) -> None:
        """A warm-up single at a heavy weight must not steal the weight record."""
        sets = [make_set(weight="200", reps=1, set_type=SetType.WARMUP)]
        assert self.detector.detect(sets, {}) == []

    def test_incomplete_sets_never_count(self) -> None:
        sets = [make_set(weight="200", is_completed=False)]
        assert self.detector.detect(sets, {}) == []

    def test_matching_an_existing_record_is_not_a_record(self) -> None:
        """Ties do not count, or repeating a working weight would celebrate weekly."""
        current = {(EXERCISE, RecordType.MAX_WEIGHT): existing(RecordType.MAX_WEIGHT, "100")}
        detected = self.detector.detect([make_set(weight="100", reps=1)], current)
        assert RecordType.MAX_WEIGHT not in {d.record_type for d in detected}

    def test_beating_an_existing_record_reports_the_improvement(self) -> None:
        current = {(EXERCISE, RecordType.MAX_WEIGHT): existing(RecordType.MAX_WEIGHT, "100")}
        detected = self.detector.detect([make_set(weight="105", reps=1)], current)
        weight_pr = next(d for d in detected if d.record_type is RecordType.MAX_WEIGHT)
        assert weight_pr.value == Decimal("105")
        assert weight_pr.previous_value == Decimal("100")
        assert weight_pr.improvement == Decimal("5")
        assert not weight_pr.is_first_ever

    def test_records_are_tracked_per_exercise(self) -> None:
        """A squat PR must not suppress a bench PR at a lower weight."""
        sets = [
            make_set(weight="200", reps=5, exercise_id=EXERCISE),
            make_set(weight="80", reps=5, exercise_id=OTHER_EXERCISE),
        ]
        detected = self.detector.detect(sets, {})
        assert {d.exercise_id for d in detected} == {EXERCISE, OTHER_EXERCISE}

    def test_best_set_of_the_session_wins_each_record(self) -> None:
        sets = [
            make_set(weight="100", reps=5),
            make_set(weight="120", reps=3),
            make_set(weight="90", reps=12),
        ]
        detected = {d.record_type: d for d in self.detector.detect(sets, {})}
        assert detected[RecordType.MAX_WEIGHT].value == Decimal("120")
        assert detected[RecordType.MAX_REPS].value == Decimal("12")
        # 90 x 12 = 1080 beats 100 x 5 = 500 and 120 x 3 = 360.
        assert detected[RecordType.MAX_VOLUME_SET].value == Decimal("1080")

    def test_each_record_points_at_the_set_that_proved_it(self) -> None:
        heavy = make_set(weight="150", reps=2)
        detected = self.detector.detect([make_set(weight="100", reps=5), heavy], {})
        weight_pr = next(d for d in detected if d.record_type is RecordType.MAX_WEIGHT)
        assert weight_pr.session_set_id == heavy.id
        assert weight_pr.reps_at_value == 2

    def test_weight_without_reps_is_not_a_weight_record(self) -> None:
        """Loading a bar and not lifting it is not a personal record."""
        detected = self.detector.detect([make_set(weight="300", reps=0, duration=30)], {})
        assert RecordType.MAX_WEIGHT not in {d.record_type for d in detected}

    def test_time_based_exercises_produce_duration_records(self) -> None:
        detected = self.detector.detect([make_set(reps=None, weight=None, duration=120)], {})
        assert {d.record_type for d in detected} == {RecordType.MAX_DURATION}

    def test_distance_exercises_produce_distance_records(self) -> None:
        detected = self.detector.detect(
            [make_set(reps=None, weight=None, duration=1800, distance="5000")], {}
        )
        types = {d.record_type for d in detected}
        assert types == {RecordType.MAX_DURATION, RecordType.MAX_DISTANCE}

    def test_no_sets_means_no_records(self) -> None:
        assert self.detector.detect([], {}) == []

    def test_sets_without_an_exercise_id_are_ignored(self) -> None:
        """A record cannot be attributed to an unknown exercise."""
        orphan = make_set()
        orphan.exercise_id = None
        assert self.detector.detect([orphan], {}) == []


# ---------------------------------------------------------------------- volume
class TestVolumeCalculator:
    def setup_method(self) -> None:
        self.calculator = VolumeCalculator()

    def test_volume_is_weight_times_reps(self) -> None:
        assert self.calculator.total([make_set(weight="100", reps=8)]) == Decimal("800")

    def test_warmups_are_excluded_from_volume(self) -> None:
        sets = [
            make_set(weight="100", reps=8),
            make_set(weight="60", reps=10, set_type=SetType.WARMUP),
        ]
        assert self.calculator.total(sets) == Decimal("800")

    def test_incomplete_sets_are_excluded(self) -> None:
        sets = [make_set(weight="100", reps=8), make_set(weight="100", reps=8, is_completed=False)]
        assert self.calculator.total(sets) == Decimal("800")

    def test_bodyweight_sets_contribute_no_tonnage(self) -> None:
        assert self.calculator.total([make_set(weight=None, reps=20)]) == Decimal("0")

    def test_empty_session_is_zero_not_an_error(self) -> None:
        assert self.calculator.total([]) == Decimal("0")

    def test_volume_splits_across_muscle_groups_by_contribution(self) -> None:
        """A bench press attributed wholly to chest would under-count triceps by a third."""
        contributions = {EXERCISE: {"chest": Decimal("0.6"), "arms": Decimal("0.4")}}
        split = self.calculator.by_muscle_group([make_set(weight="100", reps=10)], contributions)
        assert split == {"chest": Decimal("600.00"), "arms": Decimal("400.00")}

    def test_split_accumulates_across_sets(self) -> None:
        contributions = {EXERCISE: {"chest": Decimal("1")}}
        sets = [make_set(weight="100", reps=5), make_set(weight="80", reps=5)]
        assert self.calculator.by_muscle_group(sets, contributions) == {"chest": Decimal("900.00")}

    def test_exercise_without_contributions_is_skipped_not_crashed(self) -> None:
        assert self.calculator.by_muscle_group([make_set()], {}) == {}

    def test_set_counts_use_primary_movers_only(self) -> None:
        """ "34 sets of chest" means 34 sets targeting chest, not 34 where it assisted."""
        counts = self.calculator.set_counts_by_muscle_group(
            [make_set(), make_set(), make_set(set_type=SetType.WARMUP)],
            {EXERCISE: ["chest"]},
        )
        assert counts == {"chest": 2}
