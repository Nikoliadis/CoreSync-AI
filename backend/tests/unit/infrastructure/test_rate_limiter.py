"""The Redis rate limiter, and what it does when Redis is gone.

The degraded path is the interesting one. A limiter that raises when its counter store is
unreachable makes every endpoint return 500 — turning a lost cache into a full outage,
which is precisely the failure the liveness/readiness split exists to prevent.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from coresync.infrastructure.cache.redis_client import RedisRateLimiter

WINDOW = timedelta(minutes=1)


class FakePipeline:
    def __init__(self, results: list[object] | Exception) -> None:
        self._results = results
        self.commands: list[tuple[str, str]] = []

    def incr(self, key: str) -> None:
        self.commands.append(("incr", key))

    def ttl(self, key: str) -> None:
        self.commands.append(("ttl", key))

    async def execute(self) -> list[object]:
        if isinstance(self._results, Exception):
            raise self._results
        return self._results


class FakeRedis:
    """Just enough Redis to exercise the limiter, including failure injection."""

    def __init__(self, results: list[object] | Exception) -> None:
        self._results = results
        self.pipelines: list[FakePipeline] = []
        self.expired: list[tuple[str, int]] = []
        self.deleted: list[str] = []
        self.delete_error: Exception | None = None

    def pipeline(self) -> FakePipeline:
        pipe = FakePipeline(self._results)
        self.pipelines.append(pipe)
        return pipe

    async def expire(self, key: str, seconds: int) -> None:
        self.expired.append((key, seconds))

    async def delete(self, key: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(key)


class TestRateLimiterNormalOperation:
    async def test_a_hit_under_the_limit_is_allowed(self) -> None:
        limiter = RedisRateLimiter(FakeRedis([1, 60]))  # type: ignore[arg-type]
        allowed, reset_in = await limiter.hit("user:1", limit=10, window=WINDOW)
        assert allowed
        assert reset_in == 60

    async def test_the_hit_on_the_limit_is_still_allowed(self) -> None:
        """A limit of 10 means ten requests succeed, not nine."""
        limiter = RedisRateLimiter(FakeRedis([10, 30]))  # type: ignore[arg-type]
        allowed, _ = await limiter.hit("user:1", limit=10, window=WINDOW)
        assert allowed

    async def test_exceeding_the_limit_is_refused(self) -> None:
        limiter = RedisRateLimiter(FakeRedis([11, 30]))  # type: ignore[arg-type]
        allowed, reset_in = await limiter.hit("user:1", limit=10, window=WINDOW)
        assert not allowed
        assert reset_in == 30

    async def test_the_first_hit_sets_the_window_expiry(self) -> None:
        """Without this the key would live forever and the window never reset."""
        redis = FakeRedis([1, -1])  # -1: key exists with no TTL
        limiter = RedisRateLimiter(redis)  # type: ignore[arg-type]

        allowed, reset_in = await limiter.hit("user:1", limit=10, window=WINDOW)

        assert allowed
        assert reset_in == 60
        assert redis.expired == [("rl:user:1", 60)]

    async def test_keys_are_namespaced(self) -> None:
        redis = FakeRedis([1, 60])
        limiter = RedisRateLimiter(redis)  # type: ignore[arg-type]
        await limiter.hit("anon:1.2.3.4:general", limit=10, window=WINDOW)
        assert redis.pipelines[0].commands == [
            ("incr", "rl:anon:1.2.3.4:general"),
            ("ttl", "rl:anon:1.2.3.4:general"),
        ]

    async def test_reset_deletes_the_counter(self) -> None:
        redis = FakeRedis([1, 60])
        limiter = RedisRateLimiter(redis)  # type: ignore[arg-type]
        await limiter.reset("user:1")
        assert redis.deleted == ["rl:user:1"]


class TestRateLimiterFailsOpen:
    """Redis being unreachable must not take the API down with it."""

    @pytest.mark.parametrize(
        "error",
        [
            RedisTimeoutError("Timeout connecting to server"),
            RedisConnectionError("Error connecting to localhost:6379"),
            OSError("socket error"),
        ],
    )
    async def test_an_unreachable_store_allows_the_request(self, error: Exception) -> None:
        limiter = RedisRateLimiter(FakeRedis(error))  # type: ignore[arg-type]

        allowed, reset_in = await limiter.hit("user:1", limit=10, window=WINDOW)

        assert allowed, "a limiter that cannot count must not refuse the request"
        assert reset_in == 0

    async def test_failing_open_does_not_raise(self) -> None:
        """The middleware has no handler for a Redis error; it would surface as a 500."""
        limiter = RedisRateLimiter(FakeRedis(RedisTimeoutError("down")))  # type: ignore[arg-type]
        # Would raise if the adapter re-raised.
        await limiter.hit("user:1", limit=1, window=WINDOW)
        await limiter.hit("user:1", limit=1, window=WINDOW)

    async def test_reset_failure_is_swallowed(self) -> None:
        """Reset is a courtesy after a successful login. It must not fail the login."""
        redis = FakeRedis([1, 60])
        redis.delete_error = RedisConnectionError("down")
        limiter = RedisRateLimiter(redis)  # type: ignore[arg-type]

        await limiter.reset("user:1")

        assert redis.deleted == []

    async def test_a_programming_error_is_not_swallowed(self) -> None:
        """Failing open covers unreachability, not bugs in the limiter itself.

        Catching everything here would hide a genuine defect behind silently disabled
        rate limiting, which is the worst of both outcomes.
        """
        limiter = RedisRateLimiter(FakeRedis(TypeError("bad pipeline usage")))  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            await limiter.hit("user:1", limit=10, window=WINDOW)
