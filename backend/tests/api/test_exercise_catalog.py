"""Exercise catalog: search, filters, custom exercises and the authorisation boundary."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.conftest import auth_header, exercise_id_for, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration


@pytest.fixture
async def headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender))


class TestCatalogSearch:
    async def test_catalog_is_seeded_and_listable(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.get("/v1/exercises", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 250
        assert len(body["items"]) == 50  # default page size
        assert body["hasMore"] is True

    async def test_search_matches_by_name(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.get("/v1/exercises", params={"q": "bench press"}, headers=headers)
        names = [item["name"] for item in response.json()["items"]]
        assert "Barbell Bench Press" in names

    async def test_search_tolerates_a_typo(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """Lifters type "deadlfit" mid-workout and still expect the deadlift."""
        response = await client.get("/v1/exercises", params={"q": "deadlfit"}, headers=headers)
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert any("Deadlift" in name for name in names)

    async def test_filter_by_muscle_group_returns_primary_movers(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.get(
            "/v1/exercises", params={"muscle_group": "chest", "limit": 100}, headers=headers
        )
        items = response.json()["items"]
        assert items
        for item in items:
            groups = {m["groupSlug"] for m in item["muscles"] if m["role"] == "primary"}
            assert "chest" in groups

    async def test_filter_by_equipment(self, client: AsyncClient, headers: dict[str, str]) -> None:
        response = await client.get(
            "/v1/exercises", params={"equipment": "dumbbell", "limit": 100}, headers=headers
        )
        items = response.json()["items"]
        assert items
        assert all("dumbbell" in item["equipment"] for item in items)

    async def test_filters_combine(self, client: AsyncClient, headers: dict[str, str]) -> None:
        response = await client.get(
            "/v1/exercises",
            params={"muscle_group": "legs", "equipment": "barbell", "limit": 100},
            headers=headers,
        )
        items = response.json()["items"]
        assert items
        for item in items:
            assert "barbell" in item["equipment"]

    async def test_pagination_does_not_repeat_items(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        first = await client.get("/v1/exercises", params={"limit": 20}, headers=headers)
        second = await client.get(
            "/v1/exercises", params={"limit": 20, "offset": 20}, headers=headers
        )
        first_ids = {i["id"] for i in first.json()["items"]}
        second_ids = {i["id"] for i in second.json()["items"]}
        assert not (first_ids & second_ids)

    async def test_detail_includes_muscles_and_equipment(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        exercise_id = await exercise_id_for(client, headers, "Barbell Bench Press")
        response = await client.get(f"/v1/exercises/{exercise_id}", headers=headers)
        body = response.json()
        assert body["isVerified"] is True
        assert body["isCustom"] is False
        assert body["loggingType"] == "weight_reps"
        assert {m["slug"] for m in body["muscles"]} >= {"mid_chest", "triceps"}
        assert "barbell" in body["equipment"]

    async def test_metadata_endpoints(self, client: AsyncClient, headers: dict[str, str]) -> None:
        groups = await client.get("/v1/exercises/meta/muscle-groups", headers=headers)
        assert groups.status_code == 200
        assert {g["slug"] for g in groups.json()} >= {"chest", "back", "legs"}
        assert any(g["muscles"] for g in groups.json())

        equipment = await client.get("/v1/exercises/meta/equipment", headers=headers)
        assert {e["slug"] for e in equipment.json()} >= {"barbell", "dumbbell"}

        categories = await client.get("/v1/exercises/meta/categories", headers=headers)
        assert {c["slug"] for c in categories.json()} >= {"strength", "cardio"}

    async def test_catalog_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/exercises")).status_code == 401


class TestCustomExercises:
    async def test_create_and_retrieve(self, client: AsyncClient, headers: dict[str, str]) -> None:
        response = await client.post(
            "/v1/exercises",
            json={
                "name": "Reverse Nordic Curl",
                "categorySlug": "strength",
                "primaryMuscleSlugs": ["quads"],
                "equipmentSlugs": ["bodyweight"],
                "loggingType": "bodyweight_reps",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["isCustom"] is True
        # A user cannot mint a verified exercise — the CHECK constraint enforces it too.
        assert body["isVerified"] is False

        detail = await client.get(f"/v1/exercises/{body['id']}", headers=headers)
        assert detail.json()["name"] == "Reverse Nordic Curl"

    async def test_custom_exercise_appears_in_search(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        await client.post(
            "/v1/exercises",
            json={
                "name": "Zombie Squat",
                "categorySlug": "strength",
                "primaryMuscleSlugs": ["quads"],
            },
            headers=headers,
        )
        response = await client.get("/v1/exercises", params={"customOnly": True}, headers=headers)
        assert [i["name"] for i in response.json()["items"]] == ["Zombie Squat"]

    async def test_unknown_category_is_rejected(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/exercises",
            json={"name": "Nonsense", "categorySlug": "does-not-exist"},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_error"

    async def test_unknown_muscle_is_rejected(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/exercises",
            json={
                "name": "Nonsense",
                "categorySlug": "strength",
                "primaryMuscleSlugs": ["gluteus-maximums"],
            },
            headers=headers,
        )
        assert response.status_code == 400

    async def test_duplicate_names_are_allowed_and_get_distinct_slugs(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """Two exercises called the same thing must not collide on the unique index."""
        payload = {"name": "My Movement", "categorySlug": "strength"}
        first = await client.post("/v1/exercises", json=payload, headers=headers)
        second = await client.post("/v1/exercises", json=payload, headers=headers)
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["slug"] != second.json()["slug"]

    async def test_update_own_exercise(self, client: AsyncClient, headers: dict[str, str]) -> None:
        created = await client.post(
            "/v1/exercises",
            json={"name": "Old Name", "categorySlug": "strength"},
            headers=headers,
        )
        exercise_id = created.json()["id"]
        response = await client.patch(
            f"/v1/exercises/{exercise_id}",
            json={"name": "New Name", "difficulty": "advanced"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"
        assert response.json()["difficulty"] == "advanced"

    async def test_global_catalog_cannot_be_edited(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """The curated catalog changes through the admin surface, which has an audit trail."""
        exercise_id = await exercise_id_for(client, headers, "Barbell Bench Press")
        response = await client.patch(
            f"/v1/exercises/{exercise_id}", json={"name": "Hijacked"}, headers=headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    async def test_global_catalog_cannot_be_deleted(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        exercise_id = await exercise_id_for(client, headers, "Deadlift")
        response = await client.delete(f"/v1/exercises/{exercise_id}", headers=headers)
        assert response.status_code == 403

    async def test_delete_own_exercise_removes_it_from_search(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        created = await client.post(
            "/v1/exercises",
            json={"name": "Temporary Move", "categorySlug": "strength"},
            headers=headers,
        )
        exercise_id = created.json()["id"]
        assert (
            await client.delete(f"/v1/exercises/{exercise_id}", headers=headers)
        ).status_code == 204
        assert (
            await client.get(f"/v1/exercises/{exercise_id}", headers=headers)
        ).status_code == 404


class TestCustomExerciseIsolation:
    async def test_one_user_cannot_see_or_touch_anothers_custom_exercise(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """The IDOR boundary. Custom exercises are private to their author."""
        owner = auth_header(
            await register_and_verify(client, email_sender, email="owner@example.com")
        )
        created = await client.post(
            "/v1/exercises",
            json={"name": "Secret Lift", "categorySlug": "strength"},
            headers=owner,
        )
        exercise_id = created.json()["id"]

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="intruder@example.com")
        )

        assert (
            await client.get(f"/v1/exercises/{exercise_id}", headers=intruder)
        ).status_code == 404
        assert (
            await client.patch(
                f"/v1/exercises/{exercise_id}", json={"name": "Stolen"}, headers=intruder
            )
        ).status_code == 404
        assert (
            await client.delete(f"/v1/exercises/{exercise_id}", headers=intruder)
        ).status_code == 404

        search = await client.get("/v1/exercises", params={"q": "Secret"}, headers=intruder)
        assert search.json()["items"] == []


class TestFavorites:
    async def test_favorite_round_trip(self, client: AsyncClient, headers: dict[str, str]) -> None:
        exercise_id = await exercise_id_for(client, headers, "Pull-Up")

        assert (
            await client.post(f"/v1/exercises/{exercise_id}/favorite", headers=headers)
        ).status_code == 204
        detail = await client.get(f"/v1/exercises/{exercise_id}", headers=headers)
        assert detail.json()["isFavorite"] is True

        listing = await client.get("/v1/exercises", params={"favoritesOnly": True}, headers=headers)
        assert [i["id"] for i in listing.json()["items"]] == [exercise_id]

        assert (
            await client.delete(f"/v1/exercises/{exercise_id}/favorite", headers=headers)
        ).status_code == 204
        listing = await client.get("/v1/exercises", params={"favoritesOnly": True}, headers=headers)
        assert listing.json()["items"] == []

    async def test_favoriting_twice_is_idempotent(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        exercise_id = await exercise_id_for(client, headers, "Chin-Up")
        await client.post(f"/v1/exercises/{exercise_id}/favorite", headers=headers)
        second = await client.post(f"/v1/exercises/{exercise_id}/favorite", headers=headers)
        assert second.status_code == 204


class TestExerciseMedia:
    """Demonstration photographs, from the table down to the JSON.

    `exercise_media` shipped in the first migration and stayed empty for months, which
    meant nothing ever exercised the path from that table to the client. These tests run
    it end to end so the importer has something to import *into* that is known to work.
    """

    async def test_media_reaches_the_client_in_order(
        self, client: AsyncClient, headers: dict[str, str], postgres_url: str
    ) -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        exercise_id = await exercise_id_for(client, headers, "Barbell Bench Press")

        # Inserted directly rather than through the importer: this is about the read
        # path, and the importer needs the network.
        engine = create_async_engine(postgres_url)
        try:
            async with engine.begin() as connection:
                for order, name in ((1, "second.jpg"), (0, "first.jpg")):
                    await connection.execute(
                        text(
                            "INSERT INTO exercise_media"
                            " (id, exercise_id, media_type, url, sort_order,"
                            "  created_at, updated_at)"
                            " VALUES (gen_random_uuid(), :eid, 'image', :url, :ord,"
                            "         now(), now())"
                        ),
                        {
                            "eid": exercise_id,
                            "url": f"https://example.test/{name}",
                            "ord": order,
                        },
                    )
        finally:
            await engine.dispose()

        response = await client.get(f"/v1/exercises/{exercise_id}", headers=headers)
        assert response.status_code == 200, response.text

        media = response.json()["media"]
        assert [item["url"] for item in media] == [
            "https://example.test/first.jpg",
            "https://example.test/second.jpg",
        ], "media must arrive in sort_order, not insertion order"
        assert {item["mediaType"] for item in media} == {"image"}

    async def test_an_exercise_without_media_returns_an_empty_list(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        # The normal case for most of the catalogue. It has to be an empty list rather
        # than null, because every client renders it without a guard.
        exercise_id = await exercise_id_for(client, headers, "Back Squat")
        response = await client.get(f"/v1/exercises/{exercise_id}", headers=headers)

        assert response.json()["media"] == []
