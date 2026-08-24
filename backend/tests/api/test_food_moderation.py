"""The moderation queue for user-submitted foods.

Food data quality is the fatal risk of this phase, and this queue is the human half of
the mitigation: nothing reaches the shared catalogue without a person checking the
numbers. The tests that matter are the ones about what approval actually changes — who
can see the food afterwards, and at which trust tier.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coresync.core.config import Settings
from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration

OWNER_EMAIL = "owner@example.com"
ADMIN_EMAIL = "moderator@example.com"


async def _promote_to_admin(api_settings: Settings, email: str) -> None:
    engine = create_async_engine(str(api_settings.database_url))
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
    async with factory() as session:
        await session.execute(
            text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email}
        )
        await session.commit()
    await engine.dispose()


@pytest.fixture
async def owner(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender, email=OWNER_EMAIL))


@pytest.fixture
async def admin(
    client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
) -> dict[str, str]:
    headers = auth_header(await register_and_verify(client, email_sender, email=ADMIN_EMAIL))
    await _promote_to_admin(api_settings, ADMIN_EMAIL)
    return headers


@pytest.fixture
async def stranger(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(
        await register_and_verify(client, email_sender, email="stranger@example.com")
    )


async def make_food(
    client: AsyncClient, headers: dict[str, str], name: str = "Ψωμί χωριάτικο"
) -> dict:
    response = await client.post(
        "/v1/nutrition/foods",
        json={
            "name": name,
            "caloriesPer100g": "250",
            "proteinPer100g": "8",
            "carbsPer100g": "48",
            "fatPer100g": "2",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def submit(
    client: AsyncClient, headers: dict[str, str], food_id: str, **body: object
) -> dict:
    response = await client.post(
        f"/v1/nutrition/foods/{food_id}/submit", json=body, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def queue(
    client: AsyncClient, headers: dict[str, str], status: str = "pending"
) -> list[dict]:
    response = await client.get(
        "/v1/admin/food-submissions", params={"status": status}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


class TestSubmitting:
    async def test_a_custom_food_can_be_offered(self, client: AsyncClient, owner: dict) -> None:
        food = await make_food(client, owner)
        submission = await submit(client, owner, food["id"], note="Common supermarket loaf")
        assert submission["status"] == "pending"
        assert submission["foodId"] == food["id"]

    async def test_submitting_twice_is_not_an_error(self, client: AsyncClient, owner: dict) -> None:
        """The user is describing a desired state, not requesting a state change."""
        food = await make_food(client, owner)
        first = await submit(client, owner, food["id"])
        second = await submit(client, owner, food["id"])
        assert first["id"] == second["id"]

    async def test_a_curated_food_cannot_be_submitted(
        self, client: AsyncClient, owner: dict
    ) -> None:
        results = await client.get("/v1/nutrition/foods", params={"q": "Φέτα"}, headers=owner)
        feta = next(f for f in results.json()["items"] if f["name"] == "Φέτα")
        response = await client.post(
            f"/v1/nutrition/foods/{feta['id']}/submit", json={}, headers=owner
        )
        # Not the owner's food, so it does not exist as far as they are concerned.
        assert response.status_code == 404

    async def test_another_users_food_cannot_be_submitted(
        self, client: AsyncClient, owner: dict, stranger: dict
    ) -> None:
        food = await make_food(client, owner)
        response = await client.post(
            f"/v1/nutrition/foods/{food['id']}/submit", json={}, headers=stranger
        )
        assert response.status_code == 404


class TestTheQueue:
    async def test_a_submission_appears_for_a_reviewer(
        self, client: AsyncClient, owner: dict, admin: dict
    ) -> None:
        food = await make_food(client, owner)
        await submit(client, owner, food["id"])

        items = await queue(client, admin)
        assert len(items) == 1
        assert items[0]["food"]["name"] == food["name"]

    async def test_the_queue_carries_the_numbers_not_just_an_id(
        self, client: AsyncClient, owner: dict, admin: dict
    ) -> None:
        """A reviewer who has to go look up the macros will not look them up."""
        food = await make_food(client, owner)
        await submit(client, owner, food["id"])

        item = (await queue(client, admin))[0]
        assert Decimal(item["food"]["caloriesPer100g"]) == Decimal("250")
        assert "energyIsConsistent" in item

    async def test_a_non_admin_cannot_read_the_queue(
        self, client: AsyncClient, owner: dict
    ) -> None:
        response = await client.get("/v1/admin/food-submissions", headers=owner)
        assert response.status_code == 403


class TestApproval:
    async def test_approval_publishes_the_food_at_official_tier(
        self, client: AsyncClient, owner: dict, admin: dict
    ) -> None:
        """Tier 2, not tier 1. A reviewer checked these numbers; they did not write them."""
        food = await make_food(client, owner)
        await submit(client, owner, food["id"])
        submission = (await queue(client, admin))[0]["submission"]

        approved = await client.post(
            f"/v1/admin/food-submissions/{submission['id']}/approve",
            json={},
            headers=admin,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        results = await client.get("/v1/nutrition/foods", params={"q": food["name"]}, headers=admin)
        published = next(f for f in results.json()["items"] if f["name"] == food["name"])
        assert published["trustTier"] == 2
        assert published["isVerified"] is True

    async def test_an_approved_food_becomes_visible_to_everyone(
        self, client: AsyncClient, owner: dict, admin: dict, stranger: dict
    ) -> None:
        """The point of the whole queue."""
        food = await make_food(client, owner, name="Κουλούρι Θεσσαλονίκης")
        await submit(client, owner, food["id"])
        submission = (await queue(client, admin))[0]["submission"]

        before = await client.get("/v1/nutrition/foods", params={"q": "Κουλούρι"}, headers=stranger)
        assert before.json()["items"] == []

        await client.post(
            f"/v1/admin/food-submissions/{submission['id']}/approve",
            json={},
            headers=admin,
        )

        after = await client.get("/v1/nutrition/foods", params={"q": "Κουλούρι"}, headers=stranger)
        assert "Κουλούρι Θεσσαλονίκης" in {f["name"] for f in after.json()["items"]}

    async def test_a_reviewed_submission_leaves_the_pending_queue(
        self, client: AsyncClient, owner: dict, admin: dict
    ) -> None:
        food = await make_food(client, owner)
        await submit(client, owner, food["id"])
        submission = (await queue(client, admin))[0]["submission"]

        await client.post(
            f"/v1/admin/food-submissions/{submission['id']}/approve",
            json={},
            headers=admin,
        )
        assert await queue(client, admin) == []
        assert len(await queue(client, admin, status="approved")) == 1

    async def test_reviewing_twice_is_refused(
        self, client: AsyncClient, owner: dict, admin: dict
    ) -> None:
        food = await make_food(client, owner)
        await submit(client, owner, food["id"])
        submission = (await queue(client, admin))[0]["submission"]

        first = await client.post(
            f"/v1/admin/food-submissions/{submission['id']}/approve", json={}, headers=admin
        )
        assert first.status_code == 200
        second = await client.post(
            f"/v1/admin/food-submissions/{submission['id']}/reject", json={}, headers=admin
        )
        assert second.status_code == 400

    async def test_a_non_admin_cannot_approve(
        self, client: AsyncClient, owner: dict, admin: dict, stranger: dict
    ) -> None:
        food = await make_food(client, owner)
        await submit(client, owner, food["id"])
        submission = (await queue(client, admin))[0]["submission"]

        response = await client.post(
            f"/v1/admin/food-submissions/{submission['id']}/approve",
            json={},
            headers=stranger,
        )
        assert response.status_code == 403


class TestRejection:
    async def test_rejection_leaves_the_food_private_and_usable(
        self, client: AsyncClient, owner: dict, admin: dict, stranger: dict
    ) -> None:
        """The owner loses the promotion, not the food."""
        food = await make_food(client, owner, name="Πίτα γιαγιάς")
        await submit(client, owner, food["id"])
        submission = (await queue(client, admin))[0]["submission"]

        rejected = await client.post(
            f"/v1/admin/food-submissions/{submission['id']}/reject",
            json={"note": "Numbers need a source."},
            headers=admin,
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

        mine = await client.get("/v1/nutrition/foods", params={"q": "Πίτα γιαγιάς"}, headers=owner)
        assert "Πίτα γιαγιάς" in {f["name"] for f in mine.json()["items"]}

        # Not an empty result: "Πίτα γιαγιάς" trigram-matches the curated "Πίτα για
        # σουβλάκι", which the stranger is entitled to see. What must be absent is the
        # rejected food itself.
        theirs = await client.get(
            "/v1/nutrition/foods", params={"q": "Πίτα γιαγιάς"}, headers=stranger
        )
        assert "Πίτα γιαγιάς" not in {f["name"] for f in theirs.json()["items"]}

    async def test_a_rejected_food_can_be_submitted_again(
        self, client: AsyncClient, owner: dict, admin: dict
    ) -> None:
        """Otherwise a user is locked out of the queue by their own first attempt."""
        food = await make_food(client, owner)
        await submit(client, owner, food["id"])
        submission = (await queue(client, admin))[0]["submission"]
        await client.post(
            f"/v1/admin/food-submissions/{submission['id']}/reject", json={}, headers=admin
        )

        again = await submit(client, owner, food["id"])
        assert again["status"] == "pending"
        assert again["id"] != submission["id"]
