"""API test harness.

A real FastAPI app against a real PostgreSQL container, with Redis, SMTP and the
identity providers replaced by in-memory doubles. Real database, because the
constraints and partial indexes carry correctness guarantees a fake cannot reproduce.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coresync.application.common.ports import OidcIdentity
from coresync.application.identity.auth import TokenIssuer
from coresync.core.clock import SystemClock
from coresync.core.config import Settings
from coresync.core.security import JwtService, PasswordHasherService
from coresync.domain.identity.entities import AuthProvider
from coresync.domain.identity.policies import PasswordPolicy
from coresync.domain.profile.services import TdeeCalculator
from coresync.domain.progress.services import (
    GoalProjector,
    MeasurementTrendCalculator,
    WeightTrendCalculator,
)
from coresync.domain.workout.services import PersonalRecordDetector, VolumeCalculator
from coresync.infrastructure.database.session import Database
from coresync.presentation.dependencies import AppContainer
from coresync.presentation.main import create_app
from tests.fakes import (
    CapturingEmailSender,
    FakeBreachChecker,
    FakeOidcVerifier,
    FakeRateLimiter,
    FakeRevocationStore,
)

API_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


def subprocess_env(database_url: str) -> dict[str, str]:
    """The parent environment with the database settings overridden.

    Not a minimal env: on Windows, stripping ``PATH`` and ``SystemRoot`` stops Winsock
    from initialising and the child dies with ``WinError 10106`` before it runs any of our
    code. Overriding the keys that matter achieves the actual goal — the child must not
    inherit a developer's real ``DATABASE_URL`` — without breaking the interpreter.
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


@pytest.fixture(scope="session")
def api_settings(postgres_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=postgres_url,  # type: ignore[arg-type]
        jwt_secret_key="integration-test-secret-key-32-bytes!",
        access_token_ttl_minutes=15,
        refresh_token_ttl_days=30,
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
        cors_allowed_origins="http://localhost:3000",
    )


@pytest.fixture
def email_sender() -> CapturingEmailSender:
    return CapturingEmailSender()


@pytest.fixture
def google_verifier() -> FakeOidcVerifier:
    return FakeOidcVerifier(
        OidcIdentity(
            subject="google-subject-123",
            email="social@example.com",
            email_verified=True,
            name="Social User",
            provider="google",
        )
    )


@pytest_asyncio.fixture
async def container(
    api_settings: Settings,
    email_sender: CapturingEmailSender,
    google_verifier: FakeOidcVerifier,
) -> AsyncIterator[AppContainer]:
    clock = SystemClock()
    jwt_service = JwtService(api_settings)
    database = Database(api_settings)

    yield AppContainer(
        settings=api_settings,
        database=database,
        redis=None,  # type: ignore[arg-type] — no Redis in the API suite
        clock=clock,
        jwt=jwt_service,
        hasher=PasswordHasherService(api_settings),
        password_policy=PasswordPolicy(),
        tdee_calculator=TdeeCalculator(),
        # The domain services are pure and deterministic, so the real ones are used
        # rather than doubles — substituting them would test the double, not the rules.
        pr_detector=PersonalRecordDetector(),
        volume_calculator=VolumeCalculator(),
        weight_trend_calculator=WeightTrendCalculator(),
        measurement_trend_calculator=MeasurementTrendCalculator(),
        goal_projector=GoalProjector(),
        email_sender=email_sender,
        revocation_store=FakeRevocationStore(),
        rate_limiter=FakeRateLimiter(),
        breach_checker=FakeBreachChecker({"leaked-passphrase-alpha"}),
        oidc_verifiers={
            AuthProvider.GOOGLE: google_verifier,
            AuthProvider.APPLE: FakeOidcVerifier(),
        },
        token_issuer=TokenIssuer(jwt_service, api_settings, clock),
    )
    await database.dispose()


@pytest_asyncio.fixture
async def client(api_settings: Settings, container: AppContainer) -> AsyncIterator[AsyncClient]:
    app = create_app(api_settings)
    app.state.container = container  # bypass the lifespan; the container is already built
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Client-Version": "test/1.0"},
    ) as http_client:
        yield http_client


# A plain pytest fixture, not pytest_asyncio: the body is synchronous, and
# `pytest_asyncio.fixture` is only for async ones.
@pytest.fixture(scope="session", autouse=True)
def seeded_catalog(postgres_url: str) -> None:
    """Seed the exercise catalog once for the whole suite.

    Workout tests need real exercises to log against, and the catalog is reference data
    that no test owns. Seeded once rather than per-test because it is ~270 exercises and
    nothing under test mutates the global rows.
    """
    subprocess.run(
        [sys.executable, "-m", "coresync.infrastructure.seed.runner"],
        cwd=API_ROOT,
        check=True,
        env=subprocess_env(postgres_url),
    )


@pytest_asyncio.fixture(autouse=True)
async def clean_database(api_settings: Settings, seeded_catalog: None) -> AsyncIterator[None]:
    """Remove user data between tests, leaving the seeded catalog alone.

    ``DELETE FROM users`` rather than ``TRUNCATE users CASCADE``: truncate-cascade empties
    every table with a foreign key to users, which includes ``exercises`` — that would
    wipe the global catalog along with the test's data. A row-wise delete follows the
    ``ON DELETE CASCADE`` chains instead, taking custom exercises with it and leaving the
    global ones standing. Real commits, because that is the behaviour under test.
    """
    yield
    engine = create_async_engine(str(api_settings.database_url))
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
    async with factory() as session:
        from sqlalchemy import text

        await session.execute(text("DELETE FROM users"))
        await session.commit()
    await engine.dispose()


# ------------------------------------------------------------------- helpers
DEFAULT_PASSWORD = "a-strong-enough-passphrase-2026"


async def register_and_verify(
    client: AsyncClient,
    email_sender: CapturingEmailSender,
    *,
    email: str = "lifter@example.com",
    password: str = DEFAULT_PASSWORD,
) -> dict:
    """Register, consume the verification link, and return the signed-in token payload."""
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "displayName": "Test Lifter",
            "timezone": "Europe/Athens",
            "acceptedTerms": True,
        },
    )
    assert response.status_code == 201, response.text

    token = email_sender.token_from("verification")
    verified = await client.post("/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200, verified.text
    return verified.json()


def auth_header(token_payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_payload['accessToken']}"}


async def exercise_id_for(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    """Resolve a seeded exercise by name.

    Tests name the movement they mean ("Barbell Bench Press") rather than hard-coding a
    uuid, so the catalog can be re-ordered or re-keyed without touching the suite.
    """
    response = await client.get("/v1/exercises", params={"q": name}, headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    match = next((item for item in items if item["name"] == name), None)
    assert match is not None, f"seeded exercise '{name}' not found"
    return str(match["id"])
