"""Request and response schemas for /v1/users."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from coresync.presentation.schemas.auth import AuthenticatedUserResponse
from coresync.presentation.schemas.common import ApiModel

Gender = Literal["male", "female", "other", "prefer_not_to_say"]
ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
ExperienceLevel = Literal["beginner", "intermediate", "advanced"]
GoalType = Literal["lose_fat", "maintain", "gain_muscle", "recomp", "performance"]
UnitSystem = Literal["metric", "imperial"]


# ------------------------------------------------------------------- responses
class ProfileResponse(ApiModel):
    user_id: UUID
    display_name: str
    date_of_birth: date | None
    gender: str | None
    height_cm: Decimal | None
    activity_level: str
    experience_level: str
    avatar_url: str | None
    bio: str | None
    age: int | None
    is_onboarded: bool


class NutritionTargetResponse(ApiModel):
    id: UUID
    effective_from: date
    effective_to: date | None
    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    fiber_g: Decimal | None
    water_ml: Decimal
    source: str
    rationale: str | None


class GoalResponse(ApiModel):
    id: UUID
    goal_type: str
    target_weight_kg: Decimal | None
    weekly_rate_kg: Decimal | None
    target_date: date | None
    started_on: date
    ended_on: date | None


class TargetCalculationResponse(ApiModel):
    target: NutritionTargetResponse
    bmr: Decimal = Field(description="Basal metabolic rate, Mifflin-St Jeor (kcal/day)")
    tdee: Decimal = Field(description="Total daily energy expenditure (kcal/day)")
    was_clamped_to_floor: bool = Field(
        description=(
            "True when the calculated deficit fell below the safety floor and the "
            "target was raised to meet it."
        )
    )


class SettingsResponse(ApiModel):
    unit_system: str = "metric"
    theme: str = "system"
    language: str = "en"
    profile_visibility: str = "private"
    ai_training_opt_in: bool = False
    marketing_email_opt_in: bool = False


class MeResponse(ApiModel):
    user: AuthenticatedUserResponse
    profile: ProfileResponse | None
    goal: GoalResponse | None
    targets: NutritionTargetResponse | None
    settings: SettingsResponse
    entitlements: list[str]


class AccountDeletionResponse(ApiModel):
    scheduled_for: date
    message: str


# -------------------------------------------------------------------- requests
class UpdateProfileRequest(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    date_of_birth: date | None = None
    gender: Gender | None = None
    height_cm: Decimal | None = Field(default=None, gt=0, le=300)
    activity_level: ActivityLevel | None = None
    experience_level: ExperienceLevel | None = None
    bio: str | None = Field(default=None, max_length=500)


class UpdateSettingsRequest(ApiModel):
    unit_system: UnitSystem | None = None
    theme: Literal["system", "light", "dark"] | None = None
    language: str | None = Field(default=None, max_length=10)
    profile_visibility: Literal["private", "followers", "public"] | None = None
    ai_training_opt_in: bool | None = None
    marketing_email_opt_in: bool | None = None


class OnboardingRequest(ApiModel):
    date_of_birth: date
    gender: Gender
    height_cm: Decimal = Field(gt=50, le=300)
    weight_kg: Decimal = Field(gt=20, le=500)
    activity_level: ActivityLevel
    experience_level: ExperienceLevel
    goal_type: GoalType
    target_weight_kg: Decimal | None = Field(default=None, gt=20, le=500)
    weekly_rate_kg: Decimal | None = Field(
        default=None,
        description=(
            "Desired weekly rate of change in kg. Clamped server-side to at most 1% of "
            "bodyweight per week for loss and 0.5% for gain."
        ),
    )
    unit_system: UnitSystem = "metric"


class SetGoalRequest(ApiModel):
    goal_type: GoalType
    target_weight_kg: Decimal | None = Field(default=None, gt=20, le=500)
    weekly_rate_kg: Decimal | None = None
    target_date: date | None = None


class SetTargetsRequest(ApiModel):
    calories: Decimal = Field(ge=1200, le=6000)
    protein_g: Decimal = Field(ge=0, le=500)
    carbs_g: Decimal = Field(ge=0, le=1000)
    fat_g: Decimal = Field(ge=0, le=400)
    fiber_g: Decimal | None = Field(default=None, ge=0, le=200)
    water_ml: Decimal | None = Field(default=None, ge=500, le=10000)


# --------------------------------------------------------------------- devices
class RegisterDeviceRequest(ApiModel):
    """A push token, and enough context to tell one device from another in a list."""

    platform: Literal["ios", "android", "web"]
    push_token: str = Field(
        min_length=1,
        max_length=512,
        description="The provider's token for this installation. Not a secret, but not shared.",
    )
    device_name: str | None = Field(default=None, max_length=120)


class UnregisterTokenRequest(ApiModel):
    push_token: str = Field(min_length=1, max_length=512)


class DeviceResponse(ApiModel):
    id: UUID
    platform: str
    device_name: str | None
    is_active: bool
    # The token itself is never returned. Listing devices is for recognising them, and
    # echoing a delivery address back over the wire earns nothing.
    has_push_token: bool
