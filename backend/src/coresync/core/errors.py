"""Application error hierarchy.

Errors carry a stable machine-readable ``code``. Clients branch on the code, never on
the message — messages are localised and rewritten freely, codes are a contract.

Nothing below raises ``HTTPException``. Use cases raise *meaning*; the presentation
layer maps meaning to status codes (see ``presentation/middleware/error_handler.py``).
That separation is what keeps the application layer free of FastAPI.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base for every deliberate error in the system."""

    code: str = "internal_error"
    user_message: str = "Something went wrong. Please try again."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
        **context: Any,
    ) -> None:
        super().__init__(message or self.user_message)
        self.details = details or []
        self.context = context

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, context={self.context!r})"


# ---------------------------------------------------------------------- generic
class ValidationError(AppError):
    code = "validation_error"
    user_message = "The request could not be validated."


class NotFoundError(AppError):
    code = "not_found"
    user_message = "Not found."

    def __init__(self, resource: str, identifier: Any = None) -> None:
        super().__init__(f"{resource} not found", resource=resource, identifier=str(identifier))


class ConflictError(AppError):
    code = "conflict"
    user_message = "That conflicts with the current state."


class ForbiddenError(AppError):
    code = "forbidden"
    user_message = "You do not have permission to do that."


class RateLimitedError(AppError):
    code = "rate_limited"
    user_message = "Too many requests. Please slow down."

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(retry_after_seconds=retry_after_seconds)
        self.retry_after_seconds = retry_after_seconds


class QuotaExceededError(AppError):
    code = "quota_exceeded"
    user_message = "You have reached your plan's limit for this feature."


class UpstreamUnavailableError(AppError):
    code = "upstream_unavailable"
    user_message = "A service we depend on is unavailable. Please try again shortly."


# ---------------------------------------------------------------- authentication
class UnauthenticatedError(AppError):
    code = "unauthenticated"
    user_message = "Please sign in."


class InvalidCredentialsError(UnauthenticatedError):
    code = "invalid_credentials"
    # Deliberately identical whether the email is unknown or the password is wrong.
    # A distinguishable message is a user-enumeration oracle.
    user_message = "Incorrect email or password."


class AccountLockedError(UnauthenticatedError):
    code = "account_locked"
    user_message = "Too many failed attempts. Try again shortly."

    def __init__(self, unlock_in_seconds: int) -> None:
        super().__init__(unlock_in_seconds=unlock_in_seconds)
        self.unlock_in_seconds = unlock_in_seconds


class AccountInactiveError(UnauthenticatedError):
    code = "account_inactive"
    user_message = "This account is not active."


class TokenExpiredError(UnauthenticatedError):
    code = "token_expired"
    user_message = "Your session has expired. Please sign in again."


class InvalidTokenError(UnauthenticatedError):
    code = "invalid_token"
    user_message = "That link or token is not valid."


class TokenReuseDetectedError(UnauthenticatedError):
    code = "token_reuse_detected"
    user_message = "Your session was ended for security reasons. Please sign in again."


class EmailNotVerifiedError(ForbiddenError):
    code = "email_not_verified"
    user_message = "Please verify your email address first."


class ProviderEmailUnverifiedError(ForbiddenError):
    """The identity provider did not assert that it verified the address.

    Refused unconditionally, whether or not a local account exists. Two reasons: creating
    an account from it would record an unverified address as verified, and linking to an
    existing one is an account-takeover path — register an unverified account with
    someone's address, then sign in through the provider and inherit theirs. Behaving
    identically in both cases also keeps this from being a user-enumeration oracle.
    """

    code = "provider_email_unverified"
    user_message = (
        "Your provider has not verified that email address. Sign in with your password, "
        "then link the account from settings."
    )


class UnverifiedAccountExistsError(ConflictError):
    """A local account already holds this address, and its email was never verified.

    docs/06 permits auto-linking only when *both* sides assert a verified address, and
    this is the case it does not cover: the provider verified the address, but the
    account sitting on it did not. Linking anyway is the pre-hijacking attack — register
    an account with somebody's address, leave it unverified, prepare it, and wait for
    them to sign in through the provider and inherit what you left there.

    So it is refused. Unlike most refusals this one names the reason, and can: reaching
    it requires a provider-signed token for that exact address, so the caller has already
    proved they control it. Telling somebody an account exists on their own email leaks
    nothing they could not confirm by trying to register.
    """

    code = "unverified_account_exists"
    user_message = (
        "An account with this email already exists but was never verified. "
        "Sign in with your password to finish setting it up, then link your provider "
        "from settings."
    )


class WeakPasswordError(ValidationError):
    code = "weak_password"
    user_message = "Choose a stronger password."


class BreachedPasswordError(ValidationError):
    code = "breached_password"
    user_message = "That password has appeared in a known data breach. Choose another."


class EmailAlreadyRegisteredError(ConflictError):
    """Raised internally only.

    Never surfaced to an unauthenticated caller — the registration endpoint returns the
    same response whether or not the address exists. See ``RegisterUserUseCase``.
    """

    code = "email_already_registered"


class LastAuthMethodError(ConflictError):
    code = "last_auth_method"
    user_message = "You cannot remove your only way to sign in."
