"""Sign in with Google and Apple."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from coresync.application.common.dto import SignInResult
from coresync.application.common.ports import OidcVerifier
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.identity.auth import (
    RequestContext,
    TokenIssuer,
    _to_authenticated_user,
)
from coresync.core.clock import Clock
from coresync.core.errors import (
    AccountInactiveError,
    ConflictError,
    InvalidTokenError,
    LastAuthMethodError,
    NotFoundError,
)
from coresync.core.logging import get_logger
from coresync.domain.identity.entities import AuthIdentity, AuthProvider, User
from coresync.domain.profile.entities import Profile

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OAuthSignInCommand:
    provider: AuthProvider
    id_token: str
    nonce: str | None
    context: RequestContext
    # Apple returns the user's name only on the very first authorisation, and never
    # again. The client forwards it here so it can be persisted at that one chance.
    display_name_hint: str | None = None


class OAuthSignInUseCase:
    def __init__(
        self,
        uow: UnitOfWork,
        verifiers: dict[AuthProvider, OidcVerifier],
        token_issuer: TokenIssuer,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._verifiers = verifiers
        self._token_issuer = token_issuer
        self._clock = clock

    async def execute(self, cmd: OAuthSignInCommand) -> SignInResult:
        verifier = self._verifiers.get(cmd.provider)
        if verifier is None:
            raise InvalidTokenError(f"provider {cmd.provider} is not configured")

        # Verified server-side against the provider's JWKS. A client-supplied
        # "it's valid, trust me" would let anyone sign in as anyone.
        identity = await verifier.verify(cmd.id_token, nonce=cmd.nonce)
        now = self._clock.now()
        is_new_user = False

        async with self._uow:
            existing_identity = await self._uow.auth_identities.get_by_provider_subject(
                cmd.provider, identity.subject
            )

            if existing_identity is not None:
                user = await self._uow.users.get_by_id(existing_identity.user_id)
                if user is None or not user.can_authenticate:
                    raise AccountInactiveError
            else:
                user = await self._maybe_find_linkable_user(identity.email, identity.email_verified)
                if user is not None:
                    # Auto-link only when both sides assert a verified address. Linking
                    # on an unverified email is a straightforward account-takeover path:
                    # register an unverified account with someone's address, then sign
                    # in through the provider and inherit theirs.
                    await self._uow.auth_identities.add(
                        AuthIdentity.link(
                            user_id=user.id,
                            provider=cmd.provider,
                            subject=identity.subject,
                            email=identity.email,
                            now=now,
                        )
                    )
                    logger.info(
                        "oauth_linked_existing_user",
                        user_id=str(user.id),
                        provider=cmd.provider.value,
                    )
                else:
                    if identity.email is None:
                        raise InvalidTokenError("provider did not supply an email address")
                    user = User.register(
                        email=identity.email,
                        password_hash=None,  # social-only account
                        timezone="UTC",
                        now=now,
                        email_verified=True,
                    )
                    await self._uow.users.add(user)
                    await self._uow.profiles.add(
                        Profile.create(
                            user_id=user.id,
                            display_name=(
                                identity.name
                                or cmd.display_name_hint
                                or identity.email.split("@")[0]
                            ),
                        )
                    )
                    await self._uow.settings.upsert(user.id, {})
                    await self._uow.auth_identities.add(
                        AuthIdentity.link(
                            user_id=user.id,
                            provider=cmd.provider,
                            subject=identity.subject,
                            email=identity.email,
                            now=now,
                        )
                    )
                    is_new_user = True

            user.record_successful_login(now)
            await self._uow.users.update(user)
            tokens = await self._token_issuer.issue(self._uow, user, context=cmd.context)
            profile = await self._uow.profiles.get(user.id)
            await self._uow.commit()

        logger.info(
            "oauth_sign_in", user_id=str(user.id), provider=cmd.provider.value, new=is_new_user
        )
        return SignInResult(
            tokens=tokens,
            user=_to_authenticated_user(user),
            is_new_user=is_new_user,
            requires_onboarding=profile is None or not profile.is_onboarded,
        )

    async def _maybe_find_linkable_user(
        self, email: str | None, provider_verified: bool
    ) -> User | None:
        if email is None or not provider_verified:
            return None
        user = await self._uow.users.get_by_email(email)
        if user is None or not user.is_email_verified:
            return None
        return user


@dataclass(frozen=True, slots=True)
class LinkProviderCommand:
    user_id: UUID
    provider: AuthProvider
    id_token: str
    nonce: str | None = None


class LinkOAuthProviderUseCase:
    def __init__(
        self, uow: UnitOfWork, verifiers: dict[AuthProvider, OidcVerifier], clock: Clock
    ) -> None:
        self._uow = uow
        self._verifiers = verifiers
        self._clock = clock

    async def execute(self, cmd: LinkProviderCommand) -> None:
        verifier = self._verifiers.get(cmd.provider)
        if verifier is None:
            raise InvalidTokenError(f"provider {cmd.provider} is not configured")
        identity = await verifier.verify(cmd.id_token, nonce=cmd.nonce)

        async with self._uow:
            existing = await self._uow.auth_identities.get_by_provider_subject(
                cmd.provider, identity.subject
            )
            if existing is not None:
                if existing.user_id == cmd.user_id:
                    return  # already linked; idempotent
                raise ConflictError("That account is already linked to another user.")

            await self._uow.auth_identities.add(
                AuthIdentity.link(
                    user_id=cmd.user_id,
                    provider=cmd.provider,
                    subject=identity.subject,
                    email=identity.email,
                    now=self._clock.now(),
                )
            )
            await self._uow.commit()


class UnlinkOAuthProviderUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, provider: AuthProvider) -> None:
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)

            identities = await self._uow.auth_identities.list_for_user(user_id)
            target = next((i for i in identities if i.provider is provider), None)
            if target is None:
                raise NotFoundError("auth_identity", provider.value)

            # Unlinking the last sign-in method would lock the user out permanently.
            has_password = user.password_hash is not None
            if not has_password and len(identities) <= 1:
                raise LastAuthMethodError

            await self._uow.auth_identities.delete(target.id, user_id)
            await self._uow.commit()
