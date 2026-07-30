"""Exercise catalog entities.

The catalog is mostly reference data — muscles, equipment, categories — plus the
``Exercise`` itself, which is the one entity users can extend. A custom exercise is the
same entity with ``owner_user_id`` set (docs/03 §5): one table means workout logging
joins one table instead of a UNION, and custom exercises inherit every catalog feature.

Nothing here imports the workout domain. An exercise does not know it has been
performed; that direction of dependency would make the catalog un-cacheable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from coresync.core.ids import uuid7


class ForceType(StrEnum):
    PUSH = "push"
    PULL = "pull"
    STATIC = "static"


class Mechanic(StrEnum):
    COMPOUND = "compound"
    ISOLATION = "isolation"


class Difficulty(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class LoggingType(StrEnum):
    """Which fields a set carries, and therefore which records are computable.

    Getting this wrong forces NULL-riddled set rows and broken PR maths later — a plank
    has no weight, a run has no reps, and a weighted pull-up has both bodyweight and
    added load (docs/03 §5).
    """

    WEIGHT_REPS = "weight_reps"
    BODYWEIGHT_REPS = "bodyweight_reps"
    WEIGHTED_BODYWEIGHT = "weighted_bodyweight"
    TIME = "time"
    DISTANCE_TIME = "distance_time"
    REPS_ONLY = "reps_only"

    @property
    def uses_weight(self) -> bool:
        return self in (
            LoggingType.WEIGHT_REPS,
            LoggingType.WEIGHTED_BODYWEIGHT,
        )

    @property
    def uses_reps(self) -> bool:
        return self in (
            LoggingType.WEIGHT_REPS,
            LoggingType.BODYWEIGHT_REPS,
            LoggingType.WEIGHTED_BODYWEIGHT,
            LoggingType.REPS_ONLY,
        )

    @property
    def uses_duration(self) -> bool:
        return self in (LoggingType.TIME, LoggingType.DISTANCE_TIME)

    @property
    def uses_distance(self) -> bool:
        return self is LoggingType.DISTANCE_TIME


class MuscleRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    STABILIZER = "stabilizer"


@dataclass(frozen=True, slots=True)
class MuscleGroup:
    """Users think in groups ("back"); training science needs muscles ("lats")."""

    id: UUID
    slug: str
    name: str
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class Muscle:
    id: UUID
    slug: str
    name: str
    muscle_group_id: UUID
    muscle_group_slug: str | None = None


@dataclass(frozen=True, slots=True)
class Equipment:
    id: UUID
    slug: str
    name: str
    is_home_available: bool = False


@dataclass(frozen=True, slots=True)
class ExerciseCategory:
    id: UUID
    slug: str
    name: str
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class ExerciseMuscle:
    muscle_id: UUID
    role: MuscleRole
    contribution_pct: int | None = None
    muscle_slug: str | None = None
    muscle_name: str | None = None
    muscle_group_slug: str | None = None


@dataclass(frozen=True, slots=True)
class ExerciseMedia:
    id: UUID
    media_type: str
    url: str
    sort_order: int = 0


@dataclass(slots=True)
class Exercise:
    """A movement, global or user-authored.

    ``owner_user_id is None`` means the global verified catalog. A user's own exercise
    carries their id, and the two partial unique indexes on ``slug`` keep names unique
    in the right scope.
    """

    id: UUID
    slug: str
    name: str
    category_id: UUID
    logging_type: LoggingType = LoggingType.WEIGHT_REPS
    difficulty: Difficulty = Difficulty.INTERMEDIATE
    owner_user_id: UUID | None = None
    force_type: ForceType | None = None
    mechanic: Mechanic | None = None
    is_unilateral: bool = False
    is_verified: bool = False
    description: str | None = None
    instructions: list[str] = field(default_factory=list)
    muscles: list[ExerciseMuscle] = field(default_factory=list)
    equipment_ids: list[UUID] = field(default_factory=list)
    media: list[ExerciseMedia] = field(default_factory=list)
    # Populated on read for display; not authoritative state.
    category_slug: str | None = None
    equipment_slugs: list[str] = field(default_factory=list)
    is_favorite: bool = False

    @classmethod
    def create_custom(
        cls,
        *,
        owner_user_id: UUID,
        name: str,
        category_id: UUID,
        logging_type: LoggingType = LoggingType.WEIGHT_REPS,
        difficulty: Difficulty = Difficulty.INTERMEDIATE,
        force_type: ForceType | None = None,
        mechanic: Mechanic | None = None,
        is_unilateral: bool = False,
        description: str | None = None,
        muscles: list[ExerciseMuscle] | None = None,
        equipment_ids: list[UUID] | None = None,
    ) -> Exercise:
        exercise_id = uuid7()
        return cls(
            id=exercise_id,
            # Suffixed with the id so a user creating "Bench Press" twice, or creating one
            # that collides with the global catalog, does not hit a unique violation.
            slug=f"{slugify(name)}-{exercise_id.hex[-6:]}",
            name=name.strip(),
            category_id=category_id,
            logging_type=logging_type,
            difficulty=difficulty,
            owner_user_id=owner_user_id,
            force_type=force_type,
            mechanic=mechanic,
            is_unilateral=is_unilateral,
            is_verified=False,
            description=description,
            muscles=muscles or [],
            equipment_ids=equipment_ids or [],
        )

    @property
    def is_custom(self) -> bool:
        return self.owner_user_id is not None

    def is_editable_by(self, user_id: UUID) -> bool:
        """Only the author may edit, and only their own exercises.

        The global catalog is immutable from the API — moderators change it through the
        admin surface, which is a different code path with an audit trail.
        """
        return self.owner_user_id is not None and self.owner_user_id == user_id

    @property
    def primary_muscle_ids(self) -> list[UUID]:
        return [m.muscle_id for m in self.muscles if m.role is MuscleRole.PRIMARY]


def slugify(value: str) -> str:
    """ASCII slug for catalog entries.

    Deliberately simple: catalog names are English movement names, and a dependency to
    handle Unicode folding would buy nothing here.
    """
    out: list[str] = []
    previous_dash = False
    for char in value.strip().lower():
        if char.isalnum() and char.isascii():
            out.append(char)
            previous_dash = False
        elif not previous_dash and out:
            out.append("-")
            previous_dash = True
    return "".join(out).strip("-") or "exercise"
