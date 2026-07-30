"""Request and response schemas for /v1/auth."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from coresync.presentation.schemas.common import ApiModel


# ------------------------------------------------------------------- requests
class RegisterRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    timezone: str = Field(default="UTC", max_length=64)
    accepted_terms: bool = Field(
        description="Must be true. Consent is captured explicitly, never pre-ticked."
    )

    @field_validator("accepted_terms")
    @classmethod
    def _must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the terms to create an account.")
        return v


class LoginRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(ApiModel):
    # Optional: web clients send the token in an httpOnly cookie instead.
    refresh_token: str | None = None


class LogoutRequest(ApiModel):
    refresh_token: str | None = None


class VerifyEmailRequest(ApiModel):
    token: str = Field(min_length=16, max_length=256)


class ForgotPasswordRequest(ApiModel):
    email: EmailStr


class ResetPasswordRequest(ApiModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=10, max_length=128)


class ChangePasswordRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class OAuthSignInRequest(ApiModel):
    id_token: str = Field(min_length=16, max_length=8192)
    nonce: str | None = Field(default=None, max_length=256)
    display_name: str | None = Field(
        default=None,
        max_length=80,
        description=(
            "Apple returns the user's name only on the first authorisation. "
            "Forward it here so it can be persisted at that one opportunity."
        ),
    )


class OAuthLinkRequest(ApiModel):
    id_token: str = Field(min_length=16, max_length=8192)
    nonce: str | None = Field(default=None, max_length=256)


# ------------------------------------------------------------------ responses
class AuthenticatedUserResponse(ApiModel):
    id: UUID
    email: str
    role: str
    tier: str
    status: str
    email_verified: bool
    timezone: str


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    # Omitted for web clients, where it is delivered as an httpOnly cookie instead.
    refresh_token: str | None = None
    user: AuthenticatedUserResponse
    is_new_user: bool = False
    requires_onboarding: bool = False


class SessionResponse(ApiModel):
    id: UUID
    ip: str | None
    user_agent: str | None
    created_at: datetime | None
    expires_at: datetime
    is_current: bool
