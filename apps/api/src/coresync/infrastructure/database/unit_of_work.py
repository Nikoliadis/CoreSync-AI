"""SQLAlchemy Unit of Work."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coresync.infrastructure.database.repositories.identity import (
    SqlAlchemyAuthIdentityRepository,
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemySingleUseTokenRepository,
    SqlAlchemyUserDeviceRepository,
    SqlAlchemyUserRepository,
)
from coresync.infrastructure.database.repositories.profile import (
    SqlAlchemyGoalRepository,
    SqlAlchemyNutritionTargetRepository,
    SqlAlchemyProfileRepository,
    SqlAlchemyUserSettingsRepository,
)
from coresync.infrastructure.database.repositories.progress import (
    SqlAlchemyWeightLogRepository,
)


class SqlAlchemyUnitOfWork:
    """Owns one session and one transaction for the lifetime of a use case.

    Rollback is the default on the way out: an exception must never leave a partially
    applied change behind, and relying on the caller to remember is how that happens.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self._committed = False

        self.users = SqlAlchemyUserRepository(self._session)
        self.auth_identities = SqlAlchemyAuthIdentityRepository(self._session)
        self.refresh_tokens = SqlAlchemyRefreshTokenRepository(self._session)
        self.single_use_tokens = SqlAlchemySingleUseTokenRepository(self._session)
        self.devices = SqlAlchemyUserDeviceRepository(self._session)
        self.profiles = SqlAlchemyProfileRepository(self._session)
        self.goals = SqlAlchemyGoalRepository(self._session)
        self.targets = SqlAlchemyNutritionTargetRepository(self._session)
        self.settings = SqlAlchemyUserSettingsRepository(self._session)
        self.weights = SqlAlchemyWeightLogRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        try:
            if exc_type is not None or not self._committed:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()


class TestUnitOfWork(SqlAlchemyUnitOfWork):
    """Unit of Work bound to an externally managed session.

    Integration tests run every case inside an outer transaction that is rolled back
    afterwards, so ``commit`` must flush without ending that transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._committed = False
        self._bind_repositories()

    def _bind_repositories(self) -> None:
        assert self._session is not None
        self.users = SqlAlchemyUserRepository(self._session)
        self.auth_identities = SqlAlchemyAuthIdentityRepository(self._session)
        self.refresh_tokens = SqlAlchemyRefreshTokenRepository(self._session)
        self.single_use_tokens = SqlAlchemySingleUseTokenRepository(self._session)
        self.devices = SqlAlchemyUserDeviceRepository(self._session)
        self.profiles = SqlAlchemyProfileRepository(self._session)
        self.goals = SqlAlchemyGoalRepository(self._session)
        self.targets = SqlAlchemyNutritionTargetRepository(self._session)
        self.settings = SqlAlchemyUserSettingsRepository(self._session)
        self.weights = SqlAlchemyWeightLogRepository(self._session)

    async def __aenter__(self) -> TestUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None and self._session is not None:
            await self._session.rollback()

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.flush()
        self._committed = True
