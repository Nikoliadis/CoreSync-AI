"""Identity entities and policies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from coresync.core.errors import WeakPasswordError
from coresync.domain.identity.entities import (
    RefreshToken,
    SingleUseToken,
    TokenPurpose,
    User,
    UserStatus,
)
from coresync.domain.identity.policies import EmailPolicy, PasswordPolicy

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class TestUserRegistration:
    def test_email_password_signup_starts_pending(self) -> None:
        user = User.register(
            email="Alex@Example.COM", password_hash="hash", timezone="Europe/Athens", now=NOW
        )
        assert user.status is UserStatus.PENDING
        assert user.is_email_verified is False
        assert user.email == "alex@example.com", "email is normalised on the way in"

    def test_social_signup_is_active_immediately(self) -> None:
        """The provider has already proven ownership — there is nothing left to verify."""
        user = User.register(
            email="a@b.com", password_hash=None, timezone="UTC", now=NOW, email_verified=True
        )
        assert user.status is UserStatus.ACTIVE
        assert user.is_email_verified is True
        assert user.password_hash is None

    def test_pending_users_can_still_authenticate(self) -> None:
        # Blocking the entire product behind a verification click is a large, well
        # documented drop in activation. Only abusable surfaces are gated.
        user = User.register(email="a@b.com", password_hash="h", timezone="UTC", now=NOW)
        assert user.can_authenticate is True


class TestAccountLockout:
    def test_locks_after_the_configured_number_of_failures(self) -> None:
        user = User.register(email="a@b.com", password_hash="h", timezone="UTC", now=NOW)
        for _ in range(9):
            user.record_failed_login(NOW, max_attempts=10, lockout=timedelta(minutes=15))
        assert user.is_locked_at(NOW) is False

        user.record_failed_login(NOW, max_attempts=10, lockout=timedelta(minutes=15))
        assert user.is_locked_at(NOW) is True
        assert user.lock_seconds_remaining(NOW) == 900

    def test_lock_expires_rather_than_being_permanent(self) -> None:
        """A permanent lock on failed attempts is itself a denial-of-service vector."""
        user = User.register(email="a@b.com", password_hash="h", timezone="UTC", now=NOW)
        for _ in range(10):
            user.record_failed_login(NOW, max_attempts=10, lockout=timedelta(minutes=15))
        assert user.is_locked_at(NOW + timedelta(minutes=16)) is False

    def test_successful_login_clears_the_counter(self) -> None:
        user = User.register(email="a@b.com", password_hash="h", timezone="UTC", now=NOW)
        user.record_failed_login(NOW, max_attempts=10, lockout=timedelta(minutes=15))
        user.record_successful_login(NOW)
        assert user.failed_login_count == 0
        assert user.locked_until is None
        assert user.last_login_at == NOW


class TestRefreshTokenRotation:
    def _token(self, **kw) -> RefreshToken:
        return RefreshToken.issue(
            user_id=User.register(email="a@b.com", password_hash="h", timezone="UTC", now=NOW).id,
            token_hash=kw.get("token_hash", b"\x01" * 32),
            ttl=kw.get("ttl", timedelta(days=30)),
            now=NOW,
        )

    def test_a_fresh_token_is_usable(self) -> None:
        assert self._token().is_usable_at(NOW) is True

    def test_an_expired_token_is_not_usable(self) -> None:
        token = self._token(ttl=timedelta(days=30))
        assert token.is_usable_at(NOW + timedelta(days=31)) is False

    def test_rotation_revokes_the_predecessor_and_links_the_chain(self) -> None:
        old = self._token(token_hash=b"\x01" * 32)
        new = self._token(token_hash=b"\x02" * 32)
        old.rotate_to(new, NOW)

        assert old.is_revoked is True
        assert old.revoked_reason == "rotated"
        assert old.replaced_by == new.id
        assert old.is_usable_at(NOW) is False, "a rotated token must never be reusable"
        assert new.is_usable_at(NOW) is True

    def test_revoking_twice_keeps_the_original_reason(self) -> None:
        # The first reason is the true one; a later blanket revocation must not
        # overwrite "reuse_detected" with "logout" in the audit trail.
        token = self._token()
        token.revoke(NOW, "reuse_detected")
        token.revoke(NOW + timedelta(minutes=5), "logout")
        assert token.revoked_reason == "reuse_detected"
        assert token.revoked_at == NOW


class TestSingleUseToken:
    def test_is_usable_until_consumed(self) -> None:
        token = SingleUseToken.create(
            user_id=User.register(email="a@b.com", password_hash="h", timezone="UTC", now=NOW).id,
            purpose=TokenPurpose.PASSWORD_RESET,
            token_hash=b"\x03" * 32,
            ttl=timedelta(minutes=30),
            now=NOW,
        )
        assert token.is_usable_at(NOW) is True

        token.consume(NOW)
        assert token.is_usable_at(NOW) is False, "reset links are strictly single-use"

    def test_expires(self) -> None:
        token = SingleUseToken.create(
            user_id=User.register(email="a@b.com", password_hash="h", timezone="UTC", now=NOW).id,
            purpose=TokenPurpose.EMAIL_VERIFICATION,
            token_hash=b"\x04" * 32,
            ttl=timedelta(hours=24),
            now=NOW,
        )
        assert token.is_usable_at(NOW + timedelta(hours=25)) is False


class TestPasswordPolicy:
    @pytest.mark.parametrize(
        "password,reason",
        [
            ("short1!", "too short"),
            ("password123456", "common pattern"),
            ("qwertyuiopas", "common pattern"),
            ("aaaaBBBB1111", "repeated characters"),
            ("abcdefghijkl", "sequential"),
        ],
    )
    def test_rejects_predictable_passwords(self, password: str, reason: str) -> None:
        with pytest.raises(WeakPasswordError):
            PasswordPolicy().validate(password)

    def test_rejects_a_password_containing_the_email_local_part(self) -> None:
        with pytest.raises(WeakPasswordError):
            PasswordPolicy().validate("nikoliadis-2026", email="nikoliadis@example.com")

    @pytest.mark.parametrize(
        "password",
        [
            "correct horse battery staple",  # long passphrase, no symbols needed
            "Tr0ub4dor&3xample",
            "my-very-long-gym-phrase-2026",
        ],
    )
    def test_accepts_long_unpredictable_passwords(self, password: str) -> None:
        PasswordPolicy().validate(password)  # must not raise

    def test_rejects_absurdly_long_input(self) -> None:
        # Argon2 over a multi-megabyte string is a free denial-of-service.
        with pytest.raises(WeakPasswordError):
            PasswordPolicy().validate("a" * 5000)

    def test_no_composition_rules_are_enforced(self) -> None:
        """A long all-lowercase passphrase is stronger than `Password1!` and is allowed.

        Composition rules measurably produce worse passwords (NIST SP 800-63B).
        """
        PasswordPolicy().validate("thequickbrownfoxjumps")


class TestEmailPolicy:
    @pytest.mark.parametrize(
        "raw,expected",
        [("  Alex@Example.com ", "alex@example.com"), ("A@B.CO", "a@b.co")],
    )
    def test_normalises(self, raw: str, expected: str) -> None:
        assert EmailPolicy.normalise(raw) == expected
