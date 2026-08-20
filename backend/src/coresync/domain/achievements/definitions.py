"""Achievement definitions and the rules that award them.

Two principles shape this, both from docs/09 §1:

**Never punitive.** Nothing here counts what someone missed. There is no "you broke a
streak" badge, and no achievement can be *lost* — once earned it stays earned, because
an achievement that can be taken away is a punishment wearing a trophy's clothes.

**Earned, not given.** Every threshold is something the user actually did, computed
from records that already exist. A badge for opening the app is not an achievement.

The evaluation is pure: it takes a snapshot of totals and returns which definitions are
satisfied. That makes every rule unit-testable without a database, which matters
because "did this fire when it should have" is the only question anyone will ever ask
about this code.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class AchievementTier(StrEnum):
    """Purely presentational — the tier changes the badge, never the difficulty."""

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class AchievementCategory(StrEnum):
    CONSISTENCY = "consistency"
    VOLUME = "volume"
    STRENGTH = "strength"
    MILESTONE = "milestone"


@dataclass(frozen=True, slots=True)
class AchievementDefinition:
    code: str
    name: str
    description: str
    category: AchievementCategory
    tier: AchievementTier
    # The number the user has to reach. Kept alongside the definition so progress can
    # be shown as "7 of 10" rather than a locked icon with no hint.
    threshold: Decimal

    def progress(self, value: Decimal) -> Decimal:
        """How far along, clamped to 1. Shown as a bar on unearned achievements."""
        if self.threshold <= 0:
            return Decimal(1)
        return min(value / self.threshold, Decimal(1))


@dataclass(frozen=True, slots=True)
class AchievementSnapshot:
    """Everything the rules are allowed to look at.

    A flat snapshot rather than repository access on purpose: it keeps evaluation pure,
    and it makes the full input to any awarding decision visible in one place.
    """

    total_sessions: int
    total_volume_kg: Decimal
    longest_streak_weeks: int
    current_streak_weeks: int
    total_prs: int
    heaviest_lift_kg: Decimal
    distinct_exercises: int
    weeks_since_first_session: int


DEFINITIONS: tuple[AchievementDefinition, ...] = (
    # --- consistency ------------------------------------------------------
    AchievementDefinition(
        code="first_session",
        name="First one down",
        description="Logged your first workout.",
        category=AchievementCategory.MILESTONE,
        tier=AchievementTier.BRONZE,
        threshold=Decimal(1),
    ),
    AchievementDefinition(
        code="ten_sessions",
        name="Getting into it",
        description="Ten sessions logged.",
        category=AchievementCategory.CONSISTENCY,
        tier=AchievementTier.BRONZE,
        threshold=Decimal(10),
    ),
    AchievementDefinition(
        code="fifty_sessions",
        name="Regular",
        description="Fifty sessions logged.",
        category=AchievementCategory.CONSISTENCY,
        tier=AchievementTier.SILVER,
        threshold=Decimal(50),
    ),
    AchievementDefinition(
        code="two_hundred_sessions",
        name="Part of the furniture",
        description="Two hundred sessions logged.",
        category=AchievementCategory.CONSISTENCY,
        tier=AchievementTier.GOLD,
        threshold=Decimal(200),
    ),
    AchievementDefinition(
        code="streak_4_weeks",
        name="A month of showing up",
        description="Four weeks in a row.",
        category=AchievementCategory.CONSISTENCY,
        tier=AchievementTier.BRONZE,
        threshold=Decimal(4),
    ),
    AchievementDefinition(
        code="streak_12_weeks",
        name="A season",
        description="Twelve weeks in a row.",
        category=AchievementCategory.CONSISTENCY,
        tier=AchievementTier.SILVER,
        threshold=Decimal(12),
    ),
    AchievementDefinition(
        code="streak_52_weeks",
        name="A year of it",
        description="Fifty-two weeks in a row.",
        category=AchievementCategory.CONSISTENCY,
        tier=AchievementTier.GOLD,
        threshold=Decimal(52),
    ),
    # --- volume -----------------------------------------------------------
    AchievementDefinition(
        code="volume_100t",
        name="A hundred tonnes",
        description="100,000 kg moved in total.",
        category=AchievementCategory.VOLUME,
        tier=AchievementTier.BRONZE,
        threshold=Decimal(100_000),
    ),
    AchievementDefinition(
        code="volume_1000t",
        name="A thousand tonnes",
        description="1,000,000 kg moved in total.",
        category=AchievementCategory.VOLUME,
        tier=AchievementTier.SILVER,
        threshold=Decimal(1_000_000),
    ),
    AchievementDefinition(
        code="volume_5000t",
        name="Five thousand tonnes",
        description="5,000,000 kg moved in total.",
        category=AchievementCategory.VOLUME,
        tier=AchievementTier.GOLD,
        threshold=Decimal(5_000_000),
    ),
    # --- strength ---------------------------------------------------------
    AchievementDefinition(
        code="first_pr",
        name="First record",
        description="Set your first personal record.",
        category=AchievementCategory.STRENGTH,
        tier=AchievementTier.BRONZE,
        threshold=Decimal(1),
    ),
    AchievementDefinition(
        code="twenty_five_prs",
        name="Twenty-five records",
        description="Twenty-five personal records set.",
        category=AchievementCategory.STRENGTH,
        tier=AchievementTier.SILVER,
        threshold=Decimal(25),
    ),
    AchievementDefinition(
        code="hundred_prs",
        name="A hundred records",
        description="One hundred personal records set.",
        category=AchievementCategory.STRENGTH,
        tier=AchievementTier.GOLD,
        threshold=Decimal(100),
    ),
    # --- breadth ----------------------------------------------------------
    AchievementDefinition(
        code="twenty_exercises",
        name="Well rounded",
        description="Trained twenty different exercises.",
        category=AchievementCategory.MILESTONE,
        tier=AchievementTier.BRONZE,
        threshold=Decimal(20),
    ),
)

BY_CODE: dict[str, AchievementDefinition] = {d.code: d for d in DEFINITIONS}

# Which snapshot field each definition measures. A table rather than a chain of ifs, so
# adding an achievement is one entry in `DEFINITIONS` plus one here — and a definition
# with no measure is a loud KeyError rather than one that silently never awards.
MEASURES: dict[str, str] = {
    "first_session": "total_sessions",
    "ten_sessions": "total_sessions",
    "fifty_sessions": "total_sessions",
    "two_hundred_sessions": "total_sessions",
    "streak_4_weeks": "longest_streak_weeks",
    "streak_12_weeks": "longest_streak_weeks",
    "streak_52_weeks": "longest_streak_weeks",
    "volume_100t": "total_volume_kg",
    "volume_1000t": "total_volume_kg",
    "volume_5000t": "total_volume_kg",
    "first_pr": "total_prs",
    "twenty_five_prs": "total_prs",
    "hundred_prs": "total_prs",
    "twenty_exercises": "distinct_exercises",
}


def measured_value(definition: AchievementDefinition, snapshot: AchievementSnapshot) -> Decimal:
    return Decimal(getattr(snapshot, MEASURES[definition.code]))


def evaluate(
    snapshot: AchievementSnapshot, already_earned: set[str]
) -> list[AchievementDefinition]:
    """Which achievements are newly earned.

    Streaks are measured against the *longest* streak, never the current one. Using the
    current streak would mean a badge disappears when someone takes a week off — which
    is exactly the punitive design this product refuses (docs/09 §1).
    """
    return [
        definition
        for definition in DEFINITIONS
        if definition.code not in already_earned
        and measured_value(definition, snapshot) >= definition.threshold
    ]
