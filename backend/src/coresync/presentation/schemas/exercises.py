"""HTTP schemas for the exercise catalog."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from coresync.presentation.schemas.common import ApiModel

LOGGING_TYPES = (
    "weight_reps",
    "bodyweight_reps",
    "weighted_bodyweight",
    "time",
    "distance_time",
    "reps_only",
)
DIFFICULTIES = ("beginner", "intermediate", "advanced")


class MuscleRefResponse(ApiModel):
    id: UUID
    slug: str
    name: str
    group_slug: str | None = None
    role: str | None = None
    contribution_pct: int | None = None


class MuscleGroupResponse(ApiModel):
    id: UUID
    slug: str
    name: str
    muscles: list[MuscleRefResponse] = Field(default_factory=list)


class EquipmentResponse(ApiModel):
    id: UUID
    slug: str
    name: str
    is_home_available: bool


class ExerciseCategoryResponse(ApiModel):
    id: UUID
    slug: str
    name: str


class MediaResponse(ApiModel):
    id: UUID
    media_type: str
    url: str


class ExerciseResponse(ApiModel):
    id: UUID
    slug: str
    name: str
    category_slug: str | None
    logging_type: str = Field(
        description="Determines which fields a set carries and which records apply."
    )
    difficulty: str
    force_type: str | None
    mechanic: str | None
    is_unilateral: bool
    is_verified: bool
    is_custom: bool
    is_favorite: bool
    description: str | None
    instructions: list[str] = Field(default_factory=list)
    muscles: list[MuscleRefResponse] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    media: list[MediaResponse] = Field(default_factory=list)


class ExercisePageResponse(ApiModel):
    items: list[ExerciseResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class CreateExerciseRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    category_slug: str = Field(max_length=50)
    logging_type: str = Field(default="weight_reps", pattern="|".join(LOGGING_TYPES))
    difficulty: str = Field(default="intermediate", pattern="|".join(DIFFICULTIES))
    force_type: str | None = Field(default=None, pattern="push|pull|static")
    mechanic: str | None = Field(default=None, pattern="compound|isolation")
    is_unilateral: bool = False
    description: str | None = Field(default=None, max_length=2000)
    primary_muscle_slugs: list[str] = Field(default_factory=list, max_length=6)
    secondary_muscle_slugs: list[str] = Field(default_factory=list, max_length=10)
    equipment_slugs: list[str] = Field(default_factory=list, max_length=6)


class UpdateExerciseRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    difficulty: str | None = Field(default=None, pattern="|".join(DIFFICULTIES))
    force_type: str | None = Field(default=None, pattern="push|pull|static")
    mechanic: str | None = Field(default=None, pattern="compound|isolation")
    is_unilateral: bool | None = None
    description: str | None = Field(default=None, max_length=2000)


class SetHistoryResponse(ApiModel):
    id: UUID
    set_number: int
    set_type: str
    reps: int | None
    weight_kg: Decimal | None
    duration_seconds: int | None
    distance_m: Decimal | None
    rpe: Decimal | None
    is_completed: bool
    estimated_one_rep_max: Decimal | None


class ExerciseHistorySessionResponse(ApiModel):
    session_id: UUID
    session_name: str
    local_date: date
    total_volume_kg: Decimal
    best_set_id: UUID | None
    sets: list[SetHistoryResponse]


class ExerciseHistoryResponse(ApiModel):
    exercise_id: UUID
    exercise_name: str
    total_sessions: int
    total_sets: int
    total_volume_kg: Decimal
    best_estimated_one_rep_max: Decimal | None
    last_performed_on: date | None
    sessions: list[ExerciseHistorySessionResponse]


class PersonalRecordResponse(ApiModel):
    id: UUID
    exercise_id: UUID
    exercise_name: str | None = None
    record_type: str
    value: Decimal
    reps_at_value: int | None
    achieved_on: date
    is_current: bool
    previous_value: Decimal | None = None
    improvement: Decimal | None = None
