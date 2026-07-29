"""Security headers and per-user rate limiting."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from coresync.application.common.ports import RateLimiter
from coresync.core.config import Settings
from coresync.core.errors import RateLimitedError

_STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(self)",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    # The API returns JSON only, so it needs no script or style sources at all.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._is_production = settings.is_production

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in _STATIC_HEADERS.items():
            response.headers.setdefault(header, value)
        if self._is_production:
            # Only over HTTPS — sending HSTS from a local http:// server would pin
            # developers' browsers to https://localhost.
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Coarse per-identity limiting.

    Endpoint-specific buckets (login, password reset) are applied inside their routes,
    where the key can include the email being targeted. This middleware is the blanket
    fairness limit on top of that.
    """

    _EXEMPT = frozenset({"/v1/health", "/v1/health/ready", "/v1/version", "/docs", "/openapi.json"})

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._anonymous_limit = settings.rate_limit_anonymous_per_minute
        self._authenticated_limit = settings.rate_limit_authenticated_per_minute
        self._set_logging_limit = settings.rate_limit_set_logging_per_minute
        self._sync_limit = settings.rate_limit_sync_per_minute

    def _limit_for(self, request: Request, default: int) -> tuple[int, str]:
        """Per-endpoint overrides on top of the blanket limit.

        Matched on the path shape rather than the route name because middleware runs
        before routing has resolved. Each override gets its own bucket suffix, so a burst
        of set logging cannot consume the user's general allowance and vice versa.
        """
        if request.method != "POST":
            return default, "general"
        path = request.url.path
        if path.endswith("/sets"):
            return self._set_logging_limit, "sets"
        if path.endswith("/workouts/sessions/sync"):
            return self._sync_limit, "sync"
        return default, "general"

    @staticmethod
    def _limiter_for(request: Request) -> RateLimiter | None:
        """Resolve the limiter from app state at request time.

        Middleware is constructed before the lifespan runs, so the Redis-backed limiter
        does not exist yet at __init__. Reading it per request also means a test app
        without Redis simply skips limiting rather than failing to build.
        """
        container = getattr(request.app.state, "container", None)
        return getattr(container, "rate_limiter", None) if container else None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in self._EXEMPT or request.method == "OPTIONS":
            return await call_next(request)

        limiter = self._limiter_for(request)
        if limiter is None:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # Keyed on the token rather than the user id: identity is not resolved yet
            # at middleware time, and the token is a stable per-session identifier.
            key = f"authed:{hash(auth_header[7:]) & 0xFFFFFFFF}"
            limit, bucket = self._limit_for(request, self._authenticated_limit)
        else:
            key = f"anon:{self._client_ip(request)}"
            limit, bucket = self._limit_for(request, self._anonymous_limit)

        allowed, reset_in = await limiter.hit(
            f"{key}:{bucket}", limit=limit, window=timedelta(minutes=1)
        )
        if not allowed:
            raise RateLimitedError(reset_in)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Reset"] = str(reset_in)
        return response

    @staticmethod
    def _client_ip(request: Request) -> str:
        # Behind Front Door / Vercel the real client is the first X-Forwarded-For entry.
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"
