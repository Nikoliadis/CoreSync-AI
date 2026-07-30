"""Health, readiness and version endpoints."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from coresync.presentation.dependencies import Container
from coresync.presentation.schemas.common import ApiModel

router = APIRouter(tags=["system"])


class HealthResponse(ApiModel):
    status: str
    version: str


class ReadinessResponse(ApiModel):
    status: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Liveness only — touches no dependency.

    Conflating this with readiness means a slow Redis triggers a restart storm, which
    turns a degraded dependency into a full outage.
    """
    return HealthResponse(status="ok", version=os.getenv("BUILD_VERSION", "dev"))


# A cold pool connection includes TCP setup, TLS and authentication; measured at ~300 ms
# against a local container and slower across a network. A 250 ms budget therefore failed
# healthy instances on their first probe, pulling a fresh pod out of the load balancer for
# no reason — the restart storm this endpoint exists to prevent. Two seconds is still far
# below any sensible probe interval, and a dependency slower than that is genuinely unwell.
_PROBE_TIMEOUT_SECONDS = 2.0


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(container: Container, response: Response) -> ReadinessResponse:
    """Checks the dependencies this instance needs to serve traffic."""
    checks: dict[str, str] = {}

    async def check_database() -> None:
        try:
            async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                async with container.database.session() as session:
                    await session.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"

    async def check_redis() -> None:
        try:
            async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                await container.redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"

    await asyncio.gather(check_database(), check_redis())

    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if healthy else "degraded", checks=checks)


class VersionResponse(ApiModel):
    version: str
    commit: str
    environment: str
    minimum_client_version: dict[str, str]


@router.get("/version", response_model=VersionResponse, summary="Build and client requirements")
async def version(container: Container) -> VersionResponse:
    return VersionResponse(
        version=os.getenv("BUILD_VERSION", "dev"),
        commit=os.getenv("BUILD_COMMIT", "unknown"),
        environment=container.settings.environment,
        # Clients below these versions are asked to update. Mobile cannot be
        # force-upgraded quickly, so this is how a breaking change is coordinated.
        minimum_client_version={"ios": "1.0.0", "android": "1.0.0", "web": "1.0.0"},
    )
