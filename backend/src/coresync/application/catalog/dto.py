"""Catalog DTOs.

Plain dataclasses. The HTTP schemas in ``presentation`` are a separate concern that can
change independently — field naming, camelCase aliasing, versioning — without touching a
use case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MuscleRefDTO:
    id: UUID
    slug: str
    name: str
    group_slug: str | None
    role: str | None = None
    contribution_pct: int | None = None


@dataclass(frozen=True, slots=True)
class MuscleGroupDTO:
    id: UUID
    slug: str
    name: str
    muscles: list[MuscleRefDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EquipmentDTO:
    id: UUID
    slug: str
    name: str
    is_home_available: bool


@dataclass(frozen=True, slots=True)
class ExerciseCategoryDTO:
    id: UUID
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class MediaDTO:
    id: UUID
    media_type: str
    url: str


@dataclass(frozen=True, slots=True)
class ExerciseDTO:
    id: UUID
    slug: str
    name: str
    category_slug: str | None
    logging_type: str
    difficulty: str
    force_type: str | None
    mechanic: str | None
    is_unilateral: bool
    is_verified: bool
    is_custom: bool
    is_favorite: bool
    description: str | None
    instructions: list[str] = field(default_factory=list)
    muscles: list[MuscleRefDTO] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    media: list[MediaDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExercisePageDTO:
    items: list[ExerciseDTO]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


@dataclass(frozen=True, slots=True)
class SetHistoryDTO:
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


@dataclass(frozen=True, slots=True)
class ExerciseHistorySessionDTO:
    session_id: UUID
    session_name: str
    local_date: date
    total_volume_kg: Decimal
    best_set_id: UUID | None
    sets: list[SetHistoryDTO]


@dataclass(frozen=True, slots=True)
class ExerciseHistoryDTO:
    exercise_id: UUID
    exercise_name: str
    total_sessions: int
    total_sets: int
    total_volume_kg: Decimal
    best_estimated_one_rep_max: Decimal | None
    last_performed_on: date | None
    sessions: list[ExerciseHistorySessionDTO]


@dataclass(frozen=True, slots=True)
class PersonalRecordDTO:
    id: UUID
    exercise_id: UUID
    record_type: str
    value: Decimal
    reps_at_value: int | None
    achieved_on: date
    is_current: bool
    # Present on a freshly detected record so the client can celebrate with a number.
    previous_value: Decimal | None = None
    improvement: Decimal | None = None
    exercise_name: str | None = None
