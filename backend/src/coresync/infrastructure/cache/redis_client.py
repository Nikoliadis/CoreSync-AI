"""Redis adapters: token revocation, rate limiting and general caching."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from coresync.core.config import Settings
from coresync.core.errors import UpstreamUnavailableError
from coresync.core.logging import get_logger

logger = get_logger(__name__)


def create_redis(settings: Settings) -> Redis:
    pool = ConnectionPool.from_url(
        str(settings.redis_url),
        max_connections=50,
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=2,
        socket_keepalive=True,
    )
    return Redis(connection_pool=pool)


class RedisTokenRevocationStore:
    """Blocklist for access tokens revoked before their natural expiry.

    Entries live only as long as the token would have. The set therefore stays roughly
    proportional to recent logouts, not to total users.

    **Unavailability fails closed, unlike the rate limiter.** The two look alike and are
    not: a limiter that cannot count costs fairness, while a blocklist that cannot answer
    costs the ability to honour a logout. Failing open here would silently resurrect every
    revoked token, so an unreachable Redis raises instead — as an upstream failure (503),
    which is both true and retryable, rather than an unauthenticated 401 that would tell
    the user their perfectly good session had ended.
    """

    _PREFIX = "revoked:jti:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def revoke(self, jti: UUID, ttl: timedelta) -> None:
        """Best-effort. The durable half of a logout is the refresh-token revocation in
        Postgres; this only shortens the window on an access token that expires in
        minutes anyway. Failing the whole logout over it would be worse than leaving that
        window open, so the failure is logged and the logout stands."""
        try:
            await self._redis.setex(f"{self._PREFIX}{jti}", int(ttl.total_seconds()), "1")
        except (RedisError, OSError) as exc:
            logger.warning(
                "token_revocation_store_unavailable",
                operation="revoke",
                error=type(exc).__name__,
                access_token_remains_valid_until_expiry=True,
            )

    async def is_revoked(self, jti: UUID) -> bool:
        try:
            return await self._redis.exists(f"{self._PREFIX}{jti}") == 1
        except (RedisError, OSError) as exc:
            logger.error(
                "token_revocation_store_unavailable",
                operation="is_revoked",
                error=type(exc).__name__,
            )
            raise UpstreamUnavailableError from exc


class RedisRateLimiter:
    """Fixed-window counter.

    A sliding window is more accurate but needs a sorted set per key. For login and
    password-reset throttling the extra precision buys nothing — the window boundary
    just means an attacker gets 2N attempts across a boundary instead of N, which is
    still far below what credential stuffing needs.

    **Unavailability fails open.** If Redis cannot be reached the request is allowed and
    a warning is logged. A rate limiter is a fairness mechanism, not an authorisation
    one: making every endpoint return 500 because the counter store is unreachable turns
    a degraded dependency into a total outage, which is the failure mode the liveness /
    readiness split exists to avoid. Readiness already reports Redis as down, so the loss
    of limiting is visible to alerting rather than silent.
    """

    _PREFIX = "rl:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, *, limit: int, window: timedelta) -> tuple[bool, int]:
        redis_key = f"{self._PREFIX}{key}"
        seconds = int(window.total_seconds())

        try:
            pipe = self._redis.pipeline()
            pipe.incr(redis_key)
            pipe.ttl(redis_key)
            count, ttl = await pipe.execute()

            if ttl < 0:  # first hit in this window, or TTL was lost
                await self._redis.expire(redis_key, seconds)
                ttl = seconds
        except (RedisError, OSError) as exc:
            # Deliberately not re-raised. See the class docstring.
            logger.warning("rate_limiter_unavailable", error=type(exc).__name__, failing_open=True)
            return True, 0

        return count <= limit, int(ttl)

    async def reset(self, key: str) -> None:
        try:
            await self._redis.delete(f"{self._PREFIX}{key}")
        except (RedisError, OSError) as exc:
            # Reset is a best-effort courtesy — clearing a counter after a successful
            # login, for instance. Failing it must not fail the operation that asked.
            logger.warning("rate_limiter_reset_failed", error=type(exc).__name__)


class CacheService:
    """Namespaced, versioned JSON cache.

    The version prefix means a schema change invalidates a whole class of keys by
    bumping a constant, instead of scanning for keys to delete.
    """

    VERSION = "v1"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, key: str) -> str:
        return f"{self.VERSION}:{key}"

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(self._key(key))
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: timedelta) -> None:
        await self._redis.setex(self._key(key), int(ttl.total_seconds()), json.dumps(value))

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*(self._key(k) for k in keys))

    async def delete_pattern(self, pattern: str) -> None:
        """Delete by pattern using SCAN.

        Never KEYS — it blocks the server for the duration of the scan, and on a cache
        of any size that is a self-inflicted outage.
        """
        cursor = 0
        match = self._key(pattern)
        while True:
            cursor, keys = await self._redis.scan(cursor=cursor, match=match, count=500)
            if keys:
                await self._redis.delete(*keys)
            if cursor == 0:
                break
