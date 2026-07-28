"""/v1/auth — registration, sign-in, tokens, verification, password and OAuth."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from coresync.application.identity.auth import (
    AuthenticateCommand,
    AuthenticateUserUseCase,
    ListSessionsUseCase,
    LogoutAllUseCase,
    LogoutCommand,
    LogoutUseCase,
    RefreshCommand,
    RegisterUserCommand,
    RegisterUserUseCase,
    RequestContext,
    RotateRefreshTokenUseCase,
)
from coresync.application.identity.oauth import (
    LinkOAuthProviderUseCase,
    LinkProviderCommand,
    OAuthSignInCommand,
    OAuthSignInUseCase,
    UnlinkOAuthProviderUseCase,
)
from coresync.application.identity.verification import (
    ChangePasswordCommand,
    ChangePasswordUseCase,
    RequestPasswordResetUseCase,
    ResendVerificationUseCase,
    ResetPasswordCommand,
    ResetPasswordUseCase,
    VerifyEmailCommand,
    VerifyEmailUseCase,
)
from coresync.core.config import Settings
from coresync.core.errors import InvalidTokenError, RateLimitedError
from coresync.domain.identity.entities import AuthProvider
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.auth import (
    AuthenticatedUserResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    OAuthLinkRequest,
    OAuthSignInRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    TokenResponse,
    VerifyEmailRequest,
)
from coresync.presentation.schemas.common import ErrorResponse, MessageResponse

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "coresync_refresh"
# Path-scoped so the cookie is only ever sent to the one endpoint that needs it. Combined
# with SameSite=Lax this leaves CSRF almost no surface.
REFRESH_COOKIE_PATH = "/v1/auth"

_ERRORS = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


# ------------------------------------------------------------------- helpers
def _context(request: Request) -> RequestContext:
    forwarded = request.headers.get("X-Forwarded-For")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    return RequestContext(ip=ip, user_agent=request.headers.get("User-Agent"))


def _is_web_client(request: Request) -> bool:
    return request.headers.get("X-Client-Version", "").lower().startswith("web/")


def _apply_tokens(
    request: Request, response: Response, result, settings: Settings
) -> TokenResponse:
    """Deliver the refresh token by the safest route available to this client.

    Browsers get an httpOnly cookie — unreadable by JavaScript, so an XSS bug cannot
    exfiltrate it. Native clients get it in the body and store it in the Keychain or
    Keystore, which is the equivalent protection there.
    """
    web = _is_web_client(request)
    if web:
        response.set_cookie(
            key=REFRESH_COOKIE,
            value=result.tokens.refresh_token,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            path=REFRESH_COOKIE_PATH,
            max_age=settings.refresh_token_ttl_days * 86_400,
        )
    return TokenResponse(
        access_token=result.tokens.access_token,
        expires_in=result.tokens.expires_in_seconds,
        refresh_token=None if web else result.tokens.refresh_token,
        user=AuthenticatedUserResponse(**vars(result.user)),
        is_new_user=result.is_new_user,
        requires_onboarding=result.requires_onboarding,
    )


def _read_refresh_token(request: Request, body_token: str | None) -> str:
    token = body_token or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise InvalidTokenError("no refresh token supplied")
    return token


async def _throttle(container: deps.AppContainer, key: str, *, limit: int, minutes: int) -> None:
    allowed, reset_in = await container.rate_limiter.hit(
        key, limit=limit, window=timedelta(minutes=minutes)
    )
    if not allowed:
        raise RateLimitedError(reset_in)


# -------------------------------------------------------------- registration
@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageResponse,
    responses=_ERRORS,
    summary="Create an account",
    description=(
        "Always returns the same response whether or not the address is already "
        "registered. If it is, the owner receives a notification email instead — "
        "revealing which addresses have accounts would be a user-enumeration oracle."
    ),
)
async def register(
    request: Request,
    body: RegisterRequest,
    container: deps.Container,
    use_case: Annotated[RegisterUserUseCase, Depends(deps.register_user_use_case)],
) -> MessageResponse:
    await _throttle(container, f"register:{_context(request).ip}", limit=5, minutes=60)
    await use_case.execute(
        RegisterUserCommand(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            timezone=body.timezone,
            accepted_terms=body.accepted_terms,
        )
    )
    return MessageResponse(message="Check your email to verify your account.")


# --------------------------------------------------------------------- login
@router.post("/login", response_model=TokenResponse, responses=_ERRORS, summary="Sign in")
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    container: deps.Container,
    settings: deps.SettingsDep,
    use_case: Annotated[AuthenticateUserUseCase, Depends(deps.authenticate_use_case)],
) -> TokenResponse:
    ctx = _context(request)
    # Keyed on IP *and* email: neither a single address nor a single source can be
    # hammered, and a shared corporate IP does not lock out everyone behind it.
    await _throttle(container, f"login:{ctx.ip}:{body.email}", limit=5, minutes=15)

    result = await use_case.execute(
        AuthenticateCommand(email=body.email, password=body.password, context=ctx)
    )
    return _apply_tokens(request, response, result, settings)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses=_ERRORS,
    summary="Rotate the refresh token",
    description=(
        "Issues a new token pair and revokes the presented token. Replaying an "
        "already-rotated token revokes the entire rotation chain and returns "
        "`token_reuse_detected`."
    ),
)
async def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest,
    settings: deps.SettingsDep,
    use_case: Annotated[RotateRefreshTokenUseCase, Depends(deps.refresh_use_case)],
) -> TokenResponse:
    token = _read_refresh_token(request, body.refresh_token)
    result = await use_case.execute(RefreshCommand(refresh_token=token, context=_context(request)))
    return _apply_tokens(request, response, result, settings)


@router.post("/logout", response_model=MessageResponse, summary="Sign out of this device")
async def logout(
    request: Request,
    response: Response,
    body: LogoutRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LogoutUseCase, Depends(deps.logout_use_case)],
) -> MessageResponse:
    await use_case.execute(
        LogoutCommand(
            refresh_token=body.refresh_token or request.cookies.get(REFRESH_COOKIE),
            access_token_jti=getattr(request.state, "access_token_jti", None),
            user_id=user.id,
        )
    )
    # An httpOnly cookie cannot be removed by the client, so the server must clear it.
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return MessageResponse(message="Signed out.")


@router.post("/logout-all", response_model=MessageResponse, summary="Sign out everywhere")
async def logout_all(
    response: Response,
    user: deps.CurrentUser,
    use_case: Annotated[LogoutAllUseCase, Depends(deps.logout_all_use_case)],
) -> MessageResponse:
    count = await use_case.execute(user.id)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return MessageResponse(message=f"Signed out of {count} session(s).")


# -------------------------------------------------------------- verification
@router.post(
    "/verify-email",
    response_model=TokenResponse,
    responses=_ERRORS,
    summary="Verify an email address",
)
async def verify_email(
    request: Request,
    response: Response,
    body: VerifyEmailRequest,
    settings: deps.SettingsDep,
    use_case: Annotated[VerifyEmailUseCase, Depends(deps.verify_email_use_case)],
) -> TokenResponse:
    result = await use_case.execute(VerifyEmailCommand(token=body.token, context=_context(request)))
    return _apply_tokens(request, response, result, settings)


@router.post(
    "/verify-email/resend",
    response_model=MessageResponse,
    summary="Resend the verification email",
)
async def resend_verification(
    user: deps.CurrentUser,
    container: deps.Container,
    use_case: Annotated[ResendVerificationUseCase, Depends(deps.resend_verification_use_case)],
) -> MessageResponse:
    await _throttle(container, f"resend-verify:{user.id}", limit=3, minutes=60)
    await use_case.execute(user.id)
    return MessageResponse(message="Verification email sent.")


# ------------------------------------------------------------------ password
@router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=MessageResponse,
    summary="Request a password reset",
    description=(
        "Always returns 202, whether or not the address has an account. Any difference "
        "in status, body or latency would reveal which addresses are registered."
    ),
)
async def forgot_password(
    body: ForgotPasswordRequest,
    container: deps.Container,
    use_case: Annotated[RequestPasswordResetUseCase, Depends(deps.request_password_reset_use_case)],
) -> MessageResponse:
    await _throttle(container, f"forgot:{body.email}", limit=3, minutes=60)
    await use_case.execute(body.email)
    return MessageResponse(message="If that address has an account, a reset link is on its way.")


@router.post(
    "/password/reset",
    response_model=MessageResponse,
    responses=_ERRORS,
    summary="Reset a password with a token",
)
async def reset_password(
    body: ResetPasswordRequest,
    use_case: Annotated[ResetPasswordUseCase, Depends(deps.reset_password_use_case)],
) -> MessageResponse:
    await use_case.execute(ResetPasswordCommand(token=body.token, new_password=body.new_password))
    return MessageResponse(message="Password updated. Please sign in again.")


@router.post(
    "/password/change",
    response_model=MessageResponse,
    responses=_ERRORS,
    summary="Change a password while signed in",
)
async def change_password(
    response: Response,
    body: ChangePasswordRequest,
    user: deps.CurrentUser,
    use_case: Annotated[ChangePasswordUseCase, Depends(deps.change_password_use_case)],
) -> MessageResponse:
    await use_case.execute(
        ChangePasswordCommand(
            user_id=user.id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    )
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return MessageResponse(message="Password changed. All sessions were signed out.")


# --------------------------------------------------------------------- OAuth
@router.post(
    "/oauth/{provider}",
    response_model=TokenResponse,
    responses=_ERRORS,
    summary="Sign in with Google or Apple",
)
async def oauth_sign_in(
    provider: AuthProvider,
    request: Request,
    response: Response,
    body: OAuthSignInRequest,
    settings: deps.SettingsDep,
    use_case: Annotated[OAuthSignInUseCase, Depends(deps.oauth_sign_in_use_case)],
) -> TokenResponse:
    result = await use_case.execute(
        OAuthSignInCommand(
            provider=provider,
            id_token=body.id_token,
            nonce=body.nonce,
            context=_context(request),
            display_name_hint=body.display_name,
        )
    )
    return _apply_tokens(request, response, result, settings)


@router.post(
    "/oauth/{provider}/link",
    response_model=MessageResponse,
    responses=_ERRORS,
    summary="Link a provider to the signed-in account",
)
async def link_provider(
    provider: AuthProvider,
    body: OAuthLinkRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LinkOAuthProviderUseCase, Depends(deps.link_provider_use_case)],
) -> MessageResponse:
    await use_case.execute(
        LinkProviderCommand(
            user_id=user.id, provider=provider, id_token=body.id_token, nonce=body.nonce
        )
    )
    return MessageResponse(message=f"{provider.value.title()} account linked.")


@router.delete(
    "/oauth/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
    summary="Unlink a provider",
    description="Rejected with 409 if it would leave the account with no way to sign in.",
)
async def unlink_provider(
    provider: AuthProvider,
    user: deps.CurrentUser,
    use_case: Annotated[UnlinkOAuthProviderUseCase, Depends(deps.unlink_provider_use_case)],
) -> None:
    await use_case.execute(user.id, provider)


# ------------------------------------------------------------------ sessions
@router.get("/sessions", response_model=list[SessionResponse], summary="List active sessions")
async def list_sessions(
    request: Request,
    user: deps.CurrentUser,
    use_case: Annotated[ListSessionsUseCase, Depends(deps.list_sessions_use_case)],
) -> list[SessionResponse]:
    sessions = await use_case.execute(user.id, current_token=request.cookies.get(REFRESH_COOKIE))
    return [SessionResponse(**s) for s in sessions]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one session",
)
async def revoke_session(
    session_id: UUID,
    user: deps.CurrentUser,
    container: deps.Container,
) -> None:
    async with container.unit_of_work() as uow:
        tokens = await uow.refresh_tokens.list_active_for_user(user.id, container.clock.now())
        # Ownership is established by listing only this user's tokens — a session id
        # belonging to someone else simply is not in the list.
        target = next((t for t in tokens if t.id == session_id), None)
        if target is not None:
            target.revoke(container.clock.now(), "revoked_by_user")
            await uow.refresh_tokens.update(target)
        await uow.commit()
