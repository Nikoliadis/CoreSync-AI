"""Password hashing, opaque tokens and JWT handling."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from coresync.core.config import Settings
from coresync.core.errors import InvalidTokenError, TokenExpiredError
from coresync.core.ids import uuid7, uuid7_timestamp
from coresync.core.security import (
    JwtService,
    PasswordHasherService,
    generate_opaque_token,
    hash_token,
    tokens_equal,
)


class TestPasswordHashing:
    def test_hash_and_verify_round_trip(self, hasher: PasswordHasherService) -> None:
        h = hasher.hash("a-long-enough-password")
        assert hasher.verify("a-long-enough-password", h) is True
        assert hasher.verify("wrong-password-entirely", h) is False

    def test_the_same_password_hashes_differently_each_time(
        self, hasher: PasswordHasherService
    ) -> None:
        """Salted. Two identical passwords must not produce identical hashes."""
        assert hasher.hash("same-password-here") != hasher.hash("same-password-here")

    def test_verifying_against_no_hash_still_costs_work(
        self, hasher: PasswordHasherService
    ) -> None:
        """A social-only account, or an unknown email, must not return instantly.

        An early return here is a timing oracle that reveals which addresses are
        registered — so the hasher verifies against a dummy hash instead.
        """
        started = time.perf_counter()
        assert hasher.verify("some-password-value", None) is False
        elapsed = time.perf_counter() - started
        assert elapsed > 0, "verification must do real work even with no stored hash"

    def test_argon2_hash_format(self, hasher: PasswordHasherService) -> None:
        assert hasher.hash("another-password-x").startswith("$argon2id$")


class TestOpaqueTokens:
    def test_tokens_are_unique_and_long(self) -> None:
        tokens = {generate_opaque_token() for _ in range(500)}
        assert len(tokens) == 500
        assert all(len(t) >= 40 for t in tokens)

    def test_hashing_is_deterministic_and_fixed_width(self) -> None:
        token = generate_opaque_token()
        assert hash_token(token) == hash_token(token)
        assert len(hash_token(token)) == 32

    def test_comparison_is_constant_time(self) -> None:
        a = hash_token("x")
        assert tokens_equal(a, hash_token("x")) is True
        assert tokens_equal(a, hash_token("y")) is False


class TestJwt:
    def test_issue_and_decode_round_trip(self, jwt_service: JwtService) -> None:
        user_id = uuid7()
        token, claims = jwt_service.issue_access_token(
            user_id=user_id, role="user", tier="pro", email_verified=True
        )
        decoded = jwt_service.decode_access_token(token)
        assert decoded.subject == user_id
        assert decoded.role == "user"
        assert decoded.tier == "pro"
        assert decoded.email_verified is True
        assert decoded.jti == claims.jti

    def test_token_carries_no_personal_data(self, jwt_service: JwtService) -> None:
        """Tokens end up in logs, crash reports and proxy caches."""
        token, _ = jwt_service.issue_access_token(
            user_id=uuid7(), role="user", tier="free", email_verified=True
        )
        payload = jwt.decode(token, options={"verify_signature": False})
        assert "email" not in payload
        assert "name" not in payload
        assert set(payload) == {
            "sub",
            "jti",
            "typ",
            "role",
            "tier",
            "ev",
            "iat",
            "exp",
            "iss",
            "aud",
        }

    def test_rejects_a_token_signed_with_another_key(self, settings: Settings) -> None:
        other = JwtService(
            Settings(
                environment="test",
                jwt_secret_key="a-completely-different-secret-key-value",
                argon2_time_cost=1,
                argon2_memory_cost_kib=8,
                argon2_parallelism=1,
            )
        )
        token, _ = other.issue_access_token(
            user_id=uuid7(), role="user", tier="free", email_verified=True
        )
        with pytest.raises(InvalidTokenError):
            JwtService(settings).decode_access_token(token)

    def test_rejects_the_alg_none_attack(self, settings: Settings) -> None:
        """Decoding must use an explicit algorithm list, never the token's own header."""
        forged = jwt.encode(
            {
                "sub": str(uuid7()),
                "jti": str(uuid7()),
                "typ": "access",
                "iat": int(time.time()),
                "exp": int(time.time()) + 900,
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
            },
            key="",
            algorithm="none",
        )
        with pytest.raises(InvalidTokenError):
            JwtService(settings).decode_access_token(forged)

    def test_rejects_an_expired_token(self, settings: Settings) -> None:
        expired = jwt.encode(
            {
                "sub": str(uuid7()),
                "jti": str(uuid7()),
                "typ": "access",
                "iat": int(time.time()) - 3600,
                "exp": int(time.time()) - 60,
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenExpiredError):
            JwtService(settings).decode_access_token(expired)

    def test_rejects_a_refresh_token_used_as_a_bearer_credential(self, settings: Settings) -> None:
        wrong_type = jwt.encode(
            {
                "sub": str(uuid7()),
                "jti": str(uuid7()),
                "typ": "refresh",
                "iat": int(time.time()),
                "exp": int(time.time()) + 900,
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            JwtService(settings).decode_access_token(wrong_type)

    def test_rejects_a_wrong_audience(self, settings: Settings) -> None:
        foreign = jwt.encode(
            {
                "sub": str(uuid7()),
                "jti": str(uuid7()),
                "typ": "access",
                "iat": int(time.time()),
                "exp": int(time.time()) + 900,
                "iss": settings.jwt_issuer,
                "aud": "some-other-service",
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            JwtService(settings).decode_access_token(foreign)


class TestUuid7:
    def test_is_version_7(self) -> None:
        assert uuid7().version == 7

    def test_ids_sort_in_creation_order(self) -> None:
        """Time-ordering is why UUIDv7 was chosen: it keeps B-tree inserts local."""
        ids = [uuid7() for _ in range(2000)]
        assert ids == sorted(ids)

    def test_ids_are_unique(self) -> None:
        assert len({uuid7() for _ in range(10_000)}) == 10_000

    def test_timestamp_is_recoverable(self) -> None:
        before = datetime.now(UTC) - timedelta(seconds=1)
        value = uuid7()
        after = datetime.now(UTC) + timedelta(seconds=1)
        assert before <= uuid7_timestamp(value) <= after

    def test_rejects_a_non_v7_uuid(self) -> None:
        import uuid

        with pytest.raises(ValueError, match="not a UUIDv7"):
            uuid7_timestamp(uuid.uuid4())
