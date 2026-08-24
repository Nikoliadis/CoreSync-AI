"""SQLAlchemy implementations of the identity repository ports."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.identity.entities import (
    AuthIdentity,
    AuthProvider,
    RefreshToken,
    SingleUseToken,
    TokenPurpose,
    User,
    UserDevice,
    UserStatus,
)
from coresync.infrastructure.database.mappers import (
    AuthIdentityMapper,
    RefreshTokenMapper,
    SingleUseTokenMapper,
    UserDeviceMapper,
    UserMapper,
)
from coresync.infrastructure.database.models.identity import (
    AuthIdentityModel,
    RefreshTokenModel,
    SingleUseTokenModel,
    UserDeviceModel,
    UserModel,
)

# Not a hash of anything. Argon2 hashes start with `$argon2`, so a value that cannot
# parse as one can never verify against any password — which is the point. Named as a
# constant so the bandit rule can be silenced once, at the definition, with the reason.
ERASED_PASSWORD_HASH = "!erased"  # noqa: S105 — deliberately unparseable, never a secret

# Tables holding data personal to one user, cleared on erasure. Ordered so children go
# before parents where a foreign key would otherwise refuse.
#
# What is deliberately *absent* is as important as what is here: `daily_activity_summaries`,
# `daily_nutrition_summaries`, `user_streaks` and `user_achievements` are derived counts
# with nothing personal in them once the identity is scrubbed, and keeping them is what
# stops platform statistics rewriting themselves every time somebody leaves.
_PERSONAL_TABLES: tuple[str, ...] = (
    # AI: transcripts are the most sensitive thing in the system.
    "ai_tool_calls",
    "ai_messages",
    "ai_conversations",
    "ai_insights",
    "ai_usage_logs",
    # Body data.
    "progress_photos",
    "body_measurements",
    "weight_logs",
    "user_goals",
    # Nutrition.
    "diary_entries",
    "water_logs",
    "recipe_ingredients",
    "recipes",
    "nutrition_targets",
    "favorite_foods",
    # Training.
    "session_sets",
    "session_exercises",
    "workout_sessions",
    "routine_sets",
    "routine_exercises",
    "routines",
    "personal_records",
    "exercise_statistics",
    "user_favorite_exercises",
    # Identity and delivery.
    "notification_outbox",
    "notifications",
    "notification_preferences",
    "user_devices",
    "sync_operations",
    "single_use_tokens",
    "refresh_tokens",
    "auth_identities",
    "user_settings",
    "user_profiles",
)

# Child tables keyed by their parent rather than by user_id directly.
_CHILD_TABLES: dict[str, str] = {
    "ai_tool_calls": (
        "message_id IN (SELECT m.id FROM ai_messages m "
        "JOIN ai_conversations c ON c.id = m.conversation_id WHERE c.user_id = :uid)"
    ),
    "ai_messages": "conversation_id IN (SELECT id FROM ai_conversations WHERE user_id = :uid)",
    "recipe_ingredients": "recipe_id IN (SELECT id FROM recipes WHERE user_id = :uid)",
    "session_sets": (
        "session_exercise_id IN (SELECT se.id FROM session_exercises se "
        "JOIN workout_sessions s ON s.id = se.session_id WHERE s.user_id = :uid)"
    ),
    "session_exercises": "session_id IN (SELECT id FROM workout_sessions WHERE user_id = :uid)",
    "routine_sets": (
        "routine_exercise_id IN (SELECT re.id FROM routine_exercises re "
        "JOIN routines r ON r.id = re.routine_id WHERE r.user_id = :uid)"
    ),
    "routine_exercises": "routine_id IN (SELECT id FROM routines WHERE user_id = :uid)",
    "notification_outbox": "notification_id IN (SELECT id FROM notifications WHERE user_id = :uid)",
}


class _ErasureMixin:
    """Erasure, split out so the size of the table list does not bury the repository."""

    _session: AsyncSession

    async def list_due_for_erasure(self, *, cutoff: datetime, limit: int) -> list[UUID]:
        stmt = (
            select(UserModel.id)
            .where(
                UserModel.deleted_at.is_not(None),
                UserModel.deleted_at <= cutoff,
                # Already erased accounts must never be picked up again — that is what
                # makes the sweep free to re-run after a failure.
                UserModel.status != UserStatus.ERASED.value,
            )
            .order_by(UserModel.deleted_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def erase(self, user_id: UUID, *, at: datetime) -> None:
        current = (
            await self._session.execute(select(UserModel.status).where(UserModel.id == user_id))
        ).scalar_one_or_none()
        if current is None or current == UserStatus.ERASED.value:
            return

        for table in _PERSONAL_TABLES:
            predicate = _CHILD_TABLES.get(table, "user_id = :uid")

            # from a caller. The only value that varies is bound, not interpolated.
            await self._session.execute(
                text(f"DELETE FROM {table} WHERE {predicate}"),  # noqa: S608
                {"uid": user_id},
            )

        # The row survives, its identity does not. A unique, syntactically valid address
        # in a reserved TLD, so the uniqueness constraint holds and nothing can ever
        # deliver to it.
        await self._session.execute(
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(
                email=f"erased-{user_id}@invalid",
                password_hash=ERASED_PASSWORD_HASH,
                status=UserStatus.ERASED.value,
                deleted_at=at,
                # Clearing the verification timestamp along with the address: a
                # verified-at date that refers to an address nobody can name any more
                # is a fact about a person we just erased.
                email_verified_at=None,
                # Login bookkeeping is behavioural data about a real person, so it goes
                # with the rest of it.
                last_login_at=None,
                failed_login_count=0,
                locked_until=None,
            )
        )
        await self._session.flush()


class SqlAlchemyUserRepository(_ErasureMixin):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        if model is None or model.deleted_at is not None:
            return None
        return UserMapper.to_entity(model)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(UserModel).where(
            UserModel.email == email.strip().lower(),
            UserModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return UserMapper.to_entity(model) if model else None

    async def email_exists(self, email: str) -> bool:
        stmt = select(UserModel.id).where(
            UserModel.email == email.strip().lower(),
            UserModel.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def add(self, user: User) -> None:
        self._session.add(UserMapper.to_model(user))
        await self._session.flush()

    async def update(self, user: User) -> None:
        model = await self._session.get(UserModel, user.id)
        if model is None:
            raise ValueError(f"user {user.id} does not exist")
        UserMapper.apply(user, model)
        await self._session.flush()


class SqlAlchemyAuthIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_provider_subject(
        self, provider: AuthProvider, subject: str
    ) -> AuthIdentity | None:
        stmt = select(AuthIdentityModel).where(
            AuthIdentityModel.provider == provider.value,
            AuthIdentityModel.provider_subject == subject,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return AuthIdentityMapper.to_entity(model) if model else None

    async def list_for_user(self, user_id: UUID) -> list[AuthIdentity]:
        stmt = select(AuthIdentityModel).where(AuthIdentityModel.user_id == user_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [AuthIdentityMapper.to_entity(m) for m in rows]

    async def add(self, identity: AuthIdentity) -> None:
        self._session.add(AuthIdentityMapper.to_model(identity))
        await self._session.flush()

    async def delete(self, identity_id: UUID, user_id: UUID) -> None:
        stmt = select(AuthIdentityModel).where(
            AuthIdentityModel.id == identity_id,
            # Ownership is part of the predicate, not a check afterwards.
            AuthIdentityModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, token_hash: bytes) -> RefreshToken | None:
        stmt = select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return RefreshTokenMapper.to_entity(model) if model else None

    async def add(self, token: RefreshToken) -> None:
        self._session.add(RefreshTokenMapper.to_model(token))
        await self._session.flush()

    async def update(self, token: RefreshToken) -> None:
        model = await self._session.get(RefreshTokenModel, token.id)
        if model is None:
            raise ValueError(f"refresh token {token.id} does not exist")
        RefreshTokenMapper.apply(token, model)
        await self._session.flush()

    async def revoke_family(self, token_id: UUID, now: datetime, reason: str) -> int:
        """Revoke the entire rotation chain containing ``token_id``.

        Walks backwards to the root via ``replaced_by``, then forwards to the tip.
        Called when a rotated token is replayed: at that point we cannot tell whether
        the legitimate client or an attacker holds the copy, so every token in the
        family dies and the user re-authenticates.
        """
        root_id = await self._find_chain_root(token_id)
        chain_ids = await self._collect_chain(root_id)

        stmt = (
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.id.in_(chain_ids),
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount or 0

    async def revoke_all_for_user(self, user_id: UUID, now: datetime, reason: str) -> int:
        stmt = (
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount or 0

    async def list_active_for_user(self, user_id: UUID, now: datetime) -> list[RefreshToken]:
        stmt = (
            select(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
                RefreshTokenModel.expires_at > now,
            )
            .order_by(RefreshTokenModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [RefreshTokenMapper.to_entity(m) for m in rows]

    async def _find_chain_root(self, token_id: UUID) -> UUID:
        current = token_id
        # Bounded: a chain longer than this means something is very wrong, and an
        # unbounded loop over corrupt data would hang the request.
        for _ in range(200):
            stmt = select(RefreshTokenModel.id).where(RefreshTokenModel.replaced_by == current)
            predecessor = (await self._session.execute(stmt)).scalar_one_or_none()
            if predecessor is None:
                return current
            current = predecessor
        return current

    async def _collect_chain(self, root_id: UUID) -> list[UUID]:
        ids = [root_id]
        current: UUID | None = root_id
        for _ in range(200):
            stmt = select(RefreshTokenModel.replaced_by).where(RefreshTokenModel.id == current)
            successor = (await self._session.execute(stmt)).scalar_one_or_none()
            if successor is None:
                break
            ids.append(successor)
            current = successor
        return ids


class SqlAlchemySingleUseTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, token_hash: bytes, purpose: TokenPurpose) -> SingleUseToken | None:
        stmt = select(SingleUseTokenModel).where(
            SingleUseTokenModel.token_hash == token_hash,
            SingleUseTokenModel.purpose == purpose.value,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return SingleUseTokenMapper.to_entity(model) if model else None

    async def add(self, token: SingleUseToken) -> None:
        self._session.add(SingleUseTokenMapper.to_model(token))
        await self._session.flush()

    async def update(self, token: SingleUseToken) -> None:
        model = await self._session.get(SingleUseTokenModel, token.id)
        if model is None:
            raise ValueError(f"token {token.id} does not exist")
        model.used_at = token.used_at
        await self._session.flush()

    async def invalidate_outstanding(
        self, user_id: UUID, purpose: TokenPurpose, now: datetime
    ) -> None:
        stmt = (
            update(SingleUseTokenModel)
            .where(
                SingleUseTokenModel.user_id == user_id,
                SingleUseTokenModel.purpose == purpose.value,
                SingleUseTokenModel.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self._session.execute(stmt)
        await self._session.flush()


class SqlAlchemyUserDeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, device_id: UUID, user_id: UUID) -> UserDevice | None:
        stmt = select(UserDeviceModel).where(
            UserDeviceModel.id == device_id,
            UserDeviceModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return UserDeviceMapper.to_entity(model) if model else None

    async def list_for_user(self, user_id: UUID) -> list[UserDevice]:
        stmt = (
            select(UserDeviceModel)
            .where(UserDeviceModel.user_id == user_id)
            .order_by(UserDeviceModel.last_seen_at.desc().nullslast())
        )
        return [
            UserDeviceMapper.to_entity(m) for m in (await self._session.execute(stmt)).scalars()
        ]

    async def add(self, device: UserDevice) -> None:
        self._session.add(UserDeviceMapper.to_model(device))
        await self._session.flush()

    async def touch(self, device_id: UUID, now: datetime) -> None:
        stmt = (
            update(UserDeviceModel).where(UserDeviceModel.id == device_id).values(last_seen_at=now)
        )
        await self._session.execute(stmt)
