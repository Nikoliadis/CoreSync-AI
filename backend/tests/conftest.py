"""Shared test fixtures."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

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


# ----------------------------------------------------------------- database
# Defined here rather than in `tests/api/` so the API and integration suites share a
# single container. Two containers would double an already slow suite and give the two
# halves different schemas the moment a migration lands in only one of them.
API_ROOT = Path(__file__).resolve().parents[1]


def subprocess_env(database_url: str) -> dict[str, str]:
    """The parent environment with the database settings overridden.

    Not a minimal env: on Windows, stripping ``PATH`` and ``SystemRoot`` stops Winsock
    from initialising and the child dies with ``WinError 10106`` before it runs any of
    our code. Overriding the keys that matter achieves the actual goal — the child must
    not inherit a developer's real ``DATABASE_URL`` — without breaking the interpreter.
    """
    return {
        **os.environ,
        "DATABASE_URL": database_url,
        "ENVIRONMENT": "test",
        "JWT_SECRET_KEY": "integration-test-secret-key-32-bytes!",
    }


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    # `testcontainers.postgres` is deprecated and emits a DeprecationWarning, which
    # `filterwarnings = ["error"]` turns into a fixture error.
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        url = container.get_connection_url()
        # Migrations are run rather than metadata.create_all: this is the only way the
        # test schema is guaranteed to match production, triggers and all.
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=API_ROOT,
            check=True,
            env=subprocess_env(url),
        )
        yield url
