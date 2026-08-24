"""Hard erasure of accounts past their grace period.

This is the only code in the system that destroys user data on purpose, so the tests are
about what it must *not* do as much as what it must. Three properties carry the weight:

* nothing inside the grace period is touched, because that window is a promise;
* an erased account is never selected again, so a failed sweep is safe to re-run;
* personal data goes and anonymous aggregates stay, which is what keeps platform
  statistics honest instead of rewriting themselves every time somebody leaves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coresync.application.privacy.erasure import (
    GRACE_PERIOD_DAYS,
    EraseExpiredAccountsUseCase,
    erasure_deadline,
)
from coresync.core.clock import FrozenClock
from coresync.core.config import Settings
from coresync.infrastructure.database.session import Database
from coresync.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


async def _scalar(settings: Settings, sql: str, **params: object) -> object:
    engine = create_async_engine(str(settings.database_url))
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
    async with factory() as session:
        value = (await session.execute(text(sql), params)).scalar()
    await engine.dispose()
    return value


async def _execute(settings: Settings, sql: str, **params: object) -> None:
    engine = create_async_engine(str(settings.database_url))
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
    async with factory() as session:
        await session.execute(text(sql), params)
        await session.commit()
    await engine.dispose()


async def _sweep(settings: Settings, *, now: datetime = NOW) -> object:
    database = Database(settings)
    try:
        use_case = EraseExpiredAccountsUseCase(
            uow=SqlAlchemyUnitOfWork(database.session_factory), clock=FrozenClock(now)
        )
        return await use_case.execute()
    finally:
        await database.dispose()


async def _register(
    client: AsyncClient, email_sender: CapturingEmailSender, email: str
) -> tuple[dict[str, str], str]:
    tokens = await register_and_verify(client, email_sender, email=email)
    return auth_header(tokens), email


async def _user_id(settings: Settings, email: str) -> str:
    return str(await _scalar(settings, "SELECT id FROM users WHERE email = :e", e=email))


async def _mark_deleted(settings: Settings, email: str, *, days_ago: int) -> None:
    """Put an account into the deleted state as of N days before the frozen now."""
    await _execute(
        settings,
        "UPDATE users SET status = 'deleted', deleted_at = :at WHERE email = :e",
        at=NOW - timedelta(days=days_ago),
        e=email,
    )


class TestTheGracePeriodIsHonoured:
    async def test_an_account_inside_the_window_is_untouched(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        """The window is the user's protection, and this query is what enforces it."""
        _, email = await _register(client, email_sender, "inside@example.com")
        await _mark_deleted(api_settings, email, days_ago=GRACE_PERIOD_DAYS - 1)

        report = await _sweep(api_settings)
        assert report.erased == 0

        status = await _scalar(api_settings, "SELECT status FROM users WHERE email = :e", e=email)
        assert status == "deleted"

    async def test_an_account_past_the_window_is_erased(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        _, email = await _register(client, email_sender, "expired@example.com")
        user_id = await _user_id(api_settings, email)
        await _mark_deleted(api_settings, email, days_ago=GRACE_PERIOD_DAYS + 1)

        report = await _sweep(api_settings)
        assert report.erased == 1

        status = await _scalar(api_settings, "SELECT status FROM users WHERE id = :i", i=user_id)
        assert status == "erased"

    async def test_a_live_account_is_never_considered(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        _, email = await _register(client, email_sender, "alive@example.com")
        report = await _sweep(api_settings)
        assert report.considered == 0

        status = await _scalar(api_settings, "SELECT status FROM users WHERE email = :e", e=email)
        assert status == "active"

    def test_the_deadline_is_thirty_days_after_scheduling(self) -> None:
        assert erasure_deadline(NOW) == NOW + timedelta(days=30)


class TestWhatSurvives:
    async def test_the_identity_is_scrubbed(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        _, email = await _register(client, email_sender, "scrub@example.com")
        user_id = await _user_id(api_settings, email)
        await _mark_deleted(api_settings, email, days_ago=GRACE_PERIOD_DAYS + 1)
        await _sweep(api_settings)

        row = await _scalar(api_settings, "SELECT email FROM users WHERE id = :i", i=user_id)
        assert row == f"erased-{user_id}@invalid"

        # The original address must be gone, not merely hidden — it is the thing a
        # right-to-erasure request is actually about.
        remaining = await _scalar(
            api_settings, "SELECT count(*) FROM users WHERE email = :e", e=email
        )
        assert remaining == 0

    async def test_the_password_hash_cannot_verify(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        """An erased account must not be loggable into, whatever anyone knows."""
        _, email = await _register(client, email_sender, "pw@example.com")
        user_id = await _user_id(api_settings, email)
        await _mark_deleted(api_settings, email, days_ago=GRACE_PERIOD_DAYS + 1)
        await _sweep(api_settings)

        stored = await _scalar(
            api_settings, "SELECT password_hash FROM users WHERE id = :i", i=user_id
        )
        assert not str(stored).startswith("$argon2")

    async def test_personal_data_is_gone(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        headers, email = await _register(client, email_sender, "data@example.com")

        logged = await client.post(
            "/v1/progress/weight", json={"weightKg": "80.00"}, headers=headers
        )
        assert logged.status_code == 201, logged.text
        await client.post("/v1/nutrition/water", json={"millilitres": "500"}, headers=headers)

        user_id = await _user_id(api_settings, email)
        await _mark_deleted(api_settings, email, days_ago=GRACE_PERIOD_DAYS + 1)
        await _sweep(api_settings)

        for table in ("weight_logs", "water_logs", "user_profiles", "refresh_tokens"):
            count = await _scalar(
                api_settings,
                f"SELECT count(*) FROM {table} WHERE user_id = :i",  # noqa: S608
                i=user_id,
            )
            assert count == 0, table

    async def test_anonymous_aggregates_survive(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        """The whole reason erasure anonymises rather than deleting.

        A hard delete would make platform statistics rewrite themselves every time
        somebody leaves — last month's active-user count would drop retroactively.
        """
        headers, email = await _register(client, email_sender, "aggregate@example.com")
        await client.post("/v1/nutrition/water", json={"millilitres": "500"}, headers=headers)

        user_id = await _user_id(api_settings, email)
        before = await _scalar(
            api_settings,
            "SELECT count(*) FROM daily_nutrition_summaries WHERE user_id = :i",
            i=user_id,
        )
        assert before == 1

        await _mark_deleted(api_settings, email, days_ago=GRACE_PERIOD_DAYS + 1)
        await _sweep(api_settings)

        after = await _scalar(
            api_settings,
            "SELECT count(*) FROM daily_nutrition_summaries WHERE user_id = :i",
            i=user_id,
        )
        assert after == 1

        # And the row it hangs off still exists, so the foreign key is intact.
        assert (
            await _scalar(api_settings, "SELECT count(*) FROM users WHERE id = :i", i=user_id) == 1
        )


class TestTheSweepIsSafeToRepeat:
    async def test_running_twice_erases_once(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        """A scheduled job that is unsafe to re-run is one nobody dares restart."""
        _, email = await _register(client, email_sender, "twice@example.com")
        await _mark_deleted(api_settings, email, days_ago=GRACE_PERIOD_DAYS + 1)

        first = await _sweep(api_settings)
        second = await _sweep(api_settings)

        assert first.erased == 1
        assert second.considered == 0
        assert second.erased == 0

    async def test_the_batch_limit_is_respected(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        """Erasure is not urgent, and a sweep that locks thousands of rows competes
        with live traffic. What is left waits for the next run."""
        for index in range(3):
            _, email = await _register(client, email_sender, f"batch{index}@example.com")
            await _mark_deleted(api_settings, email, days_ago=GRACE_PERIOD_DAYS + 1)

        limited = await _sweep_limited(api_settings, limit=2)
        assert limited.erased == 2

        remainder = await _sweep(api_settings)
        assert remainder.erased == 1


async def _sweep_limited(settings: Settings, *, limit: int) -> object:
    database = Database(settings)
    try:
        use_case = EraseExpiredAccountsUseCase(
            uow=SqlAlchemyUnitOfWork(database.session_factory), clock=FrozenClock(NOW)
        )
        return await use_case.execute(limit=limit)
    finally:
        await database.dispose()
