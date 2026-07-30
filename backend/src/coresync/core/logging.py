"""Structured logging.

JSON in deployed environments, human-readable locally. Every log line carries the
request id and, where known, the user id — so a support ticket resolves to a trace.

The redaction processor is not optional decoration: this system handles health data,
and PII in logs is a reportable breach in its own right.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

# Keys whose values never reach a log sink, wherever they appear in the event dict.
_REDACTED_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "cookie",
        "set-cookie",
        "secret",
        "api_key",
        "client_secret",
        # Product data that is never operationally necessary in a log line.
        "message_content",
        "ai_message",
        "diary_entry",
        "photo_path",
        "blob_path",
    }
)


def _redact(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        lowered = key.lower()
        if lowered in _REDACTED_KEYS:
            event_dict[key] = "[redacted]"
        elif lowered in {"email", "user_email"} and isinstance(event_dict[key], str):
            # Emails are pseudonymised rather than dropped: correlation stays possible,
            # the address does not sit in the log store.
            event_dict[key] = _pseudonymise_email(event_dict[key])
    return event_dict


def _pseudonymise_email(email: str) -> str:
    import hashlib

    return f"email:{hashlib.sha256(email.lower().encode()).hexdigest()[:16]}"


def _add_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    if (request_id := request_id_var.get()) is not None:
        event_dict.setdefault("request_id", request_id)
    if (user_id := user_id_var.get()) is not None:
        event_dict.setdefault("user_id", user_id)
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    # Third-party loggers that are noisy at INFO and useless in aggregate.
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _add_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
