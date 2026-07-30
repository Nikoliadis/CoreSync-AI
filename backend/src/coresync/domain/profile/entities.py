"""Profile domain entities: who the user is, and what they are aiming at."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from coresync.core.ids import uuid7


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class ActivityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


class ExperienceLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class GoalType(StrEnum):
    LOSE_FAT = "lose_fat"
    MAINTAIN = "maintain"
    GAIN_MUSCLE = "gain_muscle"
    RECOMP = "recomp"
    PERFORMANCE = "performance"


class TargetSource(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    AI = "ai"


@dataclass(slots=True)
class Profile:
    user_id: UUID
    display_name: str
    date_of_birth: date | None = None
    gender: Gender | None = None
    height_cm: Decimal | None = None
    activity_level: ActivityLevel = ActivityLevel.MODERATE
    experience_level: ExperienceLevel = ExperienceLevel.BEGINNER
    avatar_url: str | None = None
    bio: str | None = None
    onboarded_at: datetime | None = None

    @classmethod
    def create(cls, *, user_id: UUID, display_name: str) -> Profile:
        return cls(user_id=user_id, display_name=display_name.strip())

    def age_at(self, on: date) -> int | None:
        if self.date_of_birth is None:
            return None
        dob = self.date_of_birth
        return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))

    @property
    def is_onboarded(self) -> bool:
        return self.onboarded_at is not None

    def complete_onboarding(self, now: datetime) -> None:
        if self.onboarded_at is None:
            self.onboarded_at = now

    def has_metrics_for_calculation(self) -> bool:
        """Whether TDEE can be computed. Weight comes from the progress domain."""
        return (
            self.height_cm is not None
            and self.date_of_birth is not None
            and self.gender is not None
        )


@dataclass(slots=True)
class Goal:
    id: UUID
    user_id: UUID
    goal_type: GoalType
    target_weight_kg: Decimal | None
    weekly_rate_kg: Decimal | None
    target_date: date | None
    started_on: date
    ended_on: date | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        goal_type: GoalType,
        target_weight_kg: Decimal | None,
        weekly_rate_kg: Decimal | None,
        target_date: date | None,
        on: date,
    ) -> Goal:
        return cls(
            id=uuid7(),
            user_id=user_id,
            goal_type=goal_type,
            target_weight_kg=target_weight_kg,
            weekly_rate_kg=weekly_rate_kg,
            target_date=target_date,
            started_on=on,
        )

    @property
    def is_current(self) -> bool:
        return self.ended_on is None

    def close(self, on: date) -> None:
        self.ended_on = on


@dataclass(slots=True)
class NutritionTarget:
    """Daily nutrition targets, versioned over time rather than mutated.

    Overwriting these would destroy the ability to answer "was I actually in a deficit
    in March?" — which is the single most valuable question the AI coach asks. Each
    change closes the previous row and opens a new one.
    """

    id: UUID
    user_id: UUID
    effective_from: date
    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    water_ml: Decimal
    effective_to: date | None = None
    fiber_g: Decimal | None = None
    source: TargetSource = TargetSource.AUTO
    rationale: str | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        effective_from: date,
        calories: Decimal,
        protein_g: Decimal,
        carbs_g: Decimal,
        fat_g: Decimal,
        water_ml: Decimal = Decimal("2500"),
        fiber_g: Decimal | None = None,
        source: TargetSource = TargetSource.AUTO,
        rationale: str | None = None,
    ) -> NutritionTarget:
        return cls(
            id=uuid7(),
            user_id=user_id,
            effective_from=effective_from,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            water_ml=water_ml,
            fiber_g=fiber_g,
            source=source,
            rationale=rationale,
        )

    @property
    def is_current(self) -> bool:
        return self.effective_to is None

    def close(self, on: date) -> None:
        self.effective_to = on

    @property
    def energy_from_macros(self) -> Decimal:
        """Atwater factors. Used to check that a target is internally consistent."""
        return self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9
