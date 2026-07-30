"""Redis adapters: token revocation, rate limiting and general caching."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import ConnectionPool, Redis

from coresync.core.config import Settings


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
    """

    _PREFIX = "revoked:jti:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def revoke(self, jti: UUID, ttl: timedelta) -> None:
        await self._redis.setex(f"{self._PREFIX}{jti}", int(ttl.total_seconds()), "1")

    async def is_revoked(self, jti: UUID) -> bool:
        return await self._redis.exists(f"{self._PREFIX}{jti}") == 1


class RedisRateLimiter:
    """Fixed-window counter.

    A sliding window is more accurate but needs a sorted set per key. For login and
    password-reset throttling the extra precision buys nothing — the window boundary
    just means an attacker gets 2N attempts across a boundary instead of N, which is
    still far below what credential stuffing needs.
    """

    _PREFIX = "rl:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, *, limit: int, window: timedelta) -> tuple[bool, int]:
        redis_key = f"{self._PREFIX}{key}"
        seconds = int(window.total_seconds())

        pipe = self._redis.pipeline()
        pipe.incr(redis_key)
        pipe.ttl(redis_key)
        count, ttl = await pipe.execute()

        if ttl < 0:  # first hit in this window, or TTL was lost
            await self._redis.expire(redis_key, seconds)
            ttl = seconds

        return count <= limit, int(ttl)

    async def reset(self, key: str) -> None:
        await self._redis.delete(f"{self._PREFIX}{key}")


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
