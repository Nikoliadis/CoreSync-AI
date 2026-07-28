"""Password hashing, token generation and JWT handling.

Every cryptographic decision in the system is made here, once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type as Argon2Type

from coresync.core.config import Settings
from coresync.core.errors import InvalidTokenError, TokenExpiredError
from coresync.core.ids import uuid7

TokenType = Literal["access", "refresh"]


# --------------------------------------------------------------------- passwords
class PasswordHasherService:
    """Argon2id. Parameters come from settings so they can be raised as hardware improves."""

    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
            hash_len=32,
            salt_len=16,
            type=Argon2Type.ID,
        )
        # Verified against when the email is unknown, so that a login attempt costs the
        # same whether or not the account exists. Without this, response timing tells an
        # attacker which addresses are registered.
        self._dummy_hash = self._hasher.hash("timing-attack-mitigation-dummy-password")

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str | None) -> bool:
        if password_hash is None:
            # Social-only account, or unknown email. Burn the same CPU anyway.
            self._safe_verify(self._dummy_hash, password)
            return False
        return self._safe_verify(password_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        """True when the stored hash used weaker parameters than we now require.

        Called on successful login so hashes are transparently upgraded over time.
        """
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True

    def _safe_verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False


# ------------------------------------------------------------------ opaque tokens
def generate_opaque_token() -> str:
    """A 256-bit URL-safe random token for refresh, verification and reset flows."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """Hash an opaque token for storage.

    SHA-256 rather than Argon2 on purpose: these tokens are 256 bits of entropy, so
    they are not brute-forceable and do not need a slow KDF — and refresh happens on
    a latency-sensitive path where a 100 ms hash would be felt.
    """
    return hashlib.sha256(token.encode("utf-8")).digest()


def tokens_equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


# --------------------------------------------------------------------------- JWT
@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    subject: UUID
    jti: UUID
    role: str
    tier: str
    email_verified: bool
    expires_at: datetime


class JwtService:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret_key
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._access_ttl = timedelta(minutes=settings.access_token_ttl_minutes)

    def issue_access_token(
        self,
        *,
        user_id: UUID,
        role: str,
        tier: str,
        email_verified: bool,
    ) -> tuple[str, AccessTokenClaims]:
        now = datetime.now(UTC)
        expires_at = now + self._access_ttl
        jti = uuid7()
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "jti": str(jti),
            "typ": "access",
            "role": role,
            "tier": tier,
            # Short claim names keep the token small; it travels on every request.
            "ev": email_verified,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "iss": self._issuer,
            "aud": self._audience,
        }
        # No email, no name, no PII: tokens end up in logs and crash reports.
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        claims = AccessTokenClaims(
            subject=user_id,
            jti=jti,
            role=role,
            tier=tier,
            email_verified=email_verified,
            expires_at=expires_at,
        )
        return token, claims

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                # An explicit algorithm list. Accepting the token's own `alg` header is
                # how algorithm-confusion and `alg=none` attacks work.
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError from exc
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError from exc

        if payload.get("typ") != "access":
            # A refresh token presented as a bearer credential must not be accepted.
            raise InvalidTokenError("wrong token type")

        return AccessTokenClaims(
            subject=UUID(payload["sub"]),
            jti=UUID(payload["jti"]),
            role=payload.get("role", "user"),
            tier=payload.get("tier", "free"),
            email_verified=bool(payload.get("ev", False)),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
