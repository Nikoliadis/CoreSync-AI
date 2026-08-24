"""/v1/notifications and /v1/admin.

The admin assertions matter most: a role guard that is only *usually* applied is worse
than none, because it reads as protection. Every admin route is exercised by a
non-admin here, and the ones that leak would fail loudly.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coresync.core.config import Settings
from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.asyncio

# Every GET on the admin router. New routes belong here: the guard is applied at the
# router level precisely so it cannot be forgotten, and this list is what proves it.
ADMIN_ROUTES = ("/v1/admin/stats", "/v1/admin/users", "/v1/admin/food-submissions")


async def _register(
    client: AsyncClient,
    email_sender: CapturingEmailSender,
    email: str = "notify-user@example.com",
) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender, email=email))


async def _promote_to_admin(api_settings: Settings, email: str) -> None:
    """Elevate a user directly in the database.

    There is deliberately no API for this: role escalation over HTTP is a privilege
    escalation vector, and it belongs in an operator's hands rather than a route.
    """
    engine = create_async_engine(str(api_settings.database_url))
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
    async with factory() as session:
        await session.execute(
            text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email}
        )
        await session.commit()
    await engine.dispose()


# --------------------------------------------------------------- notifications
class TestNotificationList:
    async def test_a_new_account_has_none(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        response = await client.get("/v1/notifications", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["notifications"] == []
        assert body["unreadCount"] == 0

    async def test_the_endpoint_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/notifications")).status_code == 401

    async def test_marking_a_missing_notification_is_a_404(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        response = await client.post(
            "/v1/notifications/019fb2f8-0000-7000-8000-000000000000/read", headers=headers
        )
        assert response.status_code == 404

    async def test_mark_all_read_on_an_empty_list_succeeds(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        response = await client.post("/v1/notifications/read-all", headers=headers)
        assert response.status_code == 200
        assert response.json()["marked"] == 0


class TestNotificationPreferences:
    async def test_defaults_are_returned_before_anything_is_saved(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        body = (await client.get("/v1/notifications/preferences", headers=headers)).json()

        assert body["pushEnabled"] is True
        assert body["quietHoursStart"] == 22
        assert body["quietHoursEnd"] == 7
        assert "pr_celebration" in body["enabledCategories"]

    async def test_preferences_round_trip(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)

        patched = await client.patch(
            "/v1/notifications/preferences",
            json={
                "pushEnabled": False,
                "enabledCategories": ["pr_celebration", "weekly_report"],
                "quietHoursStart": 23,
                "quietHoursEnd": 6,
            },
            headers=headers,
        )
        assert patched.status_code == 200

        body = (await client.get("/v1/notifications/preferences", headers=headers)).json()
        assert body["pushEnabled"] is False
        assert body["enabledCategories"] == ["pr_celebration", "weekly_report"]
        assert body["quietHoursStart"] == 23

    async def test_quiet_hours_can_be_cleared(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """`null` means "unchanged" in a partial update, so removal needs its own flag."""
        headers = await _register(client, email_sender)

        await client.patch(
            "/v1/notifications/preferences", json={"clearQuietHours": True}, headers=headers
        )

        body = (await client.get("/v1/notifications/preferences", headers=headers)).json()
        assert body["quietHoursStart"] is None
        assert body["quietHoursEnd"] is None

    async def test_half_a_quiet_window_is_rejected(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        response = await client.patch(
            "/v1/notifications/preferences", json={"quietHoursStart": 22}, headers=headers
        )
        assert response.status_code == 400

    async def test_an_unknown_category_is_rejected(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        response = await client.patch(
            "/v1/notifications/preferences",
            json={"enabledCategories": ["marketing_spam"]},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_an_out_of_range_hour_is_rejected(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        headers = await _register(client, email_sender)
        response = await client.patch(
            "/v1/notifications/preferences",
            json={"quietHoursStart": 25, "quietHoursEnd": 7},
            headers=headers,
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------- admin
class TestAdminAccessControl:
    @pytest.mark.parametrize("route", ADMIN_ROUTES)
    async def test_an_ordinary_user_is_refused(
        self, client: AsyncClient, email_sender: CapturingEmailSender, route: str
    ) -> None:
        """The assertion the whole admin surface rests on."""
        headers = await _register(client, email_sender)
        response = await client.get(route, headers=headers)
        assert response.status_code == 403, route

    @pytest.mark.parametrize("route", ADMIN_ROUTES)
    async def test_an_anonymous_caller_is_refused(self, client: AsyncClient, route: str) -> None:
        response = await client.get(route)
        assert response.status_code == 401, route

    async def test_the_refusal_leaks_nothing(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """A 403 must not become an oracle for what the endpoint would have returned."""
        headers = await _register(client, email_sender)
        response = await client.get("/v1/admin/stats", headers=headers)
        assert "totalUsers" not in response.text
        assert "aiCost" not in response.text


class TestAdminRoutes:
    async def test_stats_are_returned_to_an_admin(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        email = "operator@example.com"
        headers = await _register(client, email_sender, email)
        await _promote_to_admin(api_settings, email)

        # The role is read from the database on each request, so the existing token is
        # enough — no re-login required.
        response = await client.get("/v1/admin/stats", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["totalUsers"] >= 1
        assert body["aiCallsLastMonth"] >= 0

    async def test_the_user_list_is_searchable(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        email = "operator2@example.com"
        headers = await _register(client, email_sender, email)
        await _promote_to_admin(api_settings, email)

        response = await client.get("/v1/admin/users", params={"q": "operator2"}, headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert any(user["email"] == email for user in body["users"])

    async def test_the_user_list_exposes_no_training_or_body_data(
        self, client: AsyncClient, email_sender: CapturingEmailSender, api_settings: Settings
    ) -> None:
        """Support does not need it, and a panel that shows it is a breach waiting."""
        email = "operator3@example.com"
        headers = await _register(client, email_sender, email)
        await _promote_to_admin(api_settings, email)

        body = (await client.get("/v1/admin/users", headers=headers)).json()

        allowed = {"id", "email", "role", "status", "createdAt"}
        for user in body["users"]:
            assert set(user) <= allowed, set(user) - allowed
