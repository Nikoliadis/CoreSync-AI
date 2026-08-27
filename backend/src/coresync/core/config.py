"""Application configuration.

This is the only module that reads the environment. Everything else receives a
``Settings`` instance. Validation happens at import time, so a misconfigured process
refuses to start rather than failing on the first request that needs the bad value.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- application
    environment: Environment = "development"
    debug: bool = False
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    mobile_deep_link_scheme: str = "coresync"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    # ---------------------------------------------------------------- database
    # Pydantic coerces the string default into the DSN type at validation time; mypy
    # only sees the annotation, hence the ignore.
    database_url: PostgresDsn = Field(  # type: ignore[assignment]
        default="postgresql+asyncpg://coresync:coresync@localhost:5432/coresync"
    )
    database_replica_url: PostgresDsn | None = None
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_statement_timeout_ms: int = 15_000
    database_echo: bool = False

    # ---------------------------------------------------------------- cache
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")  # type: ignore[assignment]

    # Celery rides on the Redis that is already here. A second broker would be a second
    # thing to run, monitor and lose messages in, for work that is neither high volume
    # nor long running. Separate logical databases so a `FLUSHDB` on the cache cannot
    # take the queue with it.
    celery_broker_url: str = Field(default="")
    celery_result_backend: str = Field(default="")

    # How often the outbox is drained. Every notification this product sends is a
    # reminder or a nudge, so a minute of latency is invisible; polling harder would
    # just be load with nothing to show for it.
    outbox_dispatch_seconds: int = Field(default=60, ge=5, le=3600)

    # Accounts past their grace period are erased on this cadence. Daily rather than
    # hourly: the deadline is a date, and running more often only shortens the window
    # in which a user can still change their mind.
    erasure_sweep_hour_utc: int = Field(default=3, ge=0, le=23)

    # ---------------------------------------------------------------- auth
    jwt_secret_key: str = "development-secret-not-for-production-use-only"  # noqa: S105
    jwt_algorithm: Literal["HS256", "RS256"] = "HS256"
    jwt_issuer: str = "https://api.coresync.ai"
    jwt_audience: str = "coresync-client"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    password_reset_ttl_minutes: int = 30
    email_verification_ttl_hours: int = 24

    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65_536
    argon2_parallelism: int = 4

    max_failed_logins: int = 10
    account_lockout_minutes: int = 15

    #: The web OAuth client id, used by the browser flow.
    google_oauth_client_id: str = ""
    #: Native client ids, one per platform.
    #:
    #: Google issues a separate client id for Web, iOS and Android, and stamps whichever
    #: one requested the token into `aud`. A verifier that knows only the web id rejects
    #: every sign-in from a phone — the same defect the Apple verifier had.
    google_ios_client_id: str = ""
    google_android_client_id: str = ""
    #: The Services ID, used by the *web* Sign in with Apple flow.
    apple_service_id: str = ""
    #: The iOS app's bundle identifier.
    #:
    #: Apple issues a native token with `aud` set to the bundle id, and a web token with
    #: `aud` set to the Services ID. They are different strings, so a verifier that knows
    #: only one of them rejects every sign-in from the other platform.
    apple_bundle_id: str = ""

    # ----------------------------------------------------------------- push
    #: Enables the Expo push sender. Off by default so a deployment without push
    #: configured skips the channel cleanly rather than failing every notification.
    push_enabled: bool = False
    #: Optional. Only needed when the Expo project enforces push security; it is a
    #: server credential and must never be shipped in a client build.
    expo_access_token: str = ""

    # ---------------------------------------------------------------- email
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    email_from: str = "CoreSync <no-reply@coresync.ai>"

    # ---------------------------------------------------------------- limits
    rate_limit_anonymous_per_minute: int = 30
    rate_limit_authenticated_per_minute: int = 120
    # Deliberately generous: a lifter logging supersets can outpace the blanket limit,
    # and throttling someone mid-workout is a product failure (docs/04 §3).
    rate_limit_set_logging_per_minute: int = 300
    # Bulk endpoint with large payloads, so the opposite direction.
    rate_limit_sync_per_minute: int = 20
    cors_allowed_origins: str = "http://localhost:3000"
    # The coach is the expensive endpoint; a tight per-minute limit also blunts the
    # obvious abuse of using someone else's account as a free LLM proxy.
    rate_limit_ai_chat_per_minute: int = 10

    # ---------------------------------------------------------------- ai
    # Empty by default so the whole application runs, tests included, with no provider
    # configured. ``ai_enabled`` reports whether a real gateway can be built; everything
    # AI-shaped degrades to a clear 503 rather than failing at import.
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-10-21"
    # Deployment names, not model names: on Azure the deployment is what you address, and
    # conflating the two is the most common reason a working config fails in another
    # environment.
    azure_openai_chat_deployment: str = "gpt-4o"
    azure_openai_mini_deployment: str = "gpt-4o-mini"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"

    ai_request_timeout_seconds: float = 60.0
    ai_max_tool_iterations: int = 4
    ai_context_message_limit: int = 12
    ai_embedding_dimensions: int = 1536

    # Free-tier quotas, enforced per user per local day (docs/10 §9).
    ai_free_daily_message_limit: int = 20
    ai_free_daily_cost_ceiling_usd: float = 0.50

    # ---------------------------------------------------------------- derived
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def ai_enabled(self) -> bool:
        """Whether a real provider is configured.

        Checked at the composition root so an unconfigured deployment returns a clear
        503 from the AI endpoints while the rest of the API works normally.
        """
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def broker_url(self) -> str:
        """The Celery broker, defaulting to database 1 of the configured Redis.

        Explicit configuration wins; the fallback exists so a developer who set only
        `REDIS_URL` gets a working worker instead of a connection error.
        """
        return self.celery_broker_url or self._redis_db(1)

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self._redis_db(2)

    def _redis_db(self, index: int) -> str:
        base = str(self.redis_url).rstrip("/")
        # RedisDsn always carries a path; swap the database rather than appending, or
        # `redis://host:6379/0` becomes `redis://host:6379/0/1`.
        head, _, tail = base.rpartition("/")
        return f"{head}/{index}" if tail.isdigit() else f"{base}/{index}"

    @property
    def sync_database_url(self) -> str:
        """Alembic and other synchronous tooling need the psycopg driver."""
        return str(self.database_url).replace("+asyncpg", "")

    # ---------------------------------------------------------------- validation
    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return upper

    @model_validator(mode="after")
    def _production_requires_real_secrets(self) -> Settings:
        """Fail fast rather than run production on a development secret.

        This check exists because the failure it prevents — shipping with the default
        signing key — is silent, catastrophic and has happened to everyone once.
        """
        if not self.is_production:
            return self
        if "development" in self.jwt_secret_key or len(self.jwt_secret_key) < 32:
            raise ValueError("jwt_secret_key must be a real 32+ byte secret in production")
        if self.debug:
            raise ValueError("debug must be false in production")
        if any(o.startswith("http://") for o in self.cors_origins):
            raise ValueError("cors origins must be https in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
