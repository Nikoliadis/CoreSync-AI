"""Shared test fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from coresync.core.clock import FrozenClock
from coresync.core.config import Settings
from coresync.core.ids import uuid7
from coresync.core.security import JwtService, PasswordHasherService
from coresync.domain.profile.entities import (
    ActivityLevel,
    ExperienceLevel,
    Gender,
    Goal,
    GoalType,
    Profile,
)

# A fixed instant so every date-dependent assertion is deterministic.
FIXED_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(FIXED_NOW)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        environment="test",
        jwt_secret_key="test-secret-key-that-is-long-enough-32b",
        # Argon2 at production cost makes a 200-test suite take minutes. These
        # parameters are for speed only and are never used outside tests.
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
    )


@pytest.fixture(scope="session")
def hasher(settings: Settings) -> PasswordHasherService:
    return PasswordHasherService(settings)


@pytest.fixture(scope="session")
def jwt_service(settings: Settings) -> JwtService:
    return JwtService(settings)


@pytest.fixture
def profile() -> Profile:
    """A 24-year-old male, 181 cm, training moderately."""
    return Profile(
        user_id=uuid7(),
        display_name="Test Lifter",
        date_of_birth=date(2002, 3, 15),
        gender=Gender.MALE,
        height_cm=Decimal("181"),
        activity_level=ActivityLevel.MODERATE,
        experience_level=ExperienceLevel.INTERMEDIATE,
    )


@pytest.fixture
def goal() -> Goal:
    return Goal.create(
        user_id=uuid7(),
        goal_type=GoalType.LOSE_FAT,
        target_weight_kg=Decimal("78"),
        weekly_rate_kg=Decimal("-0.45"),
        target_date=None,
        on=FIXED_NOW.date(),
    )
