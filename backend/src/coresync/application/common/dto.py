"""Data transfer objects for the application layer.

Plain dataclasses, not Pydantic models: these cross the application boundary, and the
HTTP schemas in ``presentation`` are a separate concern that can change independently
(field naming, camelCase aliasing, versioning) without touching use cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in_seconds: int
    token_type: str = "Bearer"  # noqa: S105 — a scheme name, not a credential


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The identity view cached on the auth hot path."""

    id: UUID
    email: str
    role: str
    tier: str
    status: str
    email_verified: bool
    timezone: str


@dataclass(frozen=True, slots=True)
class SignInResult:
    tokens: TokenPair
    user: AuthenticatedUser
    is_new_user: bool = False
    requires_onboarding: bool = False


@dataclass(frozen=True, slots=True)
class ProfileDTO:
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


@dataclass(frozen=True, slots=True)
class NutritionTargetDTO:
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


@dataclass(frozen=True, slots=True)
class GoalDTO:
    id: UUID
    goal_type: str
    target_weight_kg: Decimal | None
    weekly_rate_kg: Decimal | None
    target_date: date | None
    started_on: date
    ended_on: date | None


@dataclass(frozen=True, slots=True)
class TargetCalculationDTO:
    """Includes the working, so the numbers are explicable rather than magic."""

    target: NutritionTargetDTO
    bmr: Decimal
    tdee: Decimal
    was_clamped_to_floor: bool


@dataclass(frozen=True, slots=True)
class MeDTO:
    user: AuthenticatedUser
    profile: ProfileDTO | None
    goal: GoalDTO | None
    targets: NutritionTargetDTO | None
    settings: dict[str, object]
    entitlements: list[str]


@dataclass(frozen=True, slots=True)
class SessionDTO:
    id: UUID
    device_name: str | None
    platform: str | None
    ip: str | None
    user_agent: str | None
    created_at: datetime | None
    expires_at: datetime
    is_current: bool
