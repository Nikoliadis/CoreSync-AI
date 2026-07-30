"""Request id, timing and the structured access log."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from coresync.core.ids import uuid7
from coresync.core.logging import get_logger, request_id_var, user_id_var

logger = get_logger("http")

# Endpoints that are polled constantly and say nothing useful when they succeed.
_QUIET_PATHS = frozenset({"/v1/health", "/v1/health/ready", "/metrics"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attaches a correlation id to every request and logs the outcome.

    The id is echoed in the response and included in error bodies, so a user's bug
    report ("request 01H8X…") resolves directly to a trace.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid7())
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        user_token = user_id_var.set(None)

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if request.url.path not in _QUIET_PATHS:
                logger.info(
                    "request",
                    method=request.method,
                    path=request.url.path,
                    status=status_code,
                    duration_ms=duration_ms,
                    client_version=request.headers.get("X-Client-Version"),
                )
            request_id_var.reset(token)
            user_id_var.reset(user_token)
