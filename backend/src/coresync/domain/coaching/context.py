"""The context bundle and the detectors that flag what matters in it.

The coach's quality is decided here, not in the prompt wording (docs/10 §3).

Two rules shape this module. First, the bundle is **small** — under ~3,000 tokens of
pre-computed aggregates, with no raw set lists, diary lines or free text. Those are
available on demand through tools; stuffing them into every prompt costs an order of
magnitude more tokens and measurably *reduces* answer quality by burying the signal.

Second, ``flags`` are produced by **deterministic detectors, not by the model**. Asking a
model to "spot problems" in a wall of JSON finds them inconsistently. A function finds the
same thing every time, and can be unit-tested against known histories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

_ZERO = Decimal("0")


class ContextFlag(StrEnum):
    """What the detectors noticed. The coach is told to address these explicitly."""

    SQUAT_PLATEAU = "exercise_plateau"
    VOLUME_IMBALANCE = "volume_imbalance"
    TRAINING_DROPOFF = "training_dropoff"
    OVERREACHING = "overreaching"
    STREAK_AT_RISK = "streak_at_risk"
    RAPID_WEIGHT_CHANGE = "rapid_weight_change"
    WEIGHT_STALLED = "weight_stalled"
    NO_RECENT_DATA = "no_recent_data"
    NUTRITION_NOT_TRACKED = "nutrition_not_tracked"


@dataclass(frozen=True, slots=True)
class ProfileContext:
    display_name: str
    age: int | None
    gender: str | None
    height_cm: Decimal | None
    experience: str
    activity_level: str
    goal: str | None
    target_rate_kg_per_week: Decimal | None


@dataclass(frozen=True, slots=True)
class CurrentContext:
    weight_kg: Decimal | None
    trend_weight_kg: Decimal | None
    trend_kg_per_week: Decimal | None
    target_calories: Decimal | None
    target_protein_g: Decimal | None


@dataclass(frozen=True, slots=True)
class TrainingWindow:
    sessions: int
    total_volume_kg: Decimal
    total_sets: int
    avg_duration_min: int
    volume_by_muscle_group: dict[str, Decimal] = field(default_factory=dict)
    set_counts_by_muscle_group: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecentPR:
    exercise: str
    record_type: str
    value: Decimal
    days_ago: int


@dataclass(frozen=True, slots=True)
class StalledExercise:
    exercise: str
    weeks_without_progress: int
    last_best_est_1rm: Decimal | None


@dataclass(frozen=True, slots=True)
class CoachContext:
    """Everything the coach is told before it asks a single tool.

    ``nutrition`` is deliberately absent rather than zeroed while the nutrition domain
    does not exist. Telling a coach the user ate 0 kcal would produce confident, wrong
    advice; telling it nutrition is untracked produces the right question.
    """

    today: date
    profile: ProfileContext
    current: CurrentContext
    training_7d: TrainingWindow
    training_30d: TrainingWindow
    recent_prs: list[RecentPR] = field(default_factory=list)
    stalled_exercises: list[StalledExercise] = field(default_factory=list)
    flags: list[ContextFlag] = field(default_factory=list)
    days_since_last_workout: int | None = None
    workout_streak: int = 0

    def to_prompt_dict(self) -> dict[str, Any]:
        """Compact JSON for the prompt. Decimals become strings to stay exact."""

        def money(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        return {
            "today": self.today.isoformat(),
            "profile": {
                "name": self.profile.display_name,
                "age": self.profile.age,
                "gender": self.profile.gender,
                "heightCm": money(self.profile.height_cm),
                "experience": self.profile.experience,
                "activityLevel": self.profile.activity_level,
                "goal": self.profile.goal,
                "targetRateKgPerWeek": money(self.profile.target_rate_kg_per_week),
            },
            "current": {
                "weightKg": money(self.current.weight_kg),
                "trendWeightKg": money(self.current.trend_weight_kg),
                "trendKgPerWeek": money(self.current.trend_kg_per_week),
                "targets": {
                    "calories": money(self.current.target_calories),
                    "proteinG": money(self.current.target_protein_g),
                },
            },
            "training7d": _window_dict(self.training_7d),
            "training30d": _window_dict(self.training_30d),
            "recentPRs": [
                {
                    "exercise": pr.exercise,
                    "type": pr.record_type,
                    "value": str(pr.value),
                    "daysAgo": pr.days_ago,
                }
                for pr in self.recent_prs
            ],
            "stalledExercises": [
                {
                    "exercise": s.exercise,
                    "weeksWithoutProgress": s.weeks_without_progress,
                    "lastBestEst1rm": money(s.last_best_est_1rm),
                }
                for s in self.stalled_exercises
            ],
            "daysSinceLastWorkout": self.days_since_last_workout,
            "workoutStreak": self.workout_streak,
            # Nutrition is genuinely unavailable, not zero. Stated explicitly so the coach
            # asks rather than assumes.
            "nutrition": None,
            "flags": [f.value for f in self.flags],
        }


def _window_dict(window: TrainingWindow) -> dict[str, Any]:
    return {
        "sessions": window.sessions,
        "totalVolumeKg": str(window.total_volume_kg),
        "totalSets": window.total_sets,
        "avgDurationMin": window.avg_duration_min,
        "volumeByMuscleGroup": {k: str(v) for k, v in window.volume_by_muscle_group.items()},
        "setsByMuscleGroup": window.set_counts_by_muscle_group,
    }


class FlagDetector:
    """Deterministic detectors over the assembled numbers.

    Every threshold here is a documented, reviewable decision. They are set conservatively
    on purpose: a false plateau alert erodes trust faster than silence does, and the
    insight-precision gate is 85% for exactly that reason (docs/10 §8).
    """

    # Five weeks is roughly when a genuine stall becomes distinguishable from ordinary
    # week-to-week noise on a compound lift.
    PLATEAU_WEEKS = 5
    # Below this share of total weekly sets, a muscle group is being neglected rather
    # than merely prioritised lower.
    IMBALANCE_MIN_SHARE = Decimal("0.08")
    IMBALANCE_MIN_WEEKLY_SETS = 10
    # A week more than 60% above the 30-day average is a spike, not progression.
    OVERREACH_RATIO = Decimal("1.6")
    # Two-thirds down on the same comparison is a drop-off worth naming.
    DROPOFF_RATIO = Decimal("0.34")
    STREAK_RISK_DAYS = 2
    STALE_DATA_DAYS = 14
    # 1% of bodyweight per week is the documented safe ceiling for loss.
    RAPID_CHANGE_KG_PER_WEEK = Decimal("1.0")
    STALLED_WEIGHT_KG_PER_WEEK = Decimal("0.05")

    def detect(self, context: CoachContext) -> list[ContextFlag]:
        flags: list[ContextFlag] = []

        if context.days_since_last_workout is None or (
            context.days_since_last_workout > self.STALE_DATA_DAYS
        ):
            flags.append(ContextFlag.NO_RECENT_DATA)
        elif (
            context.days_since_last_workout >= self.STREAK_RISK_DAYS and context.workout_streak > 0
        ):
            flags.append(ContextFlag.STREAK_AT_RISK)

        if context.stalled_exercises:
            flags.append(ContextFlag.SQUAT_PLATEAU)

        if self._is_imbalanced(context.training_7d):
            flags.append(ContextFlag.VOLUME_IMBALANCE)

        load = self._load_ratio(context.training_7d, context.training_30d)
        if load is not None:
            if load >= self.OVERREACH_RATIO:
                flags.append(ContextFlag.OVERREACHING)
            elif load <= self.DROPOFF_RATIO:
                flags.append(ContextFlag.TRAINING_DROPOFF)

        rate = context.current.trend_kg_per_week
        if rate is not None:
            if abs(rate) > self.RAPID_CHANGE_KG_PER_WEEK:
                flags.append(ContextFlag.RAPID_WEIGHT_CHANGE)
            elif (
                context.profile.goal in ("lose_fat", "gain_muscle")
                and abs(rate) < self.STALLED_WEIGHT_KG_PER_WEEK
            ):
                flags.append(ContextFlag.WEIGHT_STALLED)

        # Always set while the nutrition domain does not exist, so the coach never
        # reasons about intake it cannot see.
        flags.append(ContextFlag.NUTRITION_NOT_TRACKED)
        return flags

    # Tonnage shares are far more skewed than set-count shares — a deadlift day dwarfs a
    # shoulder day in kilos while being comparable in sets — so the fallback threshold is
    # tightened to avoid crying imbalance over ordinary programme structure.
    IMBALANCE_MIN_VOLUME_SHARE = Decimal("0.03")

    def _is_imbalanced(self, window: TrainingWindow) -> bool:
        """A muscle group starved relative to the rest of the week's work.

        Set counts are the right unit: 20 sets of calf raises moves less weight than 5
        sets of deadlifts, and set count is what programmes are written in. The daily
        aggregates currently carry tonnage per muscle group but not sets, so volume share
        is used as a documented proxy until they do — a weaker signal, and deliberately
        held to a stricter threshold because of it.
        """
        counts = window.set_counts_by_muscle_group
        total_sets = sum(counts.values())
        if total_sets >= self.IMBALANCE_MIN_WEEKLY_SETS and len(counts) >= 3:
            smallest = min(counts.values())
            return Decimal(smallest) / Decimal(total_sets) < self.IMBALANCE_MIN_SHARE

        volumes = window.volume_by_muscle_group
        if window.total_sets < self.IMBALANCE_MIN_WEEKLY_SETS or len(volumes) < 3:
            return False
        total_volume = sum(volumes.values(), _ZERO)
        if total_volume <= _ZERO:
            return False
        return min(volumes.values()) / total_volume < self.IMBALANCE_MIN_VOLUME_SHARE

    def _load_ratio(self, week: TrainingWindow, month: TrainingWindow) -> Decimal | None:
        """This week's volume against the 30-day weekly average.

        Returns None when there is not enough history for the comparison to mean anything
        — the first fortnight of training would otherwise look like a permanent spike.
        """
        if month.sessions < 4 or month.total_volume_kg <= _ZERO:
            return None
        weekly_average = month.total_volume_kg / 4
        if weekly_average <= _ZERO:
            return None
        return week.total_volume_kg / weekly_average


def days_between(earlier: date | None, later: date) -> int | None:
    return None if earlier is None else (later - earlier).days


def weeks_between(earlier: date, later: date) -> int:
    return max(0, (later - earlier).days // 7)


def window_start(today: date, days: int) -> date:
    return today - timedelta(days=days - 1)
