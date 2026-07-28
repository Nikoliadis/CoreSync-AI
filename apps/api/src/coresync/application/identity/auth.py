"""Registration, sign-in, refresh rotation and sign-out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from coresync.application.common.dto import (
    AuthenticatedUser,
    SignInResult,
    TokenPair,
)
from coresync.application.common.ports import (
    BreachedPasswordChecker,
    EmailSender,
    TokenRevocationStore,
)
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock
from coresync.core.config import Settings
from coresync.core.errors import (
    AccountInactiveError,
    AccountLockedError,
    BreachedPasswordError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
    TokenReuseDetectedError,
)
from coresync.core.logging import get_logger
from coresync.core.security import (
    JwtService,
    PasswordHasherService,
    generate_opaque_token,
    hash_token,
)
from coresync.domain.identity.entities import RefreshToken, User
from coresync.domain.identity.policies import EmailPolicy, PasswordPolicy
from coresync.domain.profile.entities import Profile

logger = get_logger(__name__)


# --------------------------------------------------------------------------------
# Shared token issuance
# --------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RequestContext:
    ip: str | None = None
    user_agent: str | None = None
    device_id: UUID | None = None


class TokenIssuer:
    """Issues an access + refresh pair and records the refresh token."""

    def __init__(self, jwt: JwtService, settings: Settings, clock: Clock) -> None:
        self._jwt = jwt
        self._refresh_ttl = timedelta(days=settings.refresh_token_ttl_days)
        self._access_ttl_seconds = settings.access_token_ttl_minutes * 60
        self._clock = clock

    async def issue(
        self,
        uow: UnitOfWork,
        user: User,
        *,
        tier: str = "free",
        context: RequestContext | None = None,
    ) -> TokenPair:
        access_token, _ = self._jwt.issue_access_token(
            user_id=user.id,
            role=user.role.value,
            tier=tier,
            email_verified=user.is_email_verified,
        )
        raw_refresh = generate_opaque_token()
        token = RefreshToken.issue(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            ttl=self._refresh_ttl,
            now=self._clock.now(),
            device_id=context.device_id if context else None,
            ip=context.ip if context else None,
            user_agent=context.user_agent if context else None,
        )
        await uow.refresh_tokens.add(token)
        return TokenPair(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in_seconds=self._access_ttl_seconds,
        )


def _to_authenticated_user(user: User, tier: str = "free") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        role=user.role.value,
        tier=tier,
        status=user.status.value,
        email_verified=user.is_email_verified,
        timezone=user.timezone,
    )


# --------------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RegisterUserCommand:
    email: str
    password: str
    display_name: str
    timezone: str = "UTC"
    accepted_terms: bool = False


class RegisterUserUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        hasher: PasswordHasherService,
        password_policy: PasswordPolicy,
        breach_checker: BreachedPasswordChecker,
        email_sender: EmailSender,
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._policy = password_policy
        self._breach_checker = breach_checker
        self._email = email_sender
        self._settings = settings
        self._clock = clock

    async def execute(self, cmd: RegisterUserCommand) -> None:
        """Create an account and send a verification email.

        Returns nothing on purpose. The endpoint answers identically whether or not the
        address was already registered — anything else is a user-enumeration oracle,
        and "is this person a CoreSync user" is health-adjacent information.
        """
        email = EmailPolicy.normalise(cmd.email)
        self._policy.validate(cmd.password, email=email)

        if await self._breach_checker.is_breached(cmd.password):
            # Raised before the existence check, so the timing of this branch does not
            # depend on whether the account exists.
            raise BreachedPasswordError

        now = self._clock.now()

        async with self._uow:
            existing = await self._uow.users.get_by_email(email)
            if existing is not None:
                logger.info("registration_attempt_existing_email", email=email)
                await self._email.send_account_exists_notice(
                    to=email, sign_in_url=f"{self._settings.web_base_url}/login"
                )
                return

            user = User.register(
                email=email,
                password_hash=self._hasher.hash(cmd.password),
                timezone=cmd.timezone,
                now=now,
            )
            await self._uow.users.add(user)
            await self._uow.profiles.add(
                Profile.create(user_id=user.id, display_name=cmd.display_name)
            )
            await self._uow.settings.upsert(user.id, {})

            raw_token = generate_opaque_token()
            from coresync.domain.identity.entities import SingleUseToken, TokenPurpose

            await self._uow.single_use_tokens.add(
                SingleUseToken.create(
                    user_id=user.id,
                    purpose=TokenPurpose.EMAIL_VERIFICATION,
                    token_hash=hash_token(raw_token),
                    ttl=timedelta(hours=self._settings.email_verification_ttl_hours),
                    now=now,
                )
            )
            await self._uow.commit()

        # Sent after commit: an email promising a link that no longer exists because the
        # transaction rolled back is worse than a slightly delayed email.
        await self._email.send_verification(
            to=email,
            name=cmd.display_name,
            verify_url=f"{self._settings.web_base_url}/verify?token={raw_token}",
        )
        logger.info("user_registered", user_id=str(user.id))


# --------------------------------------------------------------------------------
# Sign-in
# --------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AuthenticateCommand:
    email: str
    password: str
    context: RequestContext


class AuthenticateUserUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        hasher: PasswordHasherService,
        token_issuer: TokenIssuer,
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._token_issuer = token_issuer
        self._settings = settings
        self._clock = clock

    async def execute(self, cmd: AuthenticateCommand) -> SignInResult:
        email = EmailPolicy.normalise(cmd.email)
        now = self._clock.now()

        async with self._uow:
            user = await self._uow.users.get_by_email(email)

            # Verify unconditionally. For an unknown address the hasher checks against a
            # dummy hash, so a wrong email and a wrong password cost the same time.
            password_ok = self._hasher.verify(cmd.password, user.password_hash if user else None)

            if user is None or not user.can_authenticate:
                raise InvalidCredentialsError

            if user.is_locked_at(now):
                raise AccountLockedError(user.lock_seconds_remaining(now))

            if not password_ok:
                user.record_failed_login(
                    now,
                    max_attempts=self._settings.max_failed_logins,
                    lockout=timedelta(minutes=self._settings.account_lockout_minutes),
                )
                await self._uow.users.update(user)
                await self._uow.commit()
                logger.warning("login_failed", user_id=str(user.id), email=email)
                raise InvalidCredentialsError

            if user.status.value == "suspended":
                raise AccountInactiveError

            # Transparent hash upgrade when the stored parameters are now too weak.
            if user.password_hash and self._hasher.needs_rehash(user.password_hash):
                user.change_password(self._hasher.hash(cmd.password))

            user.record_successful_login(now)
            await self._uow.users.update(user)

            tokens = await self._token_issuer.issue(self._uow, user, context=cmd.context)
            profile = await self._uow.profiles.get(user.id)
            await self._uow.commit()

        logger.info("login_succeeded", user_id=str(user.id))
        return SignInResult(
            tokens=tokens,
            user=_to_authenticated_user(user),
            requires_onboarding=profile is None or not profile.is_onboarded,
        )


# --------------------------------------------------------------------------------
# Refresh rotation
# --------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RefreshCommand:
    refresh_token: str
    context: RequestContext


class RotateRefreshTokenUseCase:
    """Rotate a refresh token, detecting replay of an already-rotated one.

    Rotation without reuse detection is close to pointless: a stolen token would simply
    become the attacker's permanent credential. With it, the first use of a superseded
    token — by either party — kills the whole family.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        jwt: JwtService,
        token_issuer: TokenIssuer,
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._jwt = jwt
        self._token_issuer = token_issuer
        self._settings = settings
        self._clock = clock

    async def execute(self, cmd: RefreshCommand) -> SignInResult:
        now = self._clock.now()
        token_hash = hash_token(cmd.refresh_token)

        async with self._uow:
            stored = await self._uow.refresh_tokens.get_by_hash(token_hash)
            if stored is None:
                raise InvalidTokenError

            if stored.is_revoked:
                revoked_count = await self._uow.refresh_tokens.revoke_family(
                    stored.id, now, "reuse_detected"
                )
                await self._uow.commit()
                logger.error(
                    "refresh_token_reuse_detected",
                    user_id=str(stored.user_id),
                    revoked_count=revoked_count,
                )
                raise TokenReuseDetectedError

            if stored.is_expired_at(now):
                raise TokenExpiredError

            user = await self._uow.users.get_by_id(stored.user_id)
            if user is None or not user.can_authenticate:
                raise AccountInactiveError

            tokens = await self._token_issuer.issue(self._uow, user, context=cmd.context)

            successor_hash = hash_token(tokens.refresh_token)
            successor = await self._uow.refresh_tokens.get_by_hash(successor_hash)
            if successor is not None:
                stored.rotate_to(successor, now)
                await self._uow.refresh_tokens.update(stored)

            await self._uow.commit()

        return SignInResult(tokens=tokens, user=_to_authenticated_user(user))


# --------------------------------------------------------------------------------
# Sign-out
# --------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LogoutCommand:
    refresh_token: str | None
    access_token_jti: UUID | None
    user_id: UUID


class LogoutUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        revocation_store: TokenRevocationStore,
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._revocation = revocation_store
        self._settings = settings
        self._clock = clock

    async def execute(self, cmd: LogoutCommand) -> None:
        now = self._clock.now()
        async with self._uow:
            if cmd.refresh_token:
                stored = await self._uow.refresh_tokens.get_by_hash(hash_token(cmd.refresh_token))
                # Ownership check: a token belonging to someone else is not revocable here.
                if stored is not None and stored.user_id == cmd.user_id:
                    stored.revoke(now, "logout")
                    await self._uow.refresh_tokens.update(stored)
            await self._uow.commit()

        # The access token stays cryptographically valid until it expires, so it is
        # blocklisted for the remainder of its lifetime.
        if cmd.access_token_jti is not None:
            await self._revocation.revoke(
                cmd.access_token_jti,
                ttl=timedelta(minutes=self._settings.access_token_ttl_minutes),
            )


class LogoutAllUseCase:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, user_id: UUID) -> int:
        async with self._uow:
            count = await self._uow.refresh_tokens.revoke_all_for_user(
                user_id, self._clock.now(), "logout_all"
            )
            await self._uow.commit()
        logger.info("logout_all", user_id=str(user_id), revoked_count=count)
        return count


class ListSessionsUseCase:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, user_id: UUID, *, current_token: str | None = None) -> list[dict]:
        current_hash = hash_token(current_token) if current_token else None
        async with self._uow:
            tokens = await self._uow.refresh_tokens.list_active_for_user(user_id, self._clock.now())
        return [
            {
                "id": t.id,
                "ip": t.created_ip,
                "user_agent": t.user_agent,
                "created_at": t.created_at,
                "expires_at": t.expires_at,
                "is_current": current_hash is not None and t.token_hash == current_hash,
            }
            for t in tokens
        ]
