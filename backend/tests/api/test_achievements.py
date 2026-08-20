"""/v1/achievements.

The property worth defending at this level is idempotence: evaluating twice must not
award twice, and must not announce twice. The composite primary key enforces it in the
database, and these tests prove the endpoint honours it rather than working around it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.asyncio


async def _register(
    client: AsyncClient,
    email_sender: CapturingEmailSender,
    email: str = "achiever@example.com",
) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender, email=email))


class TestListing:
    async def test_a_new_account_has_earned_nothing(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        response = await client.get("/v1/achievements", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["earnedCount"] == 0
        assert body["totalCount"] > 0
        assert all(item["earned"] is False for item in body["achievements"])

    async def test_unearned_entries_carry_their_progress(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """A locked icon with no hint says nothing about how close the user is."""
        headers = await _register(client, email_sender)
        body = (await client.get("/v1/achievements", headers=headers)).json()

        for item in body["achievements"]:
            assert "progress" in item
            assert "threshold" in item
            assert "currentValue" in item

    async def test_the_endpoint_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/achievements")).status_code == 401

    async def test_one_users_achievements_are_not_another_s(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        first = await _register(client, email_sender, "a-one@example.com")
        second = await _register(client, email_sender, "a-two@example.com")

        for headers in (first, second):
            body = (await client.get("/v1/achievements", headers=headers)).json()
            assert body["earnedCount"] == 0


class TestEvaluation:
    async def test_evaluating_with_no_training_awards_nothing(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        response = await client.post("/v1/achievements/evaluate", headers=headers)

        assert response.status_code == 200
        assert response.json()["newlyEarned"] == []

    async def test_evaluating_repeatedly_is_safe(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """Called after every session, so it has to be safe to call constantly."""
        headers = await _register(client, email_sender)

        for _ in range(3):
            response = await client.post("/v1/achievements/evaluate", headers=headers)
            assert response.status_code == 200

        body = (await client.get("/v1/achievements", headers=headers)).json()
        assert body["earnedCount"] == 0

    async def test_evaluation_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.post("/v1/achievements/evaluate")).status_code == 401
