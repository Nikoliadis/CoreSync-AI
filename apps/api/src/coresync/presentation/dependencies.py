"""Dependency wiring.

The object graph is composed once at startup into ``AppContainer`` (so Celery workers
and the CLI can build the same graph without importing FastAPI), while request-scoped
pieces — the unit of work, the current user — come through ``Depends``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

from coresync.application.common.dto import AuthenticatedUser
from coresync.application.common.ports import (
    BreachedPasswordChecker,
    EmailSender,
    OidcVerifier,
    RateLimiter,
    TokenRevocationStore,
)
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.identity.auth import (
    AuthenticateUserUseCase,
    ListSessionsUseCase,
    LogoutAllUseCase,
    LogoutUseCase,
    RegisterUserUseCase,
    RotateRefreshTokenUseCase,
    TokenIssuer,
)
from coresync.application.identity.oauth import (
    LinkOAuthProviderUseCase,
    OAuthSignInUseCase,
    UnlinkOAuthProviderUseCase,
)
from coresync.application.identity.verification import (
    ChangePasswordUseCase,
    RequestPasswordResetUseCase,
    ResendVerificationUseCase,
    ResetPasswordUseCase,
    VerifyEmailUseCase,
)
from coresync.application.profile.use_cases import (
    CompleteOnboardingUseCase,
    GetMeUseCase,
    ListTargetHistoryUseCase,
    RecalculateTargetsUseCase,
    ScheduleAccountDeletionUseCase,
    SetGoalUseCase,
    SetTargetsManuallyUseCase,
    UpdateProfileUseCase,
    UpdateSettingsUseCase,
)
from coresync.core.clock import Clock, SystemClock
from coresync.core.config import Settings, get_settings
from coresync.core.errors import (
    AccountInactiveError,
    EmailNotVerifiedError,
    ForbiddenError,
    UnauthenticatedError,
)
from coresync.core.logging import user_id_var
from coresync.core.security import JwtService, PasswordHasherService
from coresync.domain.identity.entities import AuthProvider
from coresync.domain.identity.policies import PasswordPolicy
from coresync.domain.profile.services import TdeeCalculator
from coresync.infrastructure.database.session import Database
from coresync.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

# auto_error=False so a missing header raises our own error shape, not FastAPI's.
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AppContainer:
    """Singletons for the process lifetime, built once in the app lifespan."""

    settings: Settings
    database: Database
    redis: Redis
    clock: Clock
    jwt: JwtService
    hasher: PasswordHasherService
    password_policy: PasswordPolicy
    tdee_calculator: TdeeCalculator
    email_sender: EmailSender
    revocation_store: TokenRevocationStore
    rate_limiter: RateLimiter
    breach_checker: BreachedPasswordChecker
    oidc_verifiers: dict[AuthProvider, OidcVerifier]
    token_issuer: TokenIssuer

    def unit_of_work(self) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(self.database.session_factory)


# ------------------------------------------------------------------ accessors
def get_container(request: Request) -> AppContainer:
    return request.app.state.container  # type: ignore[no-any-return]


Container = Annotated[AppContainer, Depends(get_container)]


def get_uow(container: Container) -> UnitOfWork:
    return container.unit_of_work()


Uow = Annotated[UnitOfWork, Depends(get_uow)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ------------------------------------------------------------- authentication
async def get_current_user(
    request: Request,
    container: Container,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise UnauthenticatedError

    claims = container.jwt.decode_access_token(credentials.credentials)

    # The JWT is still cryptographically valid after a logout, so revocation is checked
    # here. Entries expire with the token, keeping the set small.
    if await container.revocation_store.is_revoked(claims.jti):
        raise UnauthenticatedError("token_revoked")

    async with container.unit_of_work() as uow:
        user = await uow.users.get_by_id(claims.subject)

    if user is None or not user.can_authenticate:
        raise AccountInactiveError

    user_id_var.set(str(user.id))
    request.state.access_token_jti = claims.jti

    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        role=user.role.value,
        tier=claims.tier,
        status=user.status.value,
        email_verified=user.is_email_verified,
        timezone=user.timezone,
    )


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


async def require_verified_email(user: CurrentUser) -> AuthenticatedUser:
    if not user.email_verified:
        raise EmailNotVerifiedError
    return user


VerifiedUser = Annotated[AuthenticatedUser, Depends(require_verified_email)]


def require_role(*roles: str):
    async def _dependency(user: CurrentUser) -> AuthenticatedUser:
        if user.role not in roles:
            raise ForbiddenError
        return user

    return _dependency


# ------------------------------------------------------------------ use cases
def register_user_use_case(c: Container, uow: Uow) -> RegisterUserUseCase:
    return RegisterUserUseCase(
        uow, c.hasher, c.password_policy, c.breach_checker, c.email_sender, c.settings, c.clock
    )


def authenticate_use_case(c: Container, uow: Uow) -> AuthenticateUserUseCase:
    return AuthenticateUserUseCase(uow, c.hasher, c.token_issuer, c.settings, c.clock)


def refresh_use_case(c: Container, uow: Uow) -> RotateRefreshTokenUseCase:
    return RotateRefreshTokenUseCase(uow, c.jwt, c.token_issuer, c.settings, c.clock)


def logout_use_case(c: Container, uow: Uow) -> LogoutUseCase:
    return LogoutUseCase(uow, c.revocation_store, c.settings, c.clock)


def logout_all_use_case(c: Container, uow: Uow) -> LogoutAllUseCase:
    return LogoutAllUseCase(uow, c.clock)


def list_sessions_use_case(c: Container, uow: Uow) -> ListSessionsUseCase:
    return ListSessionsUseCase(uow, c.clock)


def verify_email_use_case(c: Container, uow: Uow) -> VerifyEmailUseCase:
    return VerifyEmailUseCase(uow, c.token_issuer, c.clock)


def resend_verification_use_case(c: Container, uow: Uow) -> ResendVerificationUseCase:
    return ResendVerificationUseCase(uow, c.email_sender, c.settings, c.clock)


def request_password_reset_use_case(c: Container, uow: Uow) -> RequestPasswordResetUseCase:
    return RequestPasswordResetUseCase(uow, c.email_sender, c.settings, c.clock)


def reset_password_use_case(c: Container, uow: Uow) -> ResetPasswordUseCase:
    return ResetPasswordUseCase(
        uow, c.hasher, c.password_policy, c.breach_checker, c.email_sender, c.clock
    )


def change_password_use_case(c: Container, uow: Uow) -> ChangePasswordUseCase:
    return ChangePasswordUseCase(
        uow, c.hasher, c.password_policy, c.breach_checker, c.email_sender, c.clock
    )


def oauth_sign_in_use_case(c: Container, uow: Uow) -> OAuthSignInUseCase:
    return OAuthSignInUseCase(uow, c.oidc_verifiers, c.token_issuer, c.clock)


def link_provider_use_case(c: Container, uow: Uow) -> LinkOAuthProviderUseCase:
    return LinkOAuthProviderUseCase(uow, c.oidc_verifiers, c.clock)


def unlink_provider_use_case(uow: Uow) -> UnlinkOAuthProviderUseCase:
    return UnlinkOAuthProviderUseCase(uow)


def get_me_use_case(c: Container, uow: Uow) -> GetMeUseCase:
    return GetMeUseCase(uow, c.clock)


def update_profile_use_case(c: Container, uow: Uow) -> UpdateProfileUseCase:
    return UpdateProfileUseCase(uow, c.clock)


def update_settings_use_case(uow: Uow) -> UpdateSettingsUseCase:
    return UpdateSettingsUseCase(uow)


def onboarding_use_case(c: Container, uow: Uow) -> CompleteOnboardingUseCase:
    return CompleteOnboardingUseCase(uow, c.tdee_calculator, c.clock)


def set_goal_use_case(c: Container, uow: Uow) -> SetGoalUseCase:
    return SetGoalUseCase(uow, c.tdee_calculator, c.clock)


def recalculate_targets_use_case(c: Container, uow: Uow) -> RecalculateTargetsUseCase:
    return RecalculateTargetsUseCase(uow, c.tdee_calculator, c.clock)


def set_targets_use_case(c: Container, uow: Uow) -> SetTargetsManuallyUseCase:
    return SetTargetsManuallyUseCase(uow, c.tdee_calculator, c.clock)


def target_history_use_case(uow: Uow) -> ListTargetHistoryUseCase:
    return ListTargetHistoryUseCase(uow)


def delete_account_use_case(c: Container, uow: Uow) -> ScheduleAccountDeletionUseCase:
    return ScheduleAccountDeletionUseCase(uow, c.clock)


def build_container(settings: Settings) -> AppContainer:
    """Compose the object graph. Called from the app lifespan and from tests."""
    from coresync.infrastructure.cache.redis_client import (
        RedisRateLimiter,
        RedisTokenRevocationStore,
        create_redis,
    )
    from coresync.infrastructure.external.oidc import AppleOidcVerifier, GoogleOidcVerifier
    from coresync.infrastructure.notifications.email import (
        ConsoleEmailSender,
        SmtpEmailSender,
    )
    from coresync.infrastructure.security.breach_checker import (
        HibpBreachChecker,
        NoopBreachChecker,
    )

    clock = SystemClock()
    jwt_service = JwtService(settings)
    redis = create_redis(settings)

    return AppContainer(
        settings=settings,
        database=Database(settings),
        redis=redis,
        clock=clock,
        jwt=jwt_service,
        hasher=PasswordHasherService(settings),
        password_policy=PasswordPolicy(),
        tdee_calculator=TdeeCalculator(),
        email_sender=SmtpEmailSender(settings)
        if settings.environment != "test"
        else ConsoleEmailSender(),
        revocation_store=RedisTokenRevocationStore(redis),
        rate_limiter=RedisRateLimiter(redis),
        breach_checker=HibpBreachChecker()
        if settings.is_production
        else NoopBreachChecker({"password123456", "coresync2026"}),
        oidc_verifiers={
            AuthProvider.GOOGLE: GoogleOidcVerifier(settings),
            AuthProvider.APPLE: AppleOidcVerifier(settings),
        },
        token_issuer=TokenIssuer(jwt_service, settings, clock),
    )
