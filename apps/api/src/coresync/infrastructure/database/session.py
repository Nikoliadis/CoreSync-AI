"""Async engine and session management.

Read-replica routing lives here too: read-only, latency-tolerant work (reports, admin
analytics, AI context assembly) can be pointed at the replica, while anything a client
reads immediately after writing stays on the primary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from coresync.core.config import Settings


def create_engine(settings: Settings, *, replica: bool = False) -> AsyncEngine:
    url = settings.database_replica_url if replica else settings.database_url
    if url is None:
        raise ValueError("replica engine requested but database_replica_url is not set")

    return create_async_engine(
        str(url),
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        # Recycle below the typical cloud idle-connection timeout so the pool never
        # hands out a socket the network has already dropped.
        pool_recycle=1800,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "application_name": f"coresync-api{'-replica' if replica else ''}",
                # An unbounded query is an outage waiting for traffic.
                "statement_timeout": str(settings.database_statement_timeout_ms),
                "idle_in_transaction_session_timeout": "30000",
            },
            # Prepared-statement caching breaks behind PgBouncer in transaction mode,
            # which is where this ends up at stage 2 of the scaling plan.
            "statement_cache_size": 0,
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,  # entities stay usable after commit
        autoflush=False,  # flushes are explicit, so query counts stay predictable
    )


class Database:
    """Owns the engines for the process lifetime."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = create_engine(settings)
        self._session_factory = create_session_factory(self._engine)

        self._replica_engine: AsyncEngine | None = None
        self._replica_session_factory: async_sessionmaker[AsyncSession] | None = None
        if settings.database_replica_url is not None:
            self._replica_engine = create_engine(settings, replica=True)
            self._replica_session_factory = create_session_factory(self._replica_engine)

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @property
    def replica_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Falls back to the primary when no replica is configured.

        Making this transparent means application code can express intent ("this read
        is replica-safe") in every environment, including local development.
        """
        return self._replica_session_factory or self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self._engine.dispose()
        if self._replica_engine is not None:
            await self._replica_engine.dispose()
