"""Session and routine entity behaviour, plus streak rules."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from coresync.core.ids import uuid7
from coresync.domain.workout.entities import (
    Routine,
    RoutineExercise,
    RoutineSet,
    SessionSet,
    SessionStatus,
    SetType,
    WorkoutSession,
)
from coresync.domain.workout.services import StreakCalculator

USER = uuid7()
EXERCISE = uuid7()
STARTED = datetime(2026, 7, 29, 17, 0, tzinfo=UTC)
LOCAL_DATE = date(2026, 7, 29)


def new_session() -> WorkoutSession:
    return WorkoutSession.create(
        user_id=USER, name="Push Day", started_at=STARTED, local_date=LOCAL_DATE
    )


class TestWorkoutSession:
    def test_new_session_is_in_progress(self) -> None:
        session = new_session()
        assert session.is_active
        assert session.status is SessionStatus.IN_PROGRESS
        assert session.completed_at is None

    def test_unnamed_session_falls_back_rather_than_being_blank(self) -> None:
        session = WorkoutSession.create(
            user_id=USER, name="   ", started_at=STARTED, local_date=LOCAL_DATE
        )
        assert session.name == "Workout"

    def test_exercises_get_sequential_positions(self) -> None:
        session = new_session()
        first = session.add_exercise(exercise_id=EXERCISE)
        second = session.add_exercise(exercise_id=uuid7())
        assert (first.position, second.position) == (1, 2)

    def test_exercise_ids_are_deduplicated_in_order(self) -> None:
        session = new_session()
        second_exercise = uuid7()
        session.add_exercise(exercise_id=EXERCISE)
        session.add_exercise(exercise_id=second_exercise)
        session.add_exercise(exercise_id=EXERCISE)
        assert session.exercise_ids == [EXERCISE, second_exercise]

    def test_completion_computes_duration_and_totals(self) -> None:
        session = new_session()
        entry = session.add_exercise(exercise_id=EXERCISE)
        entry.sets = [
            SessionSet.create(
                session_exercise_id=entry.id, set_number=1, reps=8, weight_kg=Decimal("100")
            ),
            SessionSet.create(
                session_exercise_id=entry.id, set_number=2, reps=6, weight_kg=Decimal("110")
            ),
        ]

        session.complete(at=STARTED + timedelta(minutes=45), perceived_effort=8)

        assert session.status is SessionStatus.COMPLETED
        assert session.duration_seconds == 45 * 60
        assert session.total_sets == 2
        assert session.total_reps == 14
        assert session.total_volume_kg == Decimal("1460")  # 800 + 660
        assert session.perceived_effort == 8

    def test_paused_time_is_subtracted_from_the_recorded_duration(self) -> None:
        # A phone call mid-session is not training. The duration the history shows is the
        # time actually worked, so pausing has to change the stored number rather than
        # only the timer on screen.
        session = new_session()
        session.complete(at=STARTED + timedelta(minutes=45), paused_seconds=10 * 60)

        assert session.duration_seconds == 35 * 60

    def test_a_pause_longer_than_the_session_clamps_to_zero(self) -> None:
        # The value comes from a phone that may have slept or had its clock changed. A
        # negative duration would violate `duration_positive` and fail the whole
        # completion, losing the workout over a bad timer.
        session = new_session()
        session.complete(at=STARTED + timedelta(minutes=5), paused_seconds=60 * 60)

        assert session.duration_seconds == 0

    def test_negative_paused_time_is_refused(self) -> None:
        session = new_session()
        with pytest.raises(ValueError, match="negative"):
            session.complete(at=STARTED + timedelta(minutes=45), paused_seconds=-1)

    def test_completing_without_pausing_is_unchanged(self) -> None:
        session = new_session()
        session.complete(at=STARTED + timedelta(minutes=45))

        assert session.duration_seconds == 45 * 60

    def test_warmups_are_excluded_from_session_totals(self) -> None:
        session = new_session()
        entry = session.add_exercise(exercise_id=EXERCISE)
        entry.sets = [
            SessionSet.create(
                session_exercise_id=entry.id,
                set_number=1,
                reps=10,
                weight_kg=Decimal("60"),
                set_type=SetType.WARMUP,
            ),
            SessionSet.create(
                session_exercise_id=entry.id, set_number=2, reps=5, weight_kg=Decimal("100")
            ),
        ]
        session.complete(at=STARTED + timedelta(minutes=30))
        assert session.total_sets == 1
        assert session.total_volume_kg == Decimal("500")

    def test_completing_twice_is_refused(self) -> None:
        session = new_session()
        session.complete(at=STARTED + timedelta(minutes=10))
        with pytest.raises(ValueError, match="already completed"):
            session.complete(at=STARTED + timedelta(minutes=20))

    def test_a_session_cannot_finish_before_it_started(self) -> None:
        session = new_session()
        with pytest.raises(ValueError, match="cannot finish before"):
            session.complete(at=STARTED - timedelta(minutes=1))

    def test_discarded_session_cannot_be_completed(self) -> None:
        session = new_session()
        session.discard()
        assert session.status is SessionStatus.DISCARDED
        with pytest.raises(ValueError, match="already discarded"):
            session.complete(at=STARTED + timedelta(minutes=10))

    def test_reorder_rewrites_positions(self) -> None:
        session = new_session()
        first = session.add_exercise(exercise_id=uuid7())
        second = session.add_exercise(exercise_id=uuid7())
        third = session.add_exercise(exercise_id=uuid7())

        session.reorder_exercises([third.id, first.id, second.id])

        assert [e.id for e in session.exercises] == [third.id, first.id, second.id]
        assert [e.position for e in session.exercises] == [1, 2, 3]

    def test_partial_reorder_is_refused(self) -> None:
        """Dropping an id would silently delete an exercise from the session."""
        session = new_session()
        first = session.add_exercise(exercise_id=uuid7())
        session.add_exercise(exercise_id=uuid7())
        with pytest.raises(ValueError, match="exactly once"):
            session.reorder_exercises([first.id])


class TestSessionSet:
    def test_a_set_must_record_something(self) -> None:
        with pytest.raises(ValueError, match="reps, duration or distance"):
            SessionSet.create(session_exercise_id=uuid7(), set_number=1, weight_kg=Decimal("100"))

    def test_client_supplied_id_is_honoured(self) -> None:
        """Offline logging names the set locally so a double flush is one row."""
        client_id = uuid7()
        entry = SessionSet.create(
            session_exercise_id=uuid7(), set_number=1, reps=5, set_id=client_id
        )
        assert entry.id == client_id

    def test_set_numbering_continues_from_the_highest(self) -> None:
        session = new_session()
        entry = session.add_exercise(exercise_id=EXERCISE)
        assert entry.next_set_number() == 1
        entry.sets.append(SessionSet.create(session_exercise_id=entry.id, set_number=3, reps=5))
        assert entry.next_set_number() == 4


class TestRoutine:
    def test_routine_needs_a_name(self) -> None:
        with pytest.raises(ValueError, match="needs a name"):
            Routine.create(user_id=USER, name="   ")

    def test_replacing_exercises_renumbers_and_bumps_the_version(self) -> None:
        routine = Routine.create(user_id=USER, name="Upper")
        assert routine.version == 1
        routine.replace_exercises(
            [
                RoutineExercise.create(exercise_id=uuid7(), position=9),
                RoutineExercise.create(exercise_id=uuid7(), position=4),
            ]
        )
        assert [e.position for e in routine.exercises] == [1, 2]
        assert routine.version == 2

    def test_duplicate_copies_structure_with_fresh_ids(self) -> None:
        routine = Routine.create(user_id=USER, name="Push")
        routine.exercises = [
            RoutineExercise.create(
                exercise_id=EXERCISE,
                position=1,
                sets=[RoutineSet.create(set_number=1, target_reps_min=8, target_reps_max=12)],
            )
        ]

        copy = routine.duplicate(user_id=USER)

        assert copy.name == "Push (copy)"
        assert copy.id != routine.id
        assert copy.exercises[0].id != routine.exercises[0].id
        assert copy.exercises[0].exercise_id == EXERCISE
        assert copy.exercises[0].sets[0].target_reps_max == 12

    def test_duplicate_remaps_superset_groups_consistently(self) -> None:
        """The copy's groupings must be internally consistent, not aliases of the original."""
        group = uuid7()
        routine = Routine.create(user_id=USER, name="Arms")
        routine.exercises = [
            RoutineExercise.create(exercise_id=uuid7(), position=1, superset_group=group),
            RoutineExercise.create(exercise_id=uuid7(), position=2, superset_group=group),
        ]

        copy = routine.duplicate(user_id=USER)
        groups = {e.superset_group for e in copy.exercises}

        assert len(groups) == 1
        assert groups != {group}

    def test_rep_range_must_be_ordered(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed"):
            RoutineSet.create(set_number=1, target_reps_min=12, target_reps_max=8)


class TestStreakCalculator:
    def setup_method(self) -> None:
        self.calculator = StreakCalculator()

    def test_first_workout_starts_a_streak(self) -> None:
        current, longest, last = self.calculator.apply(
            workout_date=LOCAL_DATE, last_date=None, current=0, longest=0
        )
        assert (current, longest, last) == (1, 1, LOCAL_DATE)

    def test_consecutive_day_extends_the_streak(self) -> None:
        current, longest, _ = self.calculator.apply(
            workout_date=LOCAL_DATE, last_date=LOCAL_DATE - timedelta(days=1), current=4, longest=9
        )
        assert (current, longest) == (5, 9)

    def test_a_new_best_raises_the_longest(self) -> None:
        current, longest, _ = self.calculator.apply(
            workout_date=LOCAL_DATE, last_date=LOCAL_DATE - timedelta(days=1), current=9, longest=9
        )
        assert (current, longest) == (10, 10)

    def test_second_workout_same_day_does_not_double_count(self) -> None:
        current, longest, _ = self.calculator.apply(
            workout_date=LOCAL_DATE, last_date=LOCAL_DATE, current=3, longest=7
        )
        assert (current, longest) == (3, 7)

    def test_a_gap_resets_the_streak_but_keeps_the_record(self) -> None:
        current, longest, _ = self.calculator.apply(
            workout_date=LOCAL_DATE, last_date=LOCAL_DATE - timedelta(days=5), current=6, longest=11
        )
        assert (current, longest) == (1, 11)

    def test_backfilled_workout_does_not_corrupt_the_streak(self) -> None:
        """An out-of-order write from a late sync must not rewrite the current streak."""
        current, longest, last = self.calculator.apply(
            workout_date=LOCAL_DATE - timedelta(days=10),
            last_date=LOCAL_DATE,
            current=4,
            longest=8,
        )
        assert (current, longest, last) == (4, 8, LOCAL_DATE)

    def test_today_never_counts_as_a_broken_streak(self) -> None:
        assert not self.calculator.is_broken(LOCAL_DATE, LOCAL_DATE)
        assert not self.calculator.is_broken(LOCAL_DATE - timedelta(days=1), LOCAL_DATE)
        assert self.calculator.is_broken(LOCAL_DATE - timedelta(days=2), LOCAL_DATE)

    def test_no_history_is_not_a_broken_streak(self) -> None:
        assert not self.calculator.is_broken(None, LOCAL_DATE)
