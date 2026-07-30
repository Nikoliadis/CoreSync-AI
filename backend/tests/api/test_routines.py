"""Routines: creation, atomic reordering, duplication and optimistic locking."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.conftest import auth_header, exercise_id_for, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration


@pytest.fixture
async def headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender))


@pytest.fixture
async def bench_id(client: AsyncClient, headers: dict[str, str]) -> str:
    return await exercise_id_for(client, headers, "Barbell Bench Press")


@pytest.fixture
async def squat_id(client: AsyncClient, headers: dict[str, str]) -> str:
    return await exercise_id_for(client, headers, "Back Squat")


async def create_routine(
    client: AsyncClient, headers: dict[str, str], bench_id: str, **overrides
) -> dict:
    payload = {
        "name": "Push Day",
        "folder": "PPL",
        "exercises": [
            {
                "exerciseId": bench_id,
                "restSeconds": 120,
                "sets": [
                    {"targetRepsMin": 5, "targetRepsMax": 8, "targetWeightKg": "100"},
                    {"targetRepsMin": 5, "targetRepsMax": 8, "targetWeightKg": "100"},
                ],
            }
        ],
    }
    payload.update(overrides)
    response = await client.post("/v1/workouts/routines", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestRoutineCrud:
    async def test_create_with_nested_exercises_and_sets(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        assert routine["name"] == "Push Day"
        assert routine["folder"] == "PPL"
        assert routine["totalSets"] == 2
        assert routine["version"] == 1
        assert routine["exercises"][0]["exerciseName"] == "Barbell Bench Press"
        assert routine["exercises"][0]["sets"][0]["targetRepsMax"] == 8

    async def test_list_and_get(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)

        listing = await client.get("/v1/workouts/routines", headers=headers)
        assert [r["id"] for r in listing.json()] == [routine["id"]]

        detail = await client.get(f"/v1/workouts/routines/{routine['id']}", headers=headers)
        assert detail.json()["exercises"][0]["restSeconds"] == 120

    async def test_update_metadata_bumps_the_version(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        response = await client.patch(
            f"/v1/workouts/routines/{routine['id']}",
            json={"name": "Upper A", "estimatedMinutes": 60},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Upper A"
        assert response.json()["version"] == 2

    async def test_unknown_exercise_is_rejected(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/workouts/routines",
            json={
                "name": "Bad",
                "exercises": [{"exerciseId": "0192f8e0-7b3a-7c4d-9e2f-000000000000", "sets": []}],
            },
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_error"

    async def test_delete_a_routine(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        assert (
            await client.delete(f"/v1/workouts/routines/{routine['id']}", headers=headers)
        ).status_code == 204
        assert (
            await client.get(f"/v1/workouts/routines/{routine['id']}", headers=headers)
        ).status_code == 404


class TestReplaceExercises:
    async def test_replace_reorders_and_renumbers_atomically(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str, squat_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        response = await client.put(
            f"/v1/workouts/routines/{routine['id']}/exercises",
            json={
                "exercises": [
                    {"exerciseId": squat_id, "sets": [{"targetRepsMin": 5, "targetRepsMax": 5}]},
                    {"exerciseId": bench_id, "sets": [{"targetRepsMin": 8, "targetRepsMax": 12}]},
                ]
            },
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert [e["exerciseId"] for e in body["exercises"]] == [squat_id, bench_id]
        assert [e["position"] for e in body["exercises"]] == [1, 2]
        assert body["version"] == 2

    async def test_replace_with_an_empty_list_clears_the_routine(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        response = await client.put(
            f"/v1/workouts/routines/{routine['id']}/exercises",
            json={"exercises": []},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["exercises"] == []


class TestOptimisticLocking:
    async def test_a_stale_version_is_rejected(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """Two devices editing the same routine: the second learns rather than clobbers."""
        routine = await create_routine(client, headers, bench_id)

        first = await client.patch(
            f"/v1/workouts/routines/{routine['id']}",
            json={"name": "Edited First", "version": 1},
            headers=headers,
        )
        assert first.status_code == 200

        second = await client.patch(
            f"/v1/workouts/routines/{routine['id']}",
            json={"name": "Edited Second", "version": 1},
            headers=headers,
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "conflict"

    async def test_omitting_the_version_forces_the_write(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        await client.patch(
            f"/v1/workouts/routines/{routine['id']}", json={"name": "One"}, headers=headers
        )
        forced = await client.patch(
            f"/v1/workouts/routines/{routine['id']}", json={"name": "Two"}, headers=headers
        )
        assert forced.status_code == 200
        assert forced.json()["name"] == "Two"


class TestDuplication:
    async def test_duplicate_copies_structure_without_sharing_ids(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        response = await client.post(
            f"/v1/workouts/routines/{routine['id']}/duplicate", json={}, headers=headers
        )
        assert response.status_code == 201
        copy = response.json()

        assert copy["id"] != routine["id"]
        assert copy["name"] == "Push Day (copy)"
        assert copy["totalSets"] == routine["totalSets"]
        assert copy["exercises"][0]["id"] != routine["exercises"][0]["id"]
        assert copy["exercises"][0]["exerciseId"] == bench_id

    async def test_editing_a_copy_leaves_the_original_alone(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        copy = (
            await client.post(
                f"/v1/workouts/routines/{routine['id']}/duplicate",
                json={"name": "Variant"},
                headers=headers,
            )
        ).json()

        await client.put(
            f"/v1/workouts/routines/{copy['id']}/exercises",
            json={"exercises": []},
            headers=headers,
        )

        original = await client.get(f"/v1/workouts/routines/{routine['id']}", headers=headers)
        assert original.json()["totalSets"] == 2


class TestRoutinesAndSessions:
    async def test_starting_from_a_routine_seeds_the_exercises(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        routine = await create_routine(client, headers, bench_id)
        response = await client.post(
            "/v1/workouts/sessions", json={"routineId": routine["id"]}, headers=headers
        )
        assert response.status_code == 201
        session = response.json()

        assert session["name"] == "Push Day"
        assert session["routineId"] == routine["id"]
        assert [e["exerciseId"] for e in session["exercises"]] == [bench_id]
        # Prescribed sets are not pre-logged: the user has not done them yet.
        assert session["exercises"][0]["sets"] == []

    async def test_deleting_a_routine_preserves_workout_history(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """The most important ON DELETE choice in the schema, exercised end to end."""
        routine = await create_routine(client, headers, bench_id)
        session = (
            await client.post(
                "/v1/workouts/sessions", json={"routineId": routine["id"]}, headers=headers
            )
        ).json()
        entry_id = session["exercises"][0]["id"]
        await client.post(
            f"/v1/workouts/sessions/{session['id']}/exercises/{entry_id}/sets",
            json={"reps": 8, "weightKg": "100"},
            headers=headers,
        )
        await client.post(
            f"/v1/workouts/sessions/{session['id']}/complete", json={}, headers=headers
        )

        await client.delete(f"/v1/workouts/routines/{routine['id']}", headers=headers)

        stored = await client.get(f"/v1/workouts/sessions/{session['id']}", headers=headers)
        assert stored.status_code == 200
        assert stored.json()["totalVolumeKg"] == "800.00"


class TestRoutineAuthorizationBoundary:
    async def test_routines_are_private(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        owner = auth_header(
            await register_and_verify(client, email_sender, email="routine-owner@example.com")
        )
        bench = await exercise_id_for(client, owner, "Barbell Bench Press")
        routine = await create_routine(client, owner, bench)

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="routine-thief@example.com")
        )

        assert (
            await client.get(f"/v1/workouts/routines/{routine['id']}", headers=intruder)
        ).status_code == 404
        assert (
            await client.patch(
                f"/v1/workouts/routines/{routine['id']}", json={"name": "x"}, headers=intruder
            )
        ).status_code == 404
        assert (
            await client.put(
                f"/v1/workouts/routines/{routine['id']}/exercises",
                json={"exercises": []},
                headers=intruder,
            )
        ).status_code == 404
        assert (
            await client.delete(f"/v1/workouts/routines/{routine['id']}", headers=intruder)
        ).status_code == 404
        assert (await client.get("/v1/workouts/routines", headers=intruder)).json() == []

    async def test_a_routine_cannot_reference_another_users_custom_exercise(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        owner = auth_header(
            await register_and_verify(client, email_sender, email="ex-owner@example.com")
        )
        custom = (
            await client.post(
                "/v1/exercises",
                json={"name": "Private Move", "categorySlug": "strength"},
                headers=owner,
            )
        ).json()

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="ex-thief@example.com")
        )
        response = await client.post(
            "/v1/workouts/routines",
            json={"name": "Probe", "exercises": [{"exerciseId": custom["id"], "sets": []}]},
            headers=intruder,
        )
        assert response.status_code == 400
