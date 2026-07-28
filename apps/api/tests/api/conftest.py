"""API test harness.

A real FastAPI app against a real PostgreSQL container, with Redis, SMTP and the
identity providers replaced by in-memory doubles. Real database, because the
constraints and partial indexes carry correctness guarantees a fake cannot reproduce.
"""

from __future__ import annotations

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


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        url = container.get_connection_url()
        # Migrations are run rather than metadata.create_all: this is the only way the
        # test schema is guaranteed to match production, triggers and all.
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=API_ROOT,
            check=True,
            env={"DATABASE_URL": url, "ENVIRONMENT": "test", "PATH": ""},
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
        email_sender=email_sender,
        revocation_store=FakeRevocationStore(),
        rate_limiter=FakeRateLimiter(),
        breach_checker=FakeBreachChecker({"breached-password-123"}),
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


@pytest_asyncio.fixture(autouse=True)
async def clean_database(api_settings: Settings) -> AsyncIterator[None]:
    """Truncate between tests.

    TRUNCATE ... CASCADE rather than per-test transactions, because the API goes through
    its own sessions and commits for real — which is the behaviour under test.
    """
    yield
    engine = create_async_engine(str(api_settings.database_url))
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
    async with factory() as session:
        from sqlalchemy import text

        await session.execute(text("TRUNCATE users CASCADE"))
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
