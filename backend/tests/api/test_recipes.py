"""Recipes: composed dishes that reference their ingredients.

The rule under test is the one that separates a recipe from a diary entry. A recipe is a
*definition* — it holds references, so correcting a food corrects the recipe. An entry is
a *record* — it holds a snapshot, so nothing that happens later rewrites what was eaten.
Both directions are asserted here, because getting either backwards is silent.
"""

from __future__ import annotations

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


async def food_named(client: AsyncClient, headers: dict[str, str], name: str) -> dict:
    response = await client.get("/v1/nutrition/foods", params={"q": name}, headers=headers)
    assert response.status_code == 200, response.text
    match = next((f for f in response.json()["items"] if f["name"] == name), None)
    assert match is not None, f"seeded food '{name}' not found"
    return match


async def create_recipe(client: AsyncClient, headers: dict[str, str], **body: object) -> dict:
    response = await client.post("/v1/nutrition/recipes", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestCreatingRecipes:
    async def test_totals_are_computed_from_the_ingredients(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        feta = await food_named(client, headers, "Φέτα")

        recipe = await create_recipe(
            client,
            headers,
            name="Ομελέτα με φέτα",
            servingsCount="2",
            ingredients=[
                {"foodId": egg["id"], "grams": "116"},
                {"foodId": feta["id"], "grams": "60"},
            ],
        )

        # 116 g egg at 155 kcal/100 g plus 60 g feta at 264 kcal/100 g.
        expected = Decimal("155") * Decimal("1.16") + Decimal("264") * Decimal("0.6")
        assert abs(Decimal(recipe["total"]["calories"]) - expected) < Decimal("1")

    async def test_per_serving_divides_by_the_serving_count(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        recipe = await create_recipe(
            client,
            headers,
            name="Four eggs, two people",
            servingsCount="2",
            ingredients=[{"foodId": egg["id"], "grams": "232"}],
        )
        total = Decimal(recipe["total"]["calories"])
        per_serving = Decimal(recipe["perServing"]["calories"])
        assert abs(per_serving * 2 - total) < Decimal("1")

    async def test_a_recipe_can_start_empty(self, client: AsyncClient, headers: dict) -> None:
        """Named first, filled in later — that is how anyone actually writes one down."""
        recipe = await create_recipe(client, headers, name="Γεμιστά", servingsCount="4")
        assert recipe["ingredients"] == []
        assert Decimal(recipe["total"]["calories"]) == 0

    async def test_zero_servings_is_rejected(self, client: AsyncClient, headers: dict) -> None:
        response = await client.post(
            "/v1/nutrition/recipes",
            json={"name": "Nothing", "servingsCount": "0"},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_an_ingredient_that_does_not_exist_is_rejected(
        self, client: AsyncClient, headers: dict
    ) -> None:
        response = await client.post(
            "/v1/nutrition/recipes",
            json={
                "name": "Ghost",
                "servingsCount": "1",
                "ingredients": [{"foodId": "018f0000-0000-7000-8000-000000000000", "grams": "100"}],
            },
            headers=headers,
        )
        assert response.status_code == 400

    async def test_another_users_private_food_cannot_be_used_as_an_ingredient(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        """Otherwise a recipe is a way to read someone's private macros by guessing an id."""
        mine = await client.post(
            "/v1/nutrition/foods",
            json={"name": "Μυστικό", "caloriesPer100g": "500", "fatPer100g": "55"},
            headers=headers,
        )
        assert mine.status_code == 201, mine.text

        response = await client.post(
            "/v1/nutrition/recipes",
            json={
                "name": "Stolen",
                "servingsCount": "1",
                "ingredients": [{"foodId": mine.json()["id"], "grams": "100"}],
            },
            headers=other_headers,
        )
        assert response.status_code == 400


class TestDefinitionVersusRecord:
    async def test_correcting_a_food_updates_the_recipe(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """A recipe references. This is the half that must track the catalogue.

        Built on a custom food because that is the one this test can correct; the effect
        is identical for a curated one that gets a data fix.
        """
        created = await client.post(
            "/v1/nutrition/foods",
            json={"name": "Αλεύρι", "caloriesPer100g": "364", "carbsPer100g": "76"},
            headers=headers,
        )
        food_id = created.json()["id"]

        recipe = await create_recipe(
            client,
            headers,
            name="Ζύμη",
            servingsCount="1",
            ingredients=[{"foodId": food_id, "grams": "100"}],
        )
        assert abs(Decimal(recipe["total"]["calories"]) - Decimal("364")) < Decimal("1")

        # There is no food-edit endpoint yet, so the correction is modelled the way a
        # user would do it today: a second food, and the recipe repointed at it.
        corrected = await client.post(
            "/v1/nutrition/foods",
            json={"name": "Αλεύρι ολικής", "caloriesPer100g": "340", "carbsPer100g": "72"},
            headers=headers,
        )
        updated = await client.put(
            f"/v1/nutrition/recipes/{recipe['id']}",
            json={
                "name": "Ζύμη",
                "servingsCount": "1",
                "ingredients": [{"foodId": corrected.json()["id"], "grams": "100"}],
            },
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert abs(Decimal(updated.json()["total"]["calories"]) - Decimal("340")) < Decimal("1")

    async def test_editing_a_recipe_does_not_rewrite_what_was_eaten(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """A diary entry records. This is the half that must not move.

        The whole point of snapshotting: doubling tonight's recipe must not retroactively
        double what last night's dinner is reported to have been.
        """
        egg = await food_named(client, headers, "Αυγό")
        recipe = await create_recipe(
            client,
            headers,
            name="Ομελέτα",
            servingsCount="1",
            ingredients=[{"foodId": egg["id"], "grams": "116"}],
        )

        logged = await client.post(
            f"/v1/nutrition/recipes/{recipe['id']}/log",
            json={"mealType": "breakfast", "servings": "1"},
            headers=headers,
        )
        assert logged.status_code == 201, logged.text
        eaten = Decimal(logged.json()["macros"]["calories"])

        doubled = await client.put(
            f"/v1/nutrition/recipes/{recipe['id']}",
            json={
                "name": "Ομελέτα",
                "servingsCount": "1",
                "ingredients": [{"foodId": egg["id"], "grams": "232"}],
            },
            headers=headers,
        )
        assert doubled.status_code == 200, doubled.text

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert Decimal(diary.json()["entries"][0]["macros"]["calories"]) == eaten

    async def test_deleting_a_recipe_leaves_the_diary_alone(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        recipe = await create_recipe(
            client,
            headers,
            name="Ομελέτα",
            servingsCount="1",
            ingredients=[{"foodId": egg["id"], "grams": "116"}],
        )
        await client.post(
            f"/v1/nutrition/recipes/{recipe['id']}/log",
            json={"mealType": "breakfast", "servings": "1"},
            headers=headers,
        )

        deleted = await client.delete(f"/v1/nutrition/recipes/{recipe['id']}", headers=headers)
        assert deleted.status_code == 204

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert len(diary.json()["entries"]) == 1
        assert Decimal(diary.json()["entries"][0]["macros"]["calories"]) > 0


class TestLoggingRecipes:
    async def test_logging_two_servings_doubles_the_entry(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        recipe = await create_recipe(
            client,
            headers,
            name="Ομελέτα",
            servingsCount="2",
            ingredients=[{"foodId": egg["id"], "grams": "232"}],
        )
        per_serving = Decimal(recipe["perServing"]["calories"])

        logged = await client.post(
            f"/v1/nutrition/recipes/{recipe['id']}/log",
            json={"mealType": "dinner", "servings": "2"},
            headers=headers,
        )
        assert logged.status_code == 201, logged.text
        assert abs(Decimal(logged.json()["macros"]["calories"]) - per_serving * 2) < Decimal("1")

    async def test_the_entry_carries_the_recipe_name_and_id(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        recipe = await create_recipe(
            client,
            headers,
            name="Ομελέτα",
            servingsCount="1",
            ingredients=[{"foodId": egg["id"], "grams": "116"}],
        )
        logged = await client.post(
            f"/v1/nutrition/recipes/{recipe['id']}/log",
            json={"mealType": "breakfast", "servings": "1"},
            headers=headers,
        )
        assert logged.json()["displayName"] == "Ομελέτα"
        assert logged.json()["recipeId"] == recipe["id"]
        assert logged.json()["foodId"] is None

    async def test_an_empty_recipe_cannot_be_logged(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """Logging zero calories as a meal is worse than refusing."""
        recipe = await create_recipe(client, headers, name="Άδειο", servingsCount="1")
        response = await client.post(
            f"/v1/nutrition/recipes/{recipe['id']}/log",
            json={"mealType": "lunch", "servings": "1"},
            headers=headers,
        )
        assert response.status_code == 400


class TestRecipeIsolation:
    async def test_recipes_are_private(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        await create_recipe(client, headers, name="Μυστική συνταγή", servingsCount="1")

        theirs = await client.get("/v1/nutrition/recipes", headers=other_headers)
        assert theirs.status_code == 200
        assert theirs.json()["items"] == []

    async def test_another_user_cannot_read_my_recipe(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        recipe = await create_recipe(client, headers, name="Μυστική", servingsCount="1")
        response = await client.get(f"/v1/nutrition/recipes/{recipe['id']}", headers=other_headers)
        assert response.status_code == 404

    async def test_another_user_cannot_edit_my_recipe(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        recipe = await create_recipe(client, headers, name="Μυστική", servingsCount="1")
        response = await client.put(
            f"/v1/nutrition/recipes/{recipe['id']}",
            json={"name": "Hijacked", "servingsCount": "1", "ingredients": []},
            headers=other_headers,
        )
        assert response.status_code == 404

        mine = await client.get(f"/v1/nutrition/recipes/{recipe['id']}", headers=headers)
        assert mine.json()["name"] == "Μυστική"

    async def test_another_user_cannot_delete_my_recipe(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        recipe = await create_recipe(client, headers, name="Μυστική", servingsCount="1")
        response = await client.delete(
            f"/v1/nutrition/recipes/{recipe['id']}", headers=other_headers
        )
        assert response.status_code == 404

    async def test_another_user_cannot_log_my_recipe(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        recipe = await create_recipe(
            client,
            headers,
            name="Μυστική",
            servingsCount="1",
            ingredients=[{"foodId": egg["id"], "grams": "116"}],
        )
        response = await client.post(
            f"/v1/nutrition/recipes/{recipe['id']}/log",
            json={"mealType": "lunch", "servings": "1"},
            headers=other_headers,
        )
        assert response.status_code == 404
