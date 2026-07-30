"""Breached-password checking via Have I Been Pwned.

Uses the k-anonymity range API: only the first five characters of the SHA-1 hash are
sent, and the response is a list of suffixes to match locally. The password itself, and
enough of its hash to identify it, never leave this process.
"""

from __future__ import annotations

import hashlib

import httpx

from coresync.core.logging import get_logger

logger = get_logger(__name__)

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"


class HibpBreachChecker:
    def __init__(self, *, timeout_seconds: float = 2.0, fail_open: bool = True) -> None:
        self._timeout = timeout_seconds
        # Fail open on purpose: if HIBP is down, users must still be able to register
        # and reset passwords. The policy checks in PasswordPolicy still apply.
        self._fail_open = fail_open
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": "CoreSync/1.0", "Add-Padding": "true"},
            )
        return self._client

    async def is_breached(self, password: str) -> bool:
        digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324
        prefix, suffix = digest[:5], digest[5:]

        try:
            client = await self._get_client()
            response = await client.get(f"{_HIBP_RANGE_URL}{prefix}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("hibp_unavailable", error=str(exc))
            return False if self._fail_open else True

        for line in response.text.splitlines():
            candidate, _, count = line.partition(":")
            if candidate == suffix and count.strip() not in ("", "0"):
                return True
        return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class NoopBreachChecker:
    """Used in tests and local development — no outbound call."""

    def __init__(self, breached: set[str] | None = None) -> None:
        self._breached = breached or set()

    async def is_breached(self, password: str) -> bool:
        return password in self._breached
