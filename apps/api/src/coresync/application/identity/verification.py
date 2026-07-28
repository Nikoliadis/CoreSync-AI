"""Email verification and password reset."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from coresync.application.common.dto import SignInResult
from coresync.application.common.ports import BreachedPasswordChecker, EmailSender
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.identity.auth import (
    RequestContext,
    TokenIssuer,
    _to_authenticated_user,
)
from coresync.core.clock import Clock
from coresync.core.config import Settings
from coresync.core.errors import (
    BreachedPasswordError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
)
from coresync.core.logging import get_logger
from coresync.core.security import (
    PasswordHasherService,
    generate_opaque_token,
    hash_token,
)
from coresync.domain.identity.entities import SingleUseToken, TokenPurpose
from coresync.domain.identity.policies import EmailPolicy, PasswordPolicy

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class VerifyEmailCommand:
    token: str
    context: RequestContext


class VerifyEmailUseCase:
    def __init__(self, uow: UnitOfWork, token_issuer: TokenIssuer, clock: Clock) -> None:
        self._uow = uow
        self._token_issuer = token_issuer
        self._clock = clock

    async def execute(self, cmd: VerifyEmailCommand) -> SignInResult:
        """Consume a verification token and sign the user in.

        Signing in here removes a step: the user clicked a link from their inbox, which
        is proof enough of control for a fresh session.
        """
        now = self._clock.now()
        async with self._uow:
            token = await self._uow.single_use_tokens.get_by_hash(
                hash_token(cmd.token), TokenPurpose.EMAIL_VERIFICATION
            )
            if token is None or not token.is_usable_at(now):
                raise InvalidTokenError

            user = await self._uow.users.get_by_id(token.user_id)
            if user is None:
                raise InvalidTokenError

            token.consume(now)
            await self._uow.single_use_tokens.update(token)

            user.verify_email(now)
            await self._uow.users.update(user)

            tokens = await self._token_issuer.issue(self._uow, user, context=cmd.context)
            profile = await self._uow.profiles.get(user.id)
            await self._uow.commit()

        logger.info("email_verified", user_id=str(user.id))
        return SignInResult(
            tokens=tokens,
            user=_to_authenticated_user(user),
            requires_onboarding=profile is None or not profile.is_onboarded,
        )


class ResendVerificationUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        email_sender: EmailSender,
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._email = email_sender
        self._settings = settings
        self._clock = clock

    async def execute(self, user_id: UUID) -> None:
        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            if user.is_email_verified:
                return  # nothing to do; not an error

            profile = await self._uow.profiles.get(user_id)
            # Invalidate the previous link, so only the newest one works.
            await self._uow.single_use_tokens.invalidate_outstanding(
                user_id, TokenPurpose.EMAIL_VERIFICATION, now
            )
            raw_token = generate_opaque_token()
            await self._uow.single_use_tokens.add(
                SingleUseToken.create(
                    user_id=user_id,
                    purpose=TokenPurpose.EMAIL_VERIFICATION,
                    token_hash=hash_token(raw_token),
                    ttl=timedelta(hours=self._settings.email_verification_ttl_hours),
                    now=now,
                )
            )
            await self._uow.commit()

        await self._email.send_verification(
            to=user.email,
            name=profile.display_name if profile else "there",
            verify_url=f"{self._settings.web_base_url}/verify?token={raw_token}",
        )


class RequestPasswordResetUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        email_sender: EmailSender,
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._email = email_sender
        self._settings = settings
        self._clock = clock

    async def execute(self, email: str) -> None:
        """Always completes successfully, whether or not the address exists.

        The endpoint returns 202 either way. Any difference in response, status or
        latency tells an attacker which addresses are registered.
        """
        normalised = EmailPolicy.normalise(email)
        now = self._clock.now()

        async with self._uow:
            user = await self._uow.users.get_by_email(normalised)
            if user is None:
                logger.info("password_reset_unknown_email", email=normalised)
                return
            if user.password_hash is None:
                # Social-only account: there is no password to reset. Tell the owner how
                # to sign in rather than silently doing nothing.
                await self._email.send_account_exists_notice(
                    to=normalised, sign_in_url=f"{self._settings.web_base_url}/login"
                )
                return

            profile = await self._uow.profiles.get(user.id)
            await self._uow.single_use_tokens.invalidate_outstanding(
                user.id, TokenPurpose.PASSWORD_RESET, now
            )
            raw_token = generate_opaque_token()
            await self._uow.single_use_tokens.add(
                SingleUseToken.create(
                    user_id=user.id,
                    purpose=TokenPurpose.PASSWORD_RESET,
                    token_hash=hash_token(raw_token),
                    ttl=timedelta(minutes=self._settings.password_reset_ttl_minutes),
                    now=now,
                )
            )
            await self._uow.commit()

        await self._email.send_password_reset(
            to=normalised,
            name=profile.display_name if profile else "there",
            reset_url=f"{self._settings.web_base_url}/reset-password?token={raw_token}",
        )
        logger.info("password_reset_requested", user_id=str(user.id))


@dataclass(frozen=True, slots=True)
class ResetPasswordCommand:
    token: str
    new_password: str


class ResetPasswordUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        hasher: PasswordHasherService,
        policy: PasswordPolicy,
        breach_checker: BreachedPasswordChecker,
        email_sender: EmailSender,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._policy = policy
        self._breach_checker = breach_checker
        self._email = email_sender
        self._clock = clock

    async def execute(self, cmd: ResetPasswordCommand) -> None:
        now = self._clock.now()
        async with self._uow:
            token = await self._uow.single_use_tokens.get_by_hash(
                hash_token(cmd.token), TokenPurpose.PASSWORD_RESET
            )
            if token is None or not token.is_usable_at(now):
                raise InvalidTokenError

            user = await self._uow.users.get_by_id(token.user_id)
            if user is None:
                raise InvalidTokenError

            self._policy.validate(cmd.new_password, email=user.email)
            if await self._breach_checker.is_breached(cmd.new_password):
                raise BreachedPasswordError

            token.consume(now)
            await self._uow.single_use_tokens.update(token)

            user.change_password(self._hasher.hash(cmd.new_password))
            # A reset often happens *because* the account was compromised. Leaving the
            # attacker's session alive would make the whole flow theatre.
            user.verify_email(now)
            await self._uow.users.update(user)
            revoked = await self._uow.refresh_tokens.revoke_all_for_user(
                user.id, now, "password_reset"
            )
            await self._uow.commit()

        profile_name = user.email.split("@")[0]
        await self._email.send_password_changed(to=user.email, name=profile_name)
        logger.info("password_reset_completed", user_id=str(user.id), revoked_sessions=revoked)


@dataclass(frozen=True, slots=True)
class ChangePasswordCommand:
    user_id: UUID
    current_password: str
    new_password: str
    keep_current_session_token: str | None = None


class ChangePasswordUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        hasher: PasswordHasherService,
        policy: PasswordPolicy,
        breach_checker: BreachedPasswordChecker,
        email_sender: EmailSender,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._policy = policy
        self._breach_checker = breach_checker
        self._email = email_sender
        self._clock = clock

    async def execute(self, cmd: ChangePasswordCommand) -> None:
        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise NotFoundError("user", cmd.user_id)

            # Requiring the current password stops a stolen access token from being
            # upgraded into permanent account control.
            if not self._hasher.verify(cmd.current_password, user.password_hash):
                raise InvalidCredentialsError

            self._policy.validate(cmd.new_password, email=user.email)
            if await self._breach_checker.is_breached(cmd.new_password):
                raise BreachedPasswordError

            user.change_password(self._hasher.hash(cmd.new_password))
            await self._uow.users.update(user)
            await self._uow.refresh_tokens.revoke_all_for_user(user.id, now, "password_changed")
            await self._uow.commit()

        await self._email.send_password_changed(to=user.email, name=user.email.split("@")[0])
        logger.info("password_changed", user_id=str(user.id))
