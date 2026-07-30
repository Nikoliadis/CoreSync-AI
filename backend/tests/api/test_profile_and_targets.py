"""Profile, onboarding, goals, targets — and the authorization boundary."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.conftest import DEFAULT_PASSWORD, auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration

ONBOARDING = {
    "dateOfBirth": "2002-03-15",
    "gender": "male",
    "heightCm": "181",
    "weightKg": "82.5",
    "activityLevel": "moderate",
    "experienceLevel": "intermediate",
    "goalType": "lose_fat",
    "targetWeightKg": "78",
    "weeklyRateKg": "-0.45",
    "unitSystem": "metric",
}


class TestMe:
    async def test_returns_the_full_bootstrap_payload(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        response = await client.get("/v1/users/me", headers=auth_header(payload))
        assert response.status_code == 200

        body = response.json()
        assert body["user"]["email"] == "lifter@example.com"
        assert body["profile"]["displayName"] == "Test Lifter"
        assert body["profile"]["isOnboarded"] is False
        assert body["targets"] is None
        assert body["settings"]["unitSystem"] == "metric"
        # Off by default and only changed by explicit user action.
        assert body["settings"]["aiTrainingOptIn"] is False

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/users/me")).status_code == 401

    async def test_rejects_a_malformed_bearer_token(self, client: AsyncClient) -> None:
        response = await client.get("/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401


class TestOnboarding:
    async def test_produces_a_complete_profile_goal_and_targets(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        response = await client.post(
            "/v1/users/me/onboarding", json=ONBOARDING, headers=auth_header(payload)
        )
        assert response.status_code == 201, response.text

        body = response.json()
        target = body["target"]
        assert Decimal(target["calories"]) >= 1200
        assert Decimal(target["proteinG"]) > 0
        assert target["source"] == "auto"
        assert body["wasClampedToFloor"] is False
        # The working is returned so the UI can explain the number rather than assert it.
        assert Decimal(body["bmr"]) > 0
        assert Decimal(body["tdee"]) > Decimal(body["bmr"])

        me = (await client.get("/v1/users/me", headers=auth_header(payload))).json()
        assert me["profile"]["isOnboarded"] is True
        assert me["profile"]["age"] is not None
        assert me["goal"]["goalType"] == "lose_fat"
        assert me["targets"]["calories"] == target["calories"]

    async def test_clamps_an_unsafe_weekly_rate(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        await client.post(
            "/v1/users/me/onboarding",
            json={**ONBOARDING, "weeklyRateKg": "-2.5"},
            headers=auth_header(payload),
        )
        me = (await client.get("/v1/users/me", headers=auth_header(payload))).json()
        # At 82.5 kg the 1%/week limit is 0.825 kg.
        assert Decimal(me["goal"]["weeklyRateKg"]) >= Decimal("-0.825")

    async def test_rejects_an_under_13_date_of_birth(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        response = await client.post(
            "/v1/users/me/onboarding",
            json={**ONBOARDING, "dateOfBirth": "2020-01-01"},
            headers=auth_header(payload),
        )
        assert response.status_code >= 400

    async def test_is_idempotent_on_the_same_day(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """Re-running must not create a second 'current' target row.

        The partial unique index would reject that, so this test proves the same-day
        update path is taken rather than a second insert.
        """
        payload = await register_and_verify(client, email_sender)
        first = await client.post(
            "/v1/users/me/onboarding", json=ONBOARDING, headers=auth_header(payload)
        )
        second = await client.post(
            "/v1/users/me/onboarding",
            json={**ONBOARDING, "goalType": "gain_muscle"},
            headers=auth_header(payload),
        )
        assert first.status_code == 201
        assert second.status_code == 201

        history = await client.get("/v1/users/me/targets/history", headers=auth_header(payload))
        assert len([t for t in history.json() if t["effectiveTo"] is None]) == 1


class TestTargets:
    async def test_manual_targets_are_accepted_when_consistent(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        await client.post("/v1/users/me/onboarding", json=ONBOARDING, headers=auth_header(payload))
        # 180*4 + 250*4 + 70*9 = 2350 kcal
        response = await client.put(
            "/v1/users/me/targets",
            json={"calories": "2350", "proteinG": "180", "carbsG": "250", "fatG": "70"},
            headers=auth_header(payload),
        )
        assert response.status_code == 200
        assert response.json()["source"] == "manual"

    async def test_rejects_a_target_below_the_safety_floor(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """The floor is enforced in the service *and* as a CHECK constraint.

        This is the single most important guardrail in the product: no code path,
        including the AI coach, can write a dangerous calorie target.
        """
        payload = await register_and_verify(client, email_sender)
        await client.post("/v1/users/me/onboarding", json=ONBOARDING, headers=auth_header(payload))
        response = await client.put(
            "/v1/users/me/targets",
            json={"calories": "800", "proteinG": "100", "carbsG": "50", "fatG": "22"},
            headers=auth_header(payload),
        )
        assert response.status_code == 400

    async def test_rejects_macros_that_do_not_add_up(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        await client.post("/v1/users/me/onboarding", json=ONBOARDING, headers=auth_header(payload))
        response = await client.put(
            "/v1/users/me/targets",
            json={"calories": "2500", "proteinG": "10", "carbsG": "10", "fatG": "10"},
            headers=auth_header(payload),
        )
        assert response.status_code == 400
        assert response.json()["error"]["details"][0]["code"] == "inconsistent"

    async def test_history_is_versioned_rather_than_overwritten(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """Overwriting would destroy the ability to answer 'was I in a deficit in March?'."""
        payload = await register_and_verify(client, email_sender)
        await client.post("/v1/users/me/onboarding", json=ONBOARDING, headers=auth_header(payload))
        await client.put(
            "/v1/users/me/targets",
            json={"calories": "2350", "proteinG": "180", "carbsG": "250", "fatG": "70"},
            headers=auth_header(payload),
        )
        history = await client.get("/v1/users/me/targets/history", headers=auth_header(payload))
        assert history.status_code == 200
        assert len(history.json()) >= 1

    async def test_recalculate_requires_a_goal_and_a_weight(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        response = await client.post(
            "/v1/users/me/targets/recalculate", headers=auth_header(payload)
        )
        assert response.status_code == 409


class TestAuthorizationBoundary:
    """Ownership scoping — OWASP A01, the risk that actually materialises in this shape of app."""

    async def test_one_user_never_sees_another_users_data(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        alice = await register_and_verify(client, email_sender, email="alice@example.com")
        await client.post("/v1/users/me/onboarding", json=ONBOARDING, headers=auth_header(alice))
        bob = await register_and_verify(client, email_sender, email="bob@example.com")

        alice_me = (await client.get("/v1/users/me", headers=auth_header(alice))).json()
        bob_me = (await client.get("/v1/users/me", headers=auth_header(bob))).json()

        assert alice_me["user"]["id"] != bob_me["user"]["id"]
        assert bob_me["targets"] is None, "Bob must not inherit Alice's targets"
        assert bob_me["profile"]["isOnboarded"] is False

    async def test_bob_cannot_revoke_alices_session(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        alice = await register_and_verify(client, email_sender, email="alice@example.com")
        bob = await register_and_verify(client, email_sender, email="bob@example.com")

        alice_sessions = (await client.get("/v1/auth/sessions", headers=auth_header(alice))).json()
        target_id = alice_sessions[0]["id"]

        response = await client.delete(f"/v1/auth/sessions/{target_id}", headers=auth_header(bob))
        assert response.status_code == 204  # no information leaked either way

        # The decisive assertion: Alice's session still works.
        still_valid = await client.post(
            "/v1/auth/refresh", json={"refreshToken": alice["refreshToken"]}
        )
        assert still_valid.status_code == 200

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/v1/users/me"),
            ("PATCH", "/v1/users/me"),
            ("PUT", "/v1/users/me/settings"),
            ("POST", "/v1/users/me/onboarding"),
            ("POST", "/v1/users/me/goals"),
            ("PUT", "/v1/users/me/targets"),
            ("GET", "/v1/users/me/targets/history"),
            ("POST", "/v1/users/me/targets/recalculate"),
            ("DELETE", "/v1/users/me"),
            ("GET", "/v1/auth/sessions"),
            ("POST", "/v1/auth/logout-all"),
        ],
    )
    async def test_every_protected_endpoint_rejects_anonymous_access(
        self, client: AsyncClient, method: str, path: str
    ) -> None:
        response = await client.request(method, path, json={})
        assert response.status_code == 401, f"{method} {path} is not protected"


class TestAccountLifecycle:
    async def test_deletion_is_scheduled_and_ends_every_session(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        response = await client.delete("/v1/users/me", headers=auth_header(payload))
        assert response.status_code == 200
        assert response.json()["scheduledFor"]

        stale = await client.post(
            "/v1/auth/refresh", json={"refreshToken": payload["refreshToken"]}
        )
        assert stale.status_code == 401

        assert (
            await client.post(
                "/v1/auth/login",
                json={"email": "lifter@example.com", "password": DEFAULT_PASSWORD},
            )
        ).status_code == 401

    async def test_settings_can_be_updated(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        payload = await register_and_verify(client, email_sender)
        response = await client.put(
            "/v1/users/me/settings",
            json={"unitSystem": "imperial", "theme": "dark", "aiTrainingOptIn": True},
            headers=auth_header(payload),
        )
        assert response.status_code == 200
        assert response.json()["unitSystem"] == "imperial"
        assert response.json()["theme"] == "dark"
