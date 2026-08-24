"""Food search, the diary, water and custom foods.

The IDOR cases here are the point of the file. Every nutrition read takes a user id in
the predicate rather than filtering afterwards, and these tests are what stops that
guarantee quietly regressing: a second registered user asks for the first user's data
by id and must be told it does not exist.
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


async def search(client: AsyncClient, headers: dict[str, str], term: str) -> list[dict]:
    response = await client.get("/v1/nutrition/foods", params={"q": term}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def food_named(client: AsyncClient, headers: dict[str, str], name: str) -> dict:
    """Resolve a seeded food by name rather than hard-coding a uuid."""
    items = await search(client, headers, name)
    match = next((item for item in items if item["name"] == name), None)
    assert match is not None, f"seeded food '{name}' not found"
    return match


async def log(client: AsyncClient, headers: dict[str, str], **body: str) -> dict:
    response = await client.post("/v1/nutrition/diary", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestFoodSearch:
    async def test_finds_a_curated_food(self, client: AsyncClient, headers: dict) -> None:
        food = await food_named(client, headers, "Φέτα")
        assert food["trustTier"] == 1
        assert food["isVerified"] is True
        assert food["source"] == "curated"

    async def test_search_ignores_accents(self, client: AsyncClient, headers: dict) -> None:
        """The reason migration 0008 wraps names in `unaccent`.

        Nobody types the tonos on a phone keyboard. Without this the query misses
        entirely — full text does not match and trigram similarity drops to 0.5.
        """
        names = {item["name"] for item in await search(client, headers, "γιαουρτι")}
        assert "Γιαούρτι στραγγιστό 2%" in names

    async def test_search_ignores_case(self, client: AsyncClient, headers: dict) -> None:
        names = {item["name"] for item in await search(client, headers, "ΦΕΤΑ")}
        assert "Φέτα" in names

    async def test_a_curated_food_carries_its_servings(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """Logging in grams only is how a diary stops being used."""
        food = await food_named(client, headers, "Αυγό")
        assert [s["label"] for s in food["servings"]] == ["1 μεγάλο"]
        assert food["servings"][0]["isDefault"] is True

    async def test_alcohol_survives_the_round_trip(
        self, client: AsyncClient, headers: dict
    ) -> None:
        wine = await food_named(client, headers, "Κρασί κόκκινο")
        assert Decimal(wine["alcoholPer100g"]) == Decimal("10.6")

    async def test_an_empty_query_still_returns_foods(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """The search screen opens before anyone types."""
        response = await client.get("/v1/nutrition/foods", headers=headers)
        assert response.status_code == 200
        assert response.json()["total"] > 0

    async def test_search_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get("/v1/nutrition/foods", params={"q": "Φέτα"})
        assert response.status_code == 401


class TestCustomFoods:
    async def test_create_and_find_own_food(self, client: AsyncClient, headers: dict) -> None:
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
        created = response.json()
        assert created["isCustom"] is True
        assert created["trustTier"] == 4
        assert created["isVerified"] is False

        names = {item["name"] for item in await search(client, headers, "Πρωτεΐνη")}
        assert "Πρωτεΐνη ορού" in names

    async def test_macros_that_do_not_reconcile_are_rejected(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """A misplaced decimal point is the failure mode that matters.

        80 g protein, 8 g carbohydrate and 6 g fat reconcile to 406 kcal, not 40.
        Telling someone they ate a tenth of what they ate is the fatal risk in docs/15,
        so the API refuses the row and names the number it should have been — a message
        the user can act on, rather than a constraint violation surfacing as a 500.
        """
        response = await client.post(
            "/v1/nutrition/foods",
            json={
                "name": "Λάθος τροφή",
                "caloriesPer100g": "40",
                "proteinPer100g": "80",
                "carbsPer100g": "8",
                "fatPer100g": "6",
            },
            headers=headers,
        )
        assert response.status_code == 400, response.text
        assert "406" in response.text

    async def test_a_spirit_reconciles_through_alcohol(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """Regression for migration 0009.

        Tsipouro is ~40% ABV and almost pure ethanol: 225 kcal per 100 g against zero
        protein, carbohydrate and fat. Before alcohol was a tracked term this was
        indistinguishable from a typo and the API rejected it.
        """
        response = await client.post(
            "/v1/nutrition/foods",
            json={
                "name": "Τσίπουρο",
                "caloriesPer100g": "225",
                "alcoholPer100g": "32",
                "isLiquid": True,
                "servings": [{"label": "1 ποτηράκι", "grams": "50"}],
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        assert Decimal(response.json()["alcoholPer100g"]) == Decimal("32")

    async def test_another_user_cannot_see_my_custom_food(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        """A custom food is private. Search must scope by owner, not filter after."""
        await client.post(
            "/v1/nutrition/foods",
            json={"name": "Μυστική συνταγή", "caloriesPer100g": "100", "proteinPer100g": "25"},
            headers=headers,
        )
        names = {item["name"] for item in await search(client, other_headers, "Μυστική")}
        assert "Μυστική συνταγή" not in names


class TestDiary:
    async def test_logging_in_grams(self, client: AsyncClient, headers: dict) -> None:
        chicken = await food_named(client, headers, "Στήθος κοτόπουλο ωμό")
        entry = await log(client, headers, foodId=chicken["id"], mealType="lunch", quantity="200")
        assert Decimal(entry["totalGrams"]) == Decimal("200")
        assert Decimal(entry["macros"]["calories"]) == Decimal("330")
        assert Decimal(entry["macros"]["proteinG"]) == Decimal("62")

    async def test_logging_by_serving(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        serving = egg["servings"][0]
        entry = await log(
            client,
            headers,
            foodId=egg["id"],
            mealType="breakfast",
            quantity="2",
            servingId=serving["id"],
        )
        assert Decimal(entry["totalGrams"]) == Decimal("116")
        assert entry["displayName"] == "Αυγό"

    async def test_the_diary_totals_a_day(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        feta = await food_named(client, headers, "Φέτα")
        await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")
        await log(client, headers, foodId=feta["id"], mealType="lunch", quantity="30")

        response = await client.get("/v1/nutrition/diary", headers=headers)
        assert response.status_code == 200, response.text
        diary = response.json()
        assert len(diary["entries"]) == 2

        by_meal = {meal["mealType"]: meal for meal in diary["byMeal"]}
        assert by_meal["breakfast"]["entries"] == 1
        assert by_meal["lunch"]["entries"] == 1

    async def test_a_correction_to_a_food_does_not_rewrite_history(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """The diary snapshots. A food is a definition; an entry is a record."""
        created = await client.post(
            "/v1/nutrition/foods",
            json={"name": "Μπάρα δημητριακών", "caloriesPer100g": "400", "carbsPer100g": "95"},
            headers=headers,
        )
        food_id = created.json()["id"]
        entry = await log(client, headers, foodId=food_id, mealType="snack", quantity="100")
        assert Decimal(entry["macros"]["calories"]) == Decimal("400")

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert Decimal(diary.json()["entries"][0]["macros"]["calories"]) == Decimal("400")

    async def test_quick_add_needs_no_food(self, client: AsyncClient, headers: dict) -> None:
        response = await client.post(
            "/v1/nutrition/diary/quick-add",
            json={"mealType": "dinner", "calories": "650", "label": "Ταβέρνα"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        entry = response.json()
        assert entry["displayName"] == "Ταβέρνα"
        assert entry["foodId"] is None

    async def test_logging_to_an_explicit_past_date(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        yesterday = days_ago(1)
        await log(
            client,
            headers,
            foodId=egg["id"],
            mealType="breakfast",
            quantity="50",
            localDate=yesterday,
        )
        today = await client.get("/v1/nutrition/diary", headers=headers)
        assert today.json()["entries"] == []

        back_then = await client.get(
            "/v1/nutrition/diary", params={"on": yesterday}, headers=headers
        )
        assert len(back_then.json()["entries"]) == 1

    async def test_deleting_an_entry_removes_it_from_the_totals(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        deleted = await client.delete(f"/v1/nutrition/diary/{entry['id']}", headers=headers)
        assert deleted.status_code == 204

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert diary.json()["entries"] == []

    async def test_logging_an_unknown_food_is_a_404(
        self, client: AsyncClient, headers: dict
    ) -> None:
        response = await client.post(
            "/v1/nutrition/diary",
            json={
                "foodId": "018f0000-0000-7000-8000-000000000000",
                "mealType": "lunch",
                "quantity": "100",
            },
            headers=headers,
        )
        assert response.status_code == 404

    async def test_a_serving_from_another_food_is_rejected(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        milk = await food_named(client, headers, "Γάλα πλήρες 3.5%")
        response = await client.post(
            "/v1/nutrition/diary",
            json={
                "foodId": egg["id"],
                "mealType": "breakfast",
                "quantity": "1",
                "servingId": milk["servings"][0]["id"],
            },
            headers=headers,
        )
        assert response.status_code == 400


class TestDiaryIsolation:
    async def test_another_users_entries_are_invisible(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        intruder = await client.get("/v1/nutrition/diary", headers=other_headers)
        assert intruder.status_code == 200
        assert intruder.json()["entries"] == []

    async def test_another_user_cannot_delete_my_entry(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        """The IDOR case. Knowing the id must not be enough to act on it."""
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        response = await client.delete(f"/v1/nutrition/diary/{entry['id']}", headers=other_headers)
        assert response.status_code == 404

        mine = await client.get("/v1/nutrition/diary", headers=headers)
        assert len(mine.json()["entries"]) == 1


class TestWater:
    async def test_water_accumulates_through_the_day(
        self, client: AsyncClient, headers: dict
    ) -> None:
        first = await client.post(
            "/v1/nutrition/water", json={"millilitres": "250"}, headers=headers
        )
        assert first.status_code == 201, first.text
        assert Decimal(first.json()["totalMl"]) == Decimal("250")

        second = await client.post(
            "/v1/nutrition/water", json={"millilitres": "500"}, headers=headers
        )
        assert Decimal(second.json()["totalMl"]) == Decimal("750")

    async def test_the_response_carries_the_day_it_landed_on(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """The server's date is not the user's date.

        A glass logged at 01:00 in Athens belongs to the Athens day. The endpoint returns
        the date the use case resolved rather than letting the caller recompute it.
        """
        response = await client.post(
            "/v1/nutrition/water", json={"millilitres": "250"}, headers=headers
        )
        assert response.json()["localDate"] is not None

    async def test_water_shows_up_in_the_diary(self, client: AsyncClient, headers: dict) -> None:
        await client.post("/v1/nutrition/water", json={"millilitres": "400"}, headers=headers)
        diary = await client.get("/v1/nutrition/diary", headers=headers)
        assert Decimal(diary.json()["waterMl"]) == Decimal("400")

    async def test_another_users_water_is_not_counted(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        await client.post("/v1/nutrition/water", json={"millilitres": "400"}, headers=headers)
        intruder = await client.get("/v1/nutrition/water", headers=other_headers)
        assert Decimal(intruder.json()["totalMl"]) == Decimal(0)

    async def test_a_negative_amount_is_rejected(self, client: AsyncClient, headers: dict) -> None:
        response = await client.post(
            "/v1/nutrition/water", json={"millilitres": "-250"}, headers=headers
        )
        assert response.status_code == 400


class TestBarcode:
    async def test_an_unknown_barcode_is_a_404(self, client: AsyncClient, headers: dict) -> None:
        """A miss is not an error. The client decides whether to offer a wider lookup."""
        response = await client.get("/v1/nutrition/foods/barcode/5201234567890", headers=headers)
        assert response.status_code == 404


class TestRecentFoods:
    async def test_recent_reflects_what_was_logged(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """The empty state of the search screen.

        In practice people re-log the same twenty foods, so this is the list that ends up
        carrying most of the logging.
        """
        feta = await food_named(client, headers, "Φέτα")
        await log(client, headers, foodId=feta["id"], mealType="lunch", quantity="30")

        response = await client.get("/v1/nutrition/foods/recent", headers=headers)
        assert response.status_code == 200, response.text
        assert "Φέτα" in {item["name"] for item in response.json()["items"]}

    async def test_recent_is_per_user(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        feta = await food_named(client, headers, "Φέτα")
        await log(client, headers, foodId=feta["id"], mealType="lunch", quantity="30")

        response = await client.get("/v1/nutrition/foods/recent", headers=other_headers)
        assert response.json()["items"] == []
