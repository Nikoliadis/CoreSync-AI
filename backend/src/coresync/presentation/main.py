"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from coresync.core.config import Settings, get_settings
from coresync.core.logging import configure_logging, get_logger
from coresync.presentation.api.v1.router import api_router
from coresync.presentation.dependencies import build_container
from coresync.presentation.middleware.error_handler import register_exception_handlers
from coresync.presentation.middleware.request_context import RequestContextMiddleware
from coresync.presentation.middleware.security import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

logger = get_logger(__name__)

DESCRIPTION = """
The CoreSync AI API.

**Available now**
* **Identity** — registration, email verification, sign-in, refresh-token rotation,
  Google and Apple sign-in.
* **Profile** — onboarding, goals and nutrition targets.
* **Workouts** — exercise catalog, routines, live session logging, personal records,
  history, and a bulk offline-sync endpoint.
* **Progress** — weight with an EWMA trend, body measurements, statistics and the
  dashboard bundle.

**Not yet built:** nutrition logging, progress photos and the AI coach.

Conventions:
* camelCase on the wire, cursor pagination, `Idempotency-Key` on creating POSTs.
* Errors share one shape; branch on `error.code`, never on `error.message`.
* All measurements are canonical SI — kg, cm, ml, kcal, grams. Unit conversion is a
  presentation concern.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_format == "json")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The object graph is built once here. A failure to construct it — a bad DSN, a
        # missing secret — stops the process at boot rather than on first request.
        app.state.container = build_container(settings)
        logger.info("api_started", environment=settings.environment)
        try:
            yield
        finally:
            await app.state.container.database.dispose()
            await app.state.container.redis.aclose()
            logger.info("api_stopped")

    app = FastAPI(
        title="CoreSync AI API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        # No custom response class: FastAPI now serialises straight to JSON bytes via
        # Pydantic when a response model is declared, which is faster than routing through
        # ORJSONResponse and no longer needs it. Passing one emits a deprecation warning,
        # which the test suite (filterwarnings = error) turns into a failure on every
        # response. docs/05 §10 still cites orjson for this and is out of date.
        # The schema is public in development and behind auth in production, so an
        # attacker cannot enumerate the API surface for free.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
    )

    # Starlette applies middleware in reverse registration order, so the last one added
    # is outermost. Request context must be outermost: every log line, error body and
    # rate-limit rejection below it needs the request id to already exist.
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        # An explicit list. `allow_origins=["*"]` with credentials is rejected by
        # browsers anyway, and the settings validator forbids http:// in production.
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-Id",
            "X-Client-Version",
            "X-Timezone",
            "Idempotency-Key",
        ],
        expose_headers=["X-Request-Id", "X-RateLimit-Limit", "X-RateLimit-Reset", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
