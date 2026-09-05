"""In-memory test doubles for the application ports.

These let the API tests run against a real database while keeping Redis, SMTP and the
identity providers out of the loop — the parts whose behaviour we are not testing and
whose absence should never make a test fail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from coresync.application.common.ports import OidcIdentity
from coresync.core.errors import InvalidTokenError
from coresync.domain.progress.repositories import StoredObject


class FakeRevocationStore:
    def __init__(self) -> None:
        self.revoked: set[UUID] = set()

    async def revoke(self, jti: UUID, ttl: timedelta) -> None:
        self.revoked.add(jti)

    async def is_revoked(self, jti: UUID) -> bool:
        return jti in self.revoked


class FakeRateLimiter:
    """Counts hits and allows everything unless a limit is explicitly configured.

    Tests that assert on throttling set ``limits``; every other test is unaffected,
    which keeps rate limiting from becoming an incidental source of flakiness.
    """

    def __init__(self) -> None:
        self.hits: dict[str, int] = {}
        self.limits: dict[str, int] = {}

    async def hit(self, key: str, *, limit: int, window: timedelta) -> tuple[bool, int]:
        self.hits[key] = self.hits.get(key, 0) + 1
        effective = self.limits.get(key.split(":")[0])
        if effective is None:
            return True, int(window.total_seconds())
        return self.hits[key] <= effective, int(window.total_seconds())

    async def reset(self, key: str) -> None:
        self.hits.pop(key, None)


class CapturingEmailSender:
    """Records every email instead of sending it.

    Tests read verification and reset links straight out of ``sent`` — which is also
    how they obtain single-use tokens, since those are only ever hashed in the database.
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def _record(self, kind: str, to: str, **fields: str) -> None:
        self.sent.append({"kind": kind, "to": to, **fields})

    def last(self, kind: str) -> dict[str, str]:
        for entry in reversed(self.sent):
            if entry["kind"] == kind:
                return entry
        raise AssertionError(f"no {kind!r} email was sent; got {[e['kind'] for e in self.sent]}")

    def token_from(self, kind: str) -> str:
        return self.last(kind)["url"].split("token=")[1]

    async def send_verification(self, *, to: str, name: str, verify_url: str) -> None:
        self._record("verification", to, name=name, url=verify_url)

    async def send_password_reset(self, *, to: str, name: str, reset_url: str) -> None:
        self._record("password_reset", to, name=name, url=reset_url)

    async def send_password_changed(self, *, to: str, name: str) -> None:
        self._record("password_changed", to, name=name)

    async def send_account_exists_notice(self, *, to: str, sign_in_url: str) -> None:
        self._record("account_exists", to, url=sign_in_url)


class FakeBreachChecker:
    def __init__(self, breached: set[str] | None = None) -> None:
        self.breached = breached or set()

    async def is_breached(self, password: str) -> bool:
        return password in self.breached


class FakeOidcVerifier:
    """Returns a scripted identity.

    Any token starting with ``invalid`` is rejected, so both paths are testable. Matched
    by prefix rather than equality because the request schema enforces a minimum token
    length, and a short sentinel never reaches the verifier.
    """

    def __init__(self, identity: OidcIdentity | None = None) -> None:
        self.identity = identity

    async def verify(self, id_token: str, *, nonce: str | None = None) -> OidcIdentity:
        if id_token.startswith("invalid") or self.identity is None:
            raise InvalidTokenError("fake rejection")
        return self.identity


class InMemoryObjectStorage:
    """An ``ObjectStoragePort`` backed by a dict.

    The upload URL it returns is not a real URL and nothing writes to it — tests put the
    bytes in directly with ``put``, standing in for the client's direct upload. That is
    the honest boundary: what the API is responsible for is the credential and what
    happens to the object afterwards, not S3's own PUT handling.
    """

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.upload_urls: list[str] = []
        self.read_urls: list[str] = []
        self.deleted: list[str] = []

    def put(self, path: str, data: bytes, content_type: str = "image/jpeg") -> None:
        """What the client's direct upload would have done."""
        self.objects[path] = (data, content_type)

    async def create_upload_credential(
        self,
        *,
        path: str,
        expires_in_seconds: int,
        max_bytes: int,
        content_type: str | None = None,
    ) -> tuple[str, dict[str, str], datetime]:
        url = f"https://storage.test/upload/{path}?max={max_bytes}"
        self.upload_urls.append(url)
        fields = {"key": path, "policy": "fake", "x-amz-signature": "fake"}
        if content_type:
            fields["Content-Type"] = content_type
        return url, fields, datetime.now(UTC) + timedelta(seconds=expires_in_seconds)

    async def create_read_url(self, *, path: str, expires_in_seconds: int) -> tuple[str, datetime]:
        url = f"https://storage.test/read/{path}"
        self.read_urls.append(url)
        return url, datetime.now(UTC) + timedelta(seconds=expires_in_seconds)

    async def read_bytes(self, path: str) -> bytes | None:
        found = self.objects.get(path)
        return found[0] if found else None

    async def write_bytes(self, *, path: str, data: bytes, content_type: str) -> None:
        self.objects[path] = (data, content_type)

    async def delete(self, path: str) -> None:
        self.deleted.append(path)
        self.objects.pop(path, None)

    async def head(self, path: str) -> StoredObject | None:
        found = self.objects.get(path)
        if found is None:
            return None
        data, content_type = found
        return StoredObject(path=path, content_type=content_type, size_bytes=len(data))

    async def ensure_bucket(self) -> None:
        """A dict needs no provisioning."""
        return None
