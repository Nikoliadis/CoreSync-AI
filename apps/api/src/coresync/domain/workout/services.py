"""Workout domain services.

Pure functions over domain objects: no database, no clock, no I/O. Every rule here —
what counts as a record, what counts as volume, when a streak breaks — is a business
decision that deserves a fast unit test rather than an integration one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from coresync.domain.workout.entities import (
    PersonalRecord,
    RecordType,
    SessionSet,
    estimated_one_rep_max,
)

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class DetectedRecord:
    """A beaten record, with what it beat — the client renders "+5 kg" from this."""

    exercise_id: UUID
    record_type: RecordType
    value: Decimal
    session_set_id: UUID
    reps_at_value: int | None
    previous_value: Decimal | None
    previous_record_id: UUID | None

    @property
    def improvement(self) -> Decimal | None:
        if self.previous_value is None:
            return None
        return self.value - self.previous_value

    @property
    def is_first_ever(self) -> bool:
        return self.previous_value is None


class PersonalRecordDetector:
    """Decides which sets in a session beat the user's existing records.

    Takes the sets and the current records, returns what changed. Ties do not count: a
    record must be *beaten*, not matched, or a lifter repeating the same working weight
    would get a celebration every session and the notion would stop meaning anything.
    """

    def detect(
        self,
        sets: Sequence[SessionSet],
        current: Mapping[tuple[UUID, RecordType], PersonalRecord],
    ) -> list[DetectedRecord]:
        working = [s for s in sets if s.counts_toward_records and s.exercise_id is not None]
        if not working:
            return []

        by_exercise: dict[UUID, list[SessionSet]] = {}
        for entry in working:
            assert entry.exercise_id is not None  # narrowed by the filter above
            by_exercise.setdefault(entry.exercise_id, []).append(entry)

        detected: list[DetectedRecord] = []
        for exercise_id, exercise_sets in by_exercise.items():
            for record_type in RecordType:
                best = self._best(record_type, exercise_sets)
                if best is None:
                    continue
                value, source = best
                existing = current.get((exercise_id, record_type))
                if existing is not None and value <= existing.value:
                    continue
                detected.append(
                    DetectedRecord(
                        exercise_id=exercise_id,
                        record_type=record_type,
                        value=value,
                        session_set_id=source.id,
                        reps_at_value=source.reps,
                        previous_value=existing.value if existing else None,
                        previous_record_id=existing.id if existing else None,
                    )
                )
        return detected

    def _best(
        self, record_type: RecordType, sets: Sequence[SessionSet]
    ) -> tuple[Decimal, SessionSet] | None:
        """The best set for one record type, or None if the type does not apply.

        Returning the set alongside the value is what lets the UI say "3 x 8 @ 100 kg on
        12 March" instead of just showing a number.
        """
        best: tuple[Decimal, SessionSet] | None = None
        for entry in sets:
            value = self._value_of(record_type, entry)
            if value is None or value <= _ZERO:
                continue
            if best is None or value > best[0]:
                best = (value, entry)
        return best

    @staticmethod
    def _value_of(record_type: RecordType, entry: SessionSet) -> Decimal | None:
        match record_type:
            case RecordType.MAX_WEIGHT:
                # Weight alone is only a record if it was actually lifted for a rep.
                if entry.weight_kg is None or not entry.reps:
                    return None
                return entry.weight_kg
            case RecordType.MAX_REPS:
                # Tracked per exercise, so a rep record on pull-ups is compared against
                # pull-ups only. Load is captured separately by MAX_WEIGHT and EST_1RM;
                # this is the record that matters for bodyweight movements.
                if entry.reps is None:
                    return None
                return Decimal(entry.reps)
            case RecordType.MAX_VOLUME_SET:
                return entry.volume_kg or None
            case RecordType.EST_1RM:
                return estimated_one_rep_max(entry.weight_kg, entry.reps)
            case RecordType.MAX_DURATION:
                if entry.duration_seconds is None:
                    return None
                return Decimal(entry.duration_seconds)
            case RecordType.MAX_DISTANCE:
                return entry.distance_m
        return None


class VolumeCalculator:
    """Tonnage, and how it splits across muscle groups.

    Volume is weight x reps over completed working sets. Warm-ups are excluded — the
    same rule as records, for the same reason.
    """

    def total(self, sets: Iterable[SessionSet]) -> Decimal:
        return sum((s.volume_kg for s in sets if s.counts_toward_records), _ZERO)

    def by_muscle_group(
        self,
        sets: Iterable[SessionSet],
        contributions: Mapping[UUID, Mapping[str, Decimal]],
    ) -> dict[str, Decimal]:
        """Split each set's volume across the muscle groups the exercise trains.

        ``contributions`` maps exercise id → {muscle_group_slug: share}, where the shares
        for one exercise sum to 1. Attributing a bench press wholly to "chest" would
        under-count triceps work by roughly a third, and the imbalance detection the AI
        coach does in Phase 5 is only as good as this split.
        """
        totals: dict[str, Decimal] = {}
        for entry in sets:
            if not entry.counts_toward_records or entry.exercise_id is None:
                continue
            volume = entry.volume_kg
            if volume <= _ZERO:
                continue
            for group, share in contributions.get(entry.exercise_id, {}).items():
                totals[group] = totals.get(group, _ZERO) + volume * share
        return {group: value.quantize(Decimal("0.01")) for group, value in totals.items()}

    def set_counts_by_muscle_group(
        self,
        sets: Iterable[SessionSet],
        primary_groups: Mapping[UUID, Sequence[str]],
    ) -> dict[str, int]:
        """Hard set counts per muscle group — the unit training programmes are written in.

        Counted against *primary* movers only. "34 sets of chest this week" means 34 sets
        that trained chest as the target, not 34 sets where chest assisted.
        """
        counts: dict[str, int] = {}
        for entry in sets:
            if not entry.counts_toward_records or entry.exercise_id is None:
                continue
            for group in primary_groups.get(entry.exercise_id, ()):
                counts[group] = counts.get(group, 0) + 1
        return counts


class StreakCalculator:
    """Consecutive-day training streaks.

    A workout streak counts *days with a workout*, and the rules are deliberately kind:
    two sessions in one day do not double it, and re-logging a day already counted does
    not break it. Rest days are part of training, so the streak that matters to a lifter
    is measured in days trained, not in an unbroken daily chain.
    """

    def apply(
        self,
        *,
        workout_date: date,
        last_date: date | None,
        current: int,
        longest: int,
    ) -> tuple[int, int, date]:
        """Returns the new (current, longest, last_date) after logging a workout."""
        if last_date is None:
            new_current = 1
        elif workout_date == last_date:
            new_current = max(current, 1)
        elif workout_date == last_date + timedelta(days=1):
            new_current = current + 1
        elif workout_date < last_date:
            # A backfilled workout from before the current streak: leave the streak alone
            # rather than corrupting it with an out-of-order write.
            return current, longest, last_date
        else:
            new_current = 1

        newest = max(workout_date, last_date) if last_date else workout_date
        return new_current, max(longest, new_current), newest

    @staticmethod
    def is_broken(last_date: date | None, today: date) -> bool:
        """Whether a streak has lapsed as of today.

        Today itself is never a break — the day is not over, and telling someone their
        streak is gone at 09:00 is both wrong and demoralising.
        """
        if last_date is None:
            return False
        return (today - last_date).days > 1
