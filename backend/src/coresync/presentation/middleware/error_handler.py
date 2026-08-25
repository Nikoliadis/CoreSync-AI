"""Translation from domain errors to HTTP responses.

This is the only place in the codebase that decides a status code. Use cases raise
meaning; mapping meaning to HTTP is a presentation concern (docs/05 §6).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from coresync.core.errors import (
    AccountLockedError,
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    QuotaExceededError,
    RateLimitedError,
    UnauthenticatedError,
    UpstreamUnavailableError,
    ValidationError,
)
from coresync.core.logging import get_logger

logger = get_logger(__name__)

_STATUS_MAP: list[tuple[type[AppError], int]] = [
    # Ordered most-specific first: isinstance matching walks this list in order.
    (AccountLockedError, status.HTTP_401_UNAUTHORIZED),
    (UnauthenticatedError, status.HTTP_401_UNAUTHORIZED),
    (ForbiddenError, status.HTTP_403_FORBIDDEN),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (QuotaExceededError, status.HTTP_402_PAYMENT_REQUIRED),
    (RateLimitedError, status.HTTP_429_TOO_MANY_REQUESTS),
    (UpstreamUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (ValidationError, status.HTTP_400_BAD_REQUEST),
]


def _status_for(exc: AppError) -> int:
    for error_type, code in _STATUS_MAP:
        if isinstance(exc, error_type):
            return code
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _body(
    code: str, message: str, request_id: str | None, details: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "requestId": request_id,
            "details": details,
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        status_code = _status_for(exc)
        request_id = getattr(request.state, "request_id", None)

        if status_code >= 500:
            logger.exception("unhandled_app_error", error_code=exc.code, **exc.context)
        elif status_code in (401, 403, 429):
            # The developer-facing reason, not just the code. Without it every rejected
            # sign-in looks identical in the log — "nonce mismatch", "expired", "wrong
            # audience" and "unknown issuer" all read as `invalid_token`, and the one
            # thing an operator needs is which. `str(exc)` is the internal message; the
            # user still sees only `user_message`, and no token is ever logged.
            logger.warning(
                "request_denied",
                error_code=exc.code,
                path=request.url.path,
                reason=str(exc),
            )

        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitedError):
            headers["Retry-After"] = str(exc.retry_after_seconds)
        elif isinstance(exc, AccountLockedError):
            headers["Retry-After"] = str(exc.unlock_in_seconds)

        return JSONResponse(
            status_code=status_code,
            content=_body(exc.code, exc.user_message, request_id, exc.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                # Drop the "body"/"query" prefix — clients care about their field name.
                "field": ".".join(str(p) for p in err["loc"][1:]) or None,
                "code": err["type"],
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_body(
                "validation_error",
                "The request could not be validated.",
                getattr(request.state, "request_id", None),
                details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            401: "unauthenticated",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(
                codes.get(exc.status_code, "http_error"),
                str(exc.detail),
                getattr(request.state, "request_id", None),
                [],
            ),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        # Deliberately opaque: an internal error message can leak schema, file paths or
        # library versions. The request id is how support correlates it to the trace.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body(
                "internal_error",
                "Something went wrong. Please try again.",
                getattr(request.state, "request_id", None),
                [],
            ),
        )
