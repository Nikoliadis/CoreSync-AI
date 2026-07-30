"""Identity policies — the rules, separated from the entities that obey them."""

from __future__ import annotations

import re
from dataclasses import dataclass

from coresync.core.errors import WeakPasswordError

# Sequences that appear in essentially every breached-password list. Cheap to check,
# and they catch the passwords users actually pick when left to themselves.
_COMMON_PATTERNS = (
    "password",
    "qwerty",
    "12345",
    "letmein",
    "welcome",
    "admin",
    "iloveyou",
    "coresync",
    "fitness",
    "workout",
)

_SEQUENTIAL = re.compile(r"(abcdef|bcdefg|cdefgh|123456|234567|345678|456789)", re.IGNORECASE)
_REPEATED = re.compile(r"(.)\1{3,}")


@dataclass(frozen=True, slots=True)
class PasswordStrength:
    score: int  # 0-4, loosely aligned with zxcvbn
    is_acceptable: bool
    reason: str | None = None


class PasswordPolicy:
    """Length and unpredictability, not composition rules.

    Deliberately no "must contain a symbol and an uppercase letter". Those rules are
    well documented (NIST SP 800-63B) to push users toward `Password1!` — predictable
    and weaker than a long passphrase. Length plus a blocklist does more, and annoys
    people less.
    """

    MIN_LENGTH = 10
    MAX_LENGTH = 128
    MIN_SCORE = 2

    def validate(self, password: str, *, email: str | None = None) -> None:
        strength = self.evaluate(password, email=email)
        if not strength.is_acceptable:
            raise WeakPasswordError(
                strength.reason or "Password is too weak",
                details=[{"field": "password", "code": "weak", "message": strength.reason}],
            )

    def evaluate(self, password: str, *, email: str | None = None) -> PasswordStrength:
        if len(password) < self.MIN_LENGTH:
            return PasswordStrength(0, False, f"Use at least {self.MIN_LENGTH} characters.")
        if len(password) > self.MAX_LENGTH:
            # Long inputs are rejected rather than truncated: Argon2 on a 10 MB string
            # is a free denial-of-service.
            return PasswordStrength(0, False, "Password is too long.")

        lowered = password.lower()

        if email:
            local_part = email.split("@")[0].lower()
            if len(local_part) >= 4 and local_part in lowered:
                return PasswordStrength(0, False, "Do not use your email address.")

        if any(pattern in lowered for pattern in _COMMON_PATTERNS):
            return PasswordStrength(0, False, "That is too common a password.")
        if _SEQUENTIAL.search(password):
            return PasswordStrength(1, False, "Avoid sequences like 123456.")
        if _REPEATED.search(password):
            return PasswordStrength(1, False, "Avoid repeated characters.")

        score = self._score(password)
        if score < self.MIN_SCORE:
            return PasswordStrength(score, False, "Choose a longer or less predictable password.")
        return PasswordStrength(score, True)

    @staticmethod
    def _score(password: str) -> int:
        """Rough entropy proxy: length dominates, variety contributes a little.

        A stand-in for zxcvbn, which is a heavy dependency for the value it adds here.
        Swap it in if the eval data ever says this is letting weak passwords through.
        """
        score = 0
        if len(password) >= 12:
            score += 1
        if len(password) >= 16:
            score += 1
        variety = sum(
            (
                any(c.islower() for c in password),
                any(c.isupper() for c in password),
                any(c.isdigit() for c in password),
                any(not c.isalnum() for c in password),
            )
        )
        if variety >= 2:
            score += 1
        if variety >= 3:
            score += 1
        return min(score, 4)


class EmailPolicy:
    """Normalisation only. Format validation belongs to Pydantic at the edge."""

    @staticmethod
    def normalise(email: str) -> str:
        return email.strip().lower()
