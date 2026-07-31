"""Assembles the context bundle the coach reasons over.

Everything here reads pre-computed aggregates. That is the design (docs/10 §3.1): a
coaching turn must not scan a lifetime of sets, and the bundle must stay small enough
that the signal is not buried. Raw detail is reachable through tools, on demand, for the
handful of questions that actually need it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.domain.coaching.context import (
    CoachContext,
    CurrentContext,
    FlagDetector,
    ProfileContext,
    RecentPR,
    StalledExercise,
    TrainingWindow,
)
from coresync.domain.progress.services import WeightTrendCalculator
from coresync.domain.workout.entities import PersonalRecord, RecordType

_ZERO = Decimal("0")

# How much history each window covers. 7d is "what am I doing now", 30d is the baseline
# it is judged against.
_WEEK_DAYS = 7
_MONTH_DAYS = 30
# A weigh-in series long enough for the EWMA rate to mean something without dragging a
# decade of history into every coaching turn.
_WEIGHT_WINDOW_DAYS = 120
_RECENT_PR_DAYS = 30
_MAX_RECENT_PRS = 5
_MAX_STALLED = 3


@dataclass(frozen=True, slots=True)
class ContextAssembler:
    """Builds a :class:`CoachContext` for one user on one day."""

    uow: UnitOfWork
    # Both are stateless; the factory is only to satisfy the mutable-default rule.
    detector: FlagDetector = field(default_factory=FlagDetector)
    trend_calculator: WeightTrendCalculator = field(default_factory=WeightTrendCalculator)

    async def build(self, user_id: UUID, *, today: date) -> CoachContext:
        profile_ctx = await self._profile(user_id, today=today)
        current = await self._current(user_id, today=today)
        week = await self._window(user_id, today=today, days=_WEEK_DAYS)
        month = await self._window(user_id, today=today, days=_MONTH_DAYS)
        prs, stalled = await self._records(user_id, today=today)
        streak, days_since = await self._streak(user_id, today=today)

        context = CoachContext(
            today=today,
            profile=profile_ctx,
            current=current,
            training_7d=week,
            training_30d=month,
            recent_prs=prs,
            stalled_exercises=stalled,
            days_since_last_workout=days_since,
            workout_streak=streak,
        )
        # Flags are computed from the assembled numbers, never asked of the model.
        return replace(context, flags=self.detector.detect(context))

    # ---------------------------------------------------------------- sections
    async def _profile(self, user_id: UUID, *, today: date) -> ProfileContext:
        profile = await self.uow.profiles.get(user_id)
        goal = await self.uow.goals.get_current(user_id)
        return ProfileContext(
            display_name=profile.display_name if profile else "there",
            age=profile.age_at(today) if profile else None,
            gender=profile.gender.value if profile and profile.gender else None,
            height_cm=profile.height_cm if profile else None,
            experience=profile.experience_level.value if profile else "beginner",
            activity_level=profile.activity_level.value if profile else "moderate",
            goal=goal.goal_type.value if goal else None,
            target_rate_kg_per_week=goal.weekly_rate_kg if goal else None,
        )

    async def _current(self, user_id: UUID, *, today: date) -> CurrentContext:
        logs = await self.uow.weights.list_range(
            user_id, today - timedelta(days=_WEIGHT_WINDOW_DAYS), today
        )
        trend = self.trend_calculator.build(logs)
        target = await self.uow.targets.get_current(user_id)
        return CurrentContext(
            weight_kg=trend.latest_weight_kg,
            trend_weight_kg=trend.latest_trend_kg,
            trend_kg_per_week=trend.weekly_rate_kg,
            target_calories=target.calories if target else None,
            target_protein_g=target.protein_g if target else None,
        )

    async def _window(self, user_id: UUID, *, today: date, days: int) -> TrainingWindow:
        start = today - timedelta(days=days - 1)
        calendar = await self.uow.summaries.range(user_id, date_from=start, date_to=today)
        muscle_days = await self.uow.summaries.muscle_volume_range(
            user_id, date_from=start, date_to=today
        )

        sessions = sum(day.workout_count for day in calendar)
        volume = sum((day.total_volume_kg for day in calendar), _ZERO)
        sets = sum(day.total_sets for day in calendar)
        duration_seconds = sum(day.duration_seconds for day in calendar)

        by_muscle: dict[str, Decimal] = {}
        for day in muscle_days:
            for group, group_volume in day.volume_by_muscle_group.items():
                by_muscle[group] = by_muscle.get(group, _ZERO) + group_volume

        return TrainingWindow(
            sessions=sessions,
            total_volume_kg=volume,
            total_sets=sets,
            # Per session, not per day: "my sessions run 65 minutes" is the number a
            # lifter recognises.
            avg_duration_min=int(duration_seconds / sessions / 60) if sessions else 0,
            volume_by_muscle_group=by_muscle,
        )

    async def _records(
        self, user_id: UUID, *, today: date
    ) -> tuple[list[RecentPR], list[StalledExercise]]:
        records = await self.uow.records.list_current(user_id)
        if not records:
            return [], []

        exercise_ids = list({r.exercise_id for r in records})
        names = await self._exercise_names(exercise_ids, user_id)

        recent = sorted(
            (r for r in records if (today - r.achieved_on).days <= _RECENT_PR_DAYS),
            key=lambda r: r.achieved_on,
            reverse=True,
        )[:_MAX_RECENT_PRS]
        recent_prs = [
            RecentPR(
                exercise=names.get(r.exercise_id, "unknown"),
                record_type=r.record_type.value,
                value=r.value,
                days_ago=(today - r.achieved_on).days,
            )
            for r in recent
        ]
        return recent_prs, await self._stalled(user_id, records, names, today=today)

    async def _stalled(
        self,
        user_id: UUID,
        records: list[PersonalRecord],
        names: dict[UUID, str],
        *,
        today: date,
    ) -> list[StalledExercise]:
        """Exercises still being trained whose best is old.

        A plateau is *training without progressing*. An exercise nobody has touched in a
        month is not stalled, it is dropped — and telling someone their bench has
        plateaued when they stopped benching in May is exactly the kind of confidently
        wrong observation that makes a coach ignorable.
        """
        stats = await self.uow.exercise_stats.get_many(
            user_id, list({r.exercise_id for r in records})
        )
        # Estimated 1RM is the progress signal; heaviest weight is the fallback for
        # exercises never taken heavy enough for a 1RM estimate. Picking explicitly
        # rather than letting dict insertion order decide keeps the flag reproducible.
        best_by_exercise: dict[UUID, PersonalRecord] = {}
        for record in records:
            if record.record_type not in (RecordType.EST_1RM, RecordType.MAX_WEIGHT):
                continue
            existing = best_by_exercise.get(record.exercise_id)
            if existing is None or record.record_type is RecordType.EST_1RM:
                best_by_exercise[record.exercise_id] = record

        stalled: list[StalledExercise] = []
        for exercise_id, record in best_by_exercise.items():
            stat = stats.get(exercise_id)
            if stat is None or stat.last_performed_on is None:
                continue
            if (today - stat.last_performed_on).days > _MONTH_DAYS:
                continue
            weeks = (today - record.achieved_on).days // 7
            if weeks >= self.detector.PLATEAU_WEEKS:
                stalled.append(
                    StalledExercise(
                        exercise=names.get(exercise_id, "unknown"),
                        weeks_without_progress=weeks,
                        last_best_est_1rm=stat.best_est_1rm,
                    )
                )

        stalled.sort(key=lambda s: s.weeks_without_progress, reverse=True)
        return stalled[:_MAX_STALLED]

    async def _exercise_names(self, exercise_ids: list[UUID], user_id: UUID) -> dict[UUID, str]:
        exercises = await self.uow.exercises.get_many(exercise_ids, user_id)
        return {e.id: e.name for e in exercises}

    async def _streak(self, user_id: UUID, *, today: date) -> tuple[int, int | None]:
        streak = await self.uow.streaks.get(user_id)
        if streak is None or streak.workout_last_date is None:
            return 0, None
        return streak.workout_current, (today - streak.workout_last_date).days
