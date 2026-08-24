"""Correcting what you logged: edit, copy, favourites.

These are the operations a diary lives or dies on. Mistyping 200 g as 2000 g happens
daily, and a diary where the only fix is delete-and-retype is one people stop using.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration


@pytest.fixture
async def headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender))


@pytest.fixture
async def other_headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(
        await register_and_verify(client, email_sender, email="intruder@example.com")
    )


def days_ago(count: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=count)).isoformat()


async def food_named(client: AsyncClient, headers: dict[str, str], name: str) -> dict:
    response = await client.get("/v1/nutrition/foods", params={"q": name}, headers=headers)
    assert response.status_code == 200, response.text
    match = next((f for f in response.json()["items"] if f["name"] == name), None)
    assert match is not None, f"seeded food '{name}' not found"
    return match


async def log(client: AsyncClient, headers: dict[str, str], **body: object) -> dict:
    response = await client.post("/v1/nutrition/diary", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestEditingADiaryEntry:
    async def test_changing_the_amount_rescales_the_macros(
        self, client: AsyncClient, headers: dict
    ) -> None:
        chicken = await food_named(client, headers, "Στήθος κοτόπουλο ωμό")
        entry = await log(client, headers, foodId=chicken["id"], mealType="lunch", quantity="200")

        edited = await client.patch(
            f"/v1/nutrition/diary/{entry['id']}", json={"quantity": "100"}, headers=headers
        )
        assert edited.status_code == 200, edited.text
        assert Decimal(edited.json()["macros"]["calories"]) == Decimal("165")
        assert Decimal(edited.json()["totalGrams"]) == Decimal("100")

    async def test_repeated_edits_do_not_drift(self, client: AsyncClient, headers: dict) -> None:
        """The reason the amount is re-derived from the food rather than scaled.

        Scaling the already-rounded macros would compound the rounding, so a value
        corrected back and forth would slowly wander away from the truth.
        """
        chicken = await food_named(client, headers, "Στήθος κοτόπουλο ωμό")
        entry = await log(client, headers, foodId=chicken["id"], mealType="lunch", quantity="200")

        for amount in ("173", "37", "200"):
            response = await client.patch(
                f"/v1/nutrition/diary/{entry['id']}",
                json={"quantity": amount},
                headers=headers,
            )
            assert response.status_code == 200, response.text

        assert Decimal(response.json()["macros"]["calories"]) == Decimal("330")

    async def test_moving_an_entry_to_another_meal(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        edited = await client.patch(
            f"/v1/nutrition/diary/{entry['id']}", json={"mealType": "dinner"}, headers=headers
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["mealType"] == "dinner"

    async def test_moving_an_entry_to_another_day(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")
        yesterday = days_ago(1)

        edited = await client.patch(
            f"/v1/nutrition/diary/{entry['id']}",
            json={"localDate": yesterday},
            headers=headers,
        )
        assert edited.status_code == 200, edited.text

        today = await client.get("/v1/nutrition/diary", headers=headers)
        assert today.json()["entries"] == []
        moved = await client.get("/v1/nutrition/diary", params={"on": yesterday}, headers=headers)
        assert len(moved.json()["entries"]) == 1

    async def test_an_empty_patch_changes_nothing(self, client: AsyncClient, headers: dict) -> None:
        """Send only what changed — and sending nothing is not an error."""
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        edited = await client.patch(f"/v1/nutrition/diary/{entry['id']}", json={}, headers=headers)
        assert edited.status_code == 200, edited.text
        assert edited.json()["macros"] == entry["macros"]

    async def test_editing_a_quick_add_scales_its_macros(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """No food to re-derive from, so the stored numbers are scaled instead."""
        created = await client.post(
            "/v1/nutrition/diary/quick-add",
            json={"mealType": "dinner", "calories": "600", "proteinG": "30"},
            headers=headers,
        )
        assert created.status_code == 201, created.text

        edited = await client.patch(
            f"/v1/nutrition/diary/{created.json()['id']}",
            json={"quantity": "2"},
            headers=headers,
        )
        assert edited.status_code == 200, edited.text
        assert Decimal(edited.json()["macros"]["calories"]) == Decimal("1200")

    async def test_zero_is_rejected(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")
        response = await client.patch(
            f"/v1/nutrition/diary/{entry['id']}", json={"quantity": "0"}, headers=headers
        )
        assert response.status_code == 400

    async def test_another_user_cannot_edit_my_entry(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        response = await client.patch(
            f"/v1/nutrition/diary/{entry['id']}", json={"quantity": "500"}, headers=other_headers
        )
        assert response.status_code == 404

        mine = await client.get("/v1/nutrition/diary", headers=headers)
        assert Decimal(mine.json()["entries"][0]["totalGrams"]) == Decimal("100")


class TestCopyingADay:
    async def test_copying_a_whole_day(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        feta = await food_named(client, headers, "Φέτα")
        yesterday = days_ago(1)
        await log(
            client,
            headers,
            foodId=egg["id"],
            mealType="breakfast",
            quantity="100",
            localDate=yesterday,
        )
        await log(
            client,
            headers,
            foodId=feta["id"],
            mealType="lunch",
            quantity="30",
            localDate=yesterday,
        )

        today = days_ago(0)
        response = await client.post(
            "/v1/nutrition/diary/copy",
            json={"sourceDate": yesterday, "targetDate": today},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["copied"] == 2

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert len(diary.json()["entries"]) == 2

    async def test_copying_one_meal_only(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        feta = await food_named(client, headers, "Φέτα")
        yesterday = days_ago(1)
        await log(
            client,
            headers,
            foodId=egg["id"],
            mealType="breakfast",
            quantity="100",
            localDate=yesterday,
        )
        await log(
            client,
            headers,
            foodId=feta["id"],
            mealType="lunch",
            quantity="30",
            localDate=yesterday,
        )

        response = await client.post(
            "/v1/nutrition/diary/copy",
            json={
                "sourceDate": yesterday,
                "targetDate": days_ago(0),
                "mealType": "breakfast",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["copied"] == 1

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert [e["mealType"] for e in diary.json()["entries"]] == ["breakfast"]

    async def test_the_copy_keeps_the_original_numbers(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """A copy that disagreed with its source would be worse than no copy."""
        egg = await food_named(client, headers, "Αυγό")
        yesterday = days_ago(1)
        original = await log(
            client,
            headers,
            foodId=egg["id"],
            mealType="breakfast",
            quantity="100",
            localDate=yesterday,
        )

        await client.post(
            "/v1/nutrition/diary/copy",
            json={"sourceDate": yesterday, "targetDate": days_ago(0)},
            headers=headers,
        )
        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert diary.json()["entries"][0]["macros"] == original["macros"]

    async def test_copying_an_empty_day_is_rejected(
        self, client: AsyncClient, headers: dict
    ) -> None:
        response = await client.post(
            "/v1/nutrition/diary/copy",
            json={"sourceDate": days_ago(30), "targetDate": days_ago(0)},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_another_users_day_cannot_be_copied(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        yesterday = days_ago(1)
        await log(
            client,
            headers,
            foodId=egg["id"],
            mealType="breakfast",
            quantity="100",
            localDate=yesterday,
        )

        response = await client.post(
            "/v1/nutrition/diary/copy",
            json={"sourceDate": yesterday, "targetDate": days_ago(0)},
            headers=other_headers,
        )
        # Nothing of theirs is on that day, so there is nothing to copy.
        assert response.status_code == 400


class TestFavourites:
    async def test_star_and_list(self, client: AsyncClient, headers: dict) -> None:
        feta = await food_named(client, headers, "Φέτα")

        starred = await client.put(f"/v1/nutrition/foods/{feta['id']}/favourite", headers=headers)
        assert starred.status_code == 204, starred.text

        listed = await client.get("/v1/nutrition/foods/favourites", headers=headers)
        assert listed.status_code == 200, listed.text
        assert [f["name"] for f in listed.json()["items"]] == ["Φέτα"]

    async def test_the_favourites_route_is_not_swallowed_by_the_id_route(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """`/foods/favourites` must not be parsed as `/foods/{food_id}`."""
        response = await client.get("/v1/nutrition/foods/favourites", headers=headers)
        assert response.status_code == 200
        assert "items" in response.json()

    async def test_starring_twice_is_not_an_error(self, client: AsyncClient, headers: dict) -> None:
        feta = await food_named(client, headers, "Φέτα")
        for _ in range(2):
            response = await client.put(
                f"/v1/nutrition/foods/{feta['id']}/favourite", headers=headers
            )
            assert response.status_code == 204

        listed = await client.get("/v1/nutrition/foods/favourites", headers=headers)
        assert len(listed.json()["items"]) == 1

    async def test_unstarring(self, client: AsyncClient, headers: dict) -> None:
        feta = await food_named(client, headers, "Φέτα")
        await client.put(f"/v1/nutrition/foods/{feta['id']}/favourite", headers=headers)

        removed = await client.delete(
            f"/v1/nutrition/foods/{feta['id']}/favourite", headers=headers
        )
        assert removed.status_code == 204

        listed = await client.get("/v1/nutrition/foods/favourites", headers=headers)
        assert listed.json()["items"] == []

    async def test_a_starred_food_outranks_an_unstarred_one(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """docs/15 ranks favourites above verified, and this is that rule."""
        milk_full = await food_named(client, headers, "Γάλα πλήρες 3.5%")
        await client.put(f"/v1/nutrition/foods/{milk_full['id']}/favourite", headers=headers)

        results = await client.get("/v1/nutrition/foods", params={"q": "Γάλα"}, headers=headers)
        assert results.json()["items"][0]["name"] == "Γάλα πλήρες 3.5%"

    async def test_favourites_are_per_user(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        feta = await food_named(client, headers, "Φέτα")
        await client.put(f"/v1/nutrition/foods/{feta['id']}/favourite", headers=headers)

        listed = await client.get("/v1/nutrition/foods/favourites", headers=other_headers)
        assert listed.json()["items"] == []


class TestEditingACustomFood:
    async def _create(self, client: AsyncClient, headers: dict) -> dict:
        response = await client.post(
            "/v1/nutrition/foods",
            json={
                "name": "Πρωτεΐνη ορού",
                "caloriesPer100g": "400",
                "proteinPer100g": "80",
                "carbsPer100g": "8",
                "fatPer100g": "6",
                "servings": [{"label": "1 σκουπ", "grams": "30"}],
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def test_correcting_the_macros(self, client: AsyncClient, headers: dict) -> None:
        food = await self._create(client, headers)
        updated = await client.put(
            f"/v1/nutrition/foods/{food['id']}",
            json={
                "name": "Πρωτεΐνη ορού",
                "caloriesPer100g": "380",
                "proteinPer100g": "75",
                "carbsPer100g": "10",
                "fatPer100g": "5",
            },
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert Decimal(updated.json()["caloriesPer100g"]) == Decimal("380")
        assert updated.json()["id"] == food["id"]

    async def test_the_energy_check_still_applies(self, client: AsyncClient, headers: dict) -> None:
        food = await self._create(client, headers)
        response = await client.put(
            f"/v1/nutrition/foods/{food['id']}",
            json={
                "name": "Πρωτεΐνη ορού",
                "caloriesPer100g": "40",
                "proteinPer100g": "80",
                "carbsPer100g": "8",
                "fatPer100g": "6",
            },
            headers=headers,
        )
        assert response.status_code == 400

    async def test_correcting_a_food_does_not_rewrite_the_diary(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """The snapshot rule again, this time through the edit path."""
        food = await self._create(client, headers)
        entry = await log(client, headers, foodId=food["id"], mealType="snack", quantity="100")
        assert Decimal(entry["macros"]["calories"]) == Decimal("400")

        await client.put(
            f"/v1/nutrition/foods/{food['id']}",
            json={
                "name": "Πρωτεΐνη ορού",
                "caloriesPer100g": "380",
                "proteinPer100g": "75",
                "carbsPer100g": "10",
                "fatPer100g": "5",
            },
            headers=headers,
        )

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert Decimal(diary.json()["entries"][0]["macros"]["calories"]) == Decimal("400")

    async def test_a_curated_food_cannot_be_edited(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """A curated row is shared by everyone. One user must not rewrite it for all."""
        feta = await food_named(client, headers, "Φέτα")
        response = await client.put(
            f"/v1/nutrition/foods/{feta['id']}",
            json={"name": "Hijacked", "caloriesPer100g": "1"},
            headers=headers,
        )
        assert response.status_code == 404

    async def test_another_user_cannot_edit_my_food(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        food = await self._create(client, headers)
        response = await client.put(
            f"/v1/nutrition/foods/{food['id']}",
            json={"name": "Hijacked", "caloriesPer100g": "100", "proteinPer100g": "25"},
            headers=other_headers,
        )
        assert response.status_code == 404

    async def test_deleting_a_custom_food(self, client: AsyncClient, headers: dict) -> None:
        food = await self._create(client, headers)
        deleted = await client.delete(f"/v1/nutrition/foods/{food['id']}", headers=headers)
        assert deleted.status_code == 204

        results = await client.get("/v1/nutrition/foods", params={"q": "Πρωτεΐνη"}, headers=headers)
        assert results.json()["items"] == []

    async def test_deleting_a_food_leaves_the_diary_alone(
        self, client: AsyncClient, headers: dict
    ) -> None:
        food = await self._create(client, headers)
        await log(client, headers, foodId=food["id"], mealType="snack", quantity="100")

        await client.delete(f"/v1/nutrition/foods/{food['id']}", headers=headers)

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert len(diary.json()["entries"]) == 1
        assert Decimal(diary.json()["entries"][0]["macros"]["calories"]) == Decimal("400")

    async def test_a_curated_food_cannot_be_deleted(
        self, client: AsyncClient, headers: dict
    ) -> None:
        feta = await food_named(client, headers, "Φέτα")
        response = await client.delete(f"/v1/nutrition/foods/{feta['id']}", headers=headers)
        assert response.status_code == 404
