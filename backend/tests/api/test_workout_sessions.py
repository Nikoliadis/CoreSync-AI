"""Live workout logging: start, log sets, finish, records, history and aggregates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


async def start_session(client: AsyncClient, headers: dict[str, str], **body) -> dict:
    response = await client.post("/v1/workouts/sessions", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def log_set(
    client: AsyncClient,
    headers: dict[str, str],
    session_id: str,
    exercise_entry_id: str,
    **body,
) -> dict:
    response = await client.post(
        f"/v1/workouts/sessions/{session_id}/exercises/{exercise_entry_id}/sets",
        json=body,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def session_with_bench(
    client: AsyncClient, headers: dict[str, str], bench_id: str
) -> tuple[str, str]:
    session = await start_session(client, headers, name="Push Day")
    added = await client.post(
        f"/v1/workouts/sessions/{session['id']}/exercises",
        json={"exerciseId": bench_id},
        headers=headers,
    )
    assert added.status_code == 201, added.text
    return session["id"], added.json()["exercises"][0]["id"]


class TestSessionLifecycle:
    async def test_start_creates_an_in_progress_session(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        session = await start_session(client, headers, name="Leg Day")
        assert session["status"] == "in_progress"
        assert session["name"] == "Leg Day"
        assert session["totalVolumeKg"] == "0.00"

    async def test_active_session_is_retrievable(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        session = await start_session(client, headers)
        active = await client.get("/v1/workouts/sessions/active", headers=headers)
        assert active.status_code == 200
        assert active.json()["id"] == session["id"]

    async def test_no_active_session_returns_no_content(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.get("/v1/workouts/sessions/active", headers=headers)
        assert response.status_code == 204

    async def test_only_one_workout_can_be_in_progress(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        await start_session(client, headers)
        second = await client.post("/v1/workouts/sessions", json={}, headers=headers)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "conflict"

    async def test_start_is_idempotent_on_client_session_id(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """A double-tapped start on gym Wi-Fi must not create two sessions."""
        client_id = "0192f8e0-7b3a-7c4d-9e2f-1a2b3c4d5e6f"
        first = await start_session(client, headers, clientSessionId=client_id)
        second = await start_session(client, headers, clientSessionId=client_id)
        assert first["id"] == second["id"]

    async def test_discard_frees_the_slot_for_a_new_session(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        session = await start_session(client, headers)
        assert (
            await client.post(f"/v1/workouts/sessions/{session['id']}/discard", headers=headers)
        ).status_code == 204
        assert (
            await client.post("/v1/workouts/sessions", json={}, headers=headers)
        ).status_code == 201

    async def test_discarded_session_stays_out_of_history(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        session = await start_session(client, headers)
        await client.post(f"/v1/workouts/sessions/{session['id']}/discard", headers=headers)
        history = await client.get("/v1/workouts/sessions", headers=headers)
        assert history.json()["items"] == []

    async def test_update_session_metadata(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        session = await start_session(client, headers)
        response = await client.patch(
            f"/v1/workouts/sessions/{session['id']}",
            json={"name": "Renamed", "notes": "felt strong", "perceivedEffort": 9},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"
        assert response.json()["perceivedEffort"] == 9


class TestLoggingSets:
    async def test_log_a_set_and_see_it_on_the_session(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        logged = await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")

        assert logged["setNumber"] == 1
        assert logged["reps"] == 8
        # Epley, computed by the database: 100 x (1 + 8/30).
        assert logged["estimatedOneRepMax"] == "126.67"

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert len(session.json()["exercises"][0]["sets"]) == 1

    async def test_set_numbers_increment(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        first = await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        second = await log_set(client, headers, session_id, entry_id, reps=6, weightKg="105")
        assert (first["setNumber"], second["setNumber"]) == (1, 2)

    async def test_client_supplied_set_id_is_idempotent(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """The same offline set flushed twice must be one row."""
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        set_id = "0192f8e0-7b3a-7c4d-9e2f-aaaaaaaaaaaa"
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100", id=set_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100", id=set_id)

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert len(session.json()["exercises"][0]["sets"]) == 1

    async def test_a_set_must_record_something(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        response = await client.post(
            f"/v1/workouts/sessions/{session_id}/exercises/{entry_id}/sets",
            json={"weightKg": "100"},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_correct_and_delete_a_set(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        logged = await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        base = f"/v1/workouts/sessions/{session_id}/exercises/{entry_id}/sets/{logged['id']}"

        corrected = await client.patch(base, json={"reps": 10}, headers=headers)
        assert corrected.status_code == 200
        assert corrected.json()["reps"] == 10

        assert (await client.delete(base, headers=headers)).status_code == 204
        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert session.json()["exercises"][0]["sets"] == []

    async def test_sets_cannot_be_logged_to_a_finished_session(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        response = await client.post(
            f"/v1/workouts/sessions/{session_id}/exercises/{entry_id}/sets",
            json={"reps": 8, "weightKg": "100"},
            headers=headers,
        )
        assert response.status_code == 409

    async def test_reorder_exercises_atomically(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        squat_id = await exercise_id_for(client, headers, "Back Squat")
        session_id, first_entry = await session_with_bench(client, headers, bench_id)
        added = await client.post(
            f"/v1/workouts/sessions/{session_id}/exercises",
            json={"exerciseId": squat_id},
            headers=headers,
        )
        second_entry = added.json()["exercises"][1]["id"]

        response = await client.put(
            f"/v1/workouts/sessions/{session_id}/exercises/order",
            json={"exerciseIds": [second_entry, first_entry]},
            headers=headers,
        )
        assert response.status_code == 200
        assert [e["id"] for e in response.json()["exercises"]] == [second_entry, first_entry]

    async def test_remove_an_exercise_from_the_session(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        response = await client.delete(
            f"/v1/workouts/sessions/{session_id}/exercises/{entry_id}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["exercises"] == []


class TestCompletionAndRecords:
    async def test_completion_computes_totals(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(
            client, headers, session_id, entry_id, reps=10, weightKg="60", setType="warmup"
        )
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        await log_set(client, headers, session_id, entry_id, reps=6, weightKg="110")

        response = await client.post(
            f"/v1/workouts/sessions/{session_id}/complete",
            json={"perceivedEffort": 8},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        session = response.json()["session"]

        assert session["status"] == "completed"
        # Warm-up excluded: 8x100 + 6x110 = 1460.
        assert session["totalVolumeKg"] == "1460.00"
        assert session["totalSets"] == 2
        assert session["totalReps"] == 14

    async def test_first_workout_sets_personal_records(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")

        response = await client.post(
            f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
        )
        records = {r["recordType"] for r in response.json()["newRecords"]}
        assert records == {"max_weight", "max_reps", "max_volume_set", "est_1rm"}

    async def test_beating_a_record_reports_the_improvement(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=5, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=5, weightKg="105")
        response = await client.post(
            f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
        )

        weight_pr = next(
            r for r in response.json()["newRecords"] if r["recordType"] == "max_weight"
        )
        assert weight_pr["value"] == "105.00"
        assert weight_pr["previousValue"] == "100.00"
        assert weight_pr["improvement"] == "5.00"

    async def test_repeating_a_workout_sets_no_new_records(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """Matching last week is not a PR, or the celebration means nothing."""
        for _ in range(2):
            session_id, entry_id = await session_with_bench(client, headers, bench_id)
            await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
            response = await client.post(
                f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
            )
        assert response.json()["newRecords"] == []

    async def test_warmups_do_not_set_records(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(
            client, headers, session_id, entry_id, reps=1, weightKg="200", setType="warmup"
        )
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")

        response = await client.post(
            f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
        )
        weight_pr = next(
            r for r in response.json()["newRecords"] if r["recordType"] == "max_weight"
        )
        assert weight_pr["value"] == "100.00"

    async def test_records_are_readable_per_exercise(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        response = await client.get(f"/v1/exercises/{bench_id}/records", headers=headers)
        assert response.status_code == 200
        assert {r["recordType"] for r in response.json()} >= {"max_weight", "est_1rm"}

    async def test_completing_twice_is_refused(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """A double-tapped Finish must not compute records twice."""
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")

        first = await client.post(
            f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
        )
        second = await client.post(
            f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
        )
        assert first.status_code == 200
        assert second.status_code == 409

    async def test_completion_updates_the_streak(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        response = await client.post(
            f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
        )
        assert response.json()["streak"]["current"] == 1

    async def test_discarding_restores_the_previous_record(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """Discarding must not cost the user a PR they still hold."""
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=5, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=5, weightKg="120")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        # The 120 kg session is deleted; the 100 kg record must come back as current.
        await client.delete(f"/v1/workouts/sessions/{session_id}", headers=headers)

        records = await client.get(f"/v1/exercises/{bench_id}/records", headers=headers)
        current = [r for r in records.json() if r["isCurrent"] and r["recordType"] == "max_weight"]
        assert len(current) == 1
        assert current[0]["value"] == "100.00"


class TestHistoryAndAggregates:
    async def test_completed_session_appears_in_history(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        history = await client.get("/v1/workouts/sessions", headers=headers)
        items = history.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == session_id
        assert items[0]["exerciseCount"] == 1
        assert items[0]["prCount"] == 4

    async def test_history_pagination_uses_a_cursor(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        for _ in range(3):
            session_id, entry_id = await session_with_bench(client, headers, bench_id)
            await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
            await client.post(
                f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
            )

        first = await client.get("/v1/workouts/sessions", params={"limit": 2}, headers=headers)
        assert first.json()["hasMore"] is True
        cursor = first.json()["nextCursor"]

        second = await client.get(
            "/v1/workouts/sessions", params={"limit": 2, "cursor": cursor}, headers=headers
        )
        first_ids = {i["id"] for i in first.json()["items"]}
        second_ids = {i["id"] for i in second.json()["items"]}
        assert not (first_ids & second_ids)

    async def test_an_invalid_cursor_is_rejected(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.get(
            "/v1/workouts/sessions", params={"cursor": "not-a-cursor"}, headers=headers
        )
        assert response.status_code == 400

    async def test_calendar_reflects_completed_workouts(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        response = await client.get("/v1/workouts/sessions/calendar", headers=headers)
        days = response.json()
        assert len(days) == 1
        assert days[0]["workoutCount"] == 1
        assert days[0]["totalVolumeKg"] == "800.00"

    async def test_two_workouts_in_a_day_accumulate(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        for _ in range(2):
            session_id, entry_id = await session_with_bench(client, headers, bench_id)
            await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
            await client.post(
                f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers
            )

        days = (await client.get("/v1/workouts/sessions/calendar", headers=headers)).json()
        assert days[0]["workoutCount"] == 2
        assert days[0]["totalVolumeKg"] == "1600.00"

    async def test_exercise_history_accumulates_statistics(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        response = await client.get(f"/v1/exercises/{bench_id}/history", headers=headers)
        body = response.json()
        assert body["totalSessions"] == 1
        assert body["totalSets"] == 1
        assert body["totalVolumeKg"] == "800.00"
        assert body["bestEstimatedOneRepMax"] == "126.67"
        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["sets"][0]["reps"] == 8

    async def test_deleting_a_session_backs_it_out_of_the_calendar(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = await session_with_bench(client, headers, bench_id)
        await log_set(client, headers, session_id, entry_id, reps=8, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)
        await client.delete(f"/v1/workouts/sessions/{session_id}", headers=headers)

        days = (await client.get("/v1/workouts/sessions/calendar", headers=headers)).json()
        assert days == [] or days[0]["workoutCount"] == 0


class TestSessionAuthorizationBoundary:
    async def test_one_user_cannot_read_or_write_anothers_session(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        owner = auth_header(
            await register_and_verify(client, email_sender, email="lifter-a@example.com")
        )
        bench = await exercise_id_for(client, owner, "Barbell Bench Press")
        session_id, entry_id = await session_with_bench(client, owner, bench)

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="lifter-b@example.com")
        )

        assert (
            await client.get(f"/v1/workouts/sessions/{session_id}", headers=intruder)
        ).status_code == 404
        assert (
            await client.patch(
                f"/v1/workouts/sessions/{session_id}", json={"name": "x"}, headers=intruder
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/v1/workouts/sessions/{session_id}/exercises/{entry_id}/sets",
                json={"reps": 8, "weightKg": "100"},
                headers=intruder,
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=intruder
            )
        ).status_code == 404
        assert (
            await client.delete(f"/v1/workouts/sessions/{session_id}", headers=intruder)
        ).status_code == 404

    async def test_history_is_scoped_to_the_caller(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        owner = auth_header(
            await register_and_verify(client, email_sender, email="owner-h@example.com")
        )
        bench = await exercise_id_for(client, owner, "Barbell Bench Press")
        session_id, entry_id = await session_with_bench(client, owner, bench)
        await log_set(client, owner, session_id, entry_id, reps=8, weightKg="100")
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=owner)

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="other-h@example.com")
        )
        history = await client.get("/v1/workouts/sessions", headers=intruder)
        assert history.json()["items"] == []


class TestClientClockBounds:
    async def test_a_future_start_time_is_clamped_to_now(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """A phone claiming to be from 2030 must not write a workout into the future."""
        future = (datetime.now(UTC) + timedelta(days=365 * 4)).isoformat()
        session = await start_session(client, headers, startedAt=future)
        started = datetime.fromisoformat(session["startedAt"])
        assert started <= datetime.now(UTC) + timedelta(minutes=1)

    async def test_a_past_start_time_is_honoured(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """Offline sessions genuinely happened in the past."""
        past = (datetime.now(UTC) - timedelta(hours=3)).replace(microsecond=0)
        session = await start_session(client, headers, startedAt=past.isoformat())
        assert datetime.fromisoformat(session["startedAt"]) == past
