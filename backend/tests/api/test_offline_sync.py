"""The offline sync contract.

The scenario these tests encode is the one from the roadmap's exit criteria: log a full
workout in airplane mode, then reconnect and flush. The phone may flush the same batch
more than once, may be killed mid-flush, and may carry a wrong clock. None of those may
produce a duplicated workout or a lost set.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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


def op(op_type: str, payload: dict, *, at: datetime | None = None) -> dict:
    return {
        "opId": str(uuid4()),
        "type": op_type,
        "at": (at or datetime.now(UTC)).isoformat(),
        "payload": payload,
    }


async def flush(client: AsyncClient, headers: dict[str, str], operations: list[dict]) -> dict:
    response = await client.post(
        "/v1/workouts/sessions/sync",
        json={"deviceId": str(uuid4()), "operations": operations},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def offline_workout(bench_id: str) -> tuple[list[dict], str]:
    """A complete workout as the client's write-ahead log would hold it."""
    session_id = str(uuid4())
    entry_id = str(uuid4())
    started = datetime.now(UTC) - timedelta(hours=1)

    operations = [
        op("session.create", {"id": session_id, "name": "Airplane Mode Push"}, at=started),
        op(
            "exercise.add",
            {"id": entry_id, "sessionId": session_id, "exerciseId": bench_id},
            at=started + timedelta(minutes=1),
        ),
        op(
            "set.log",
            {
                "id": str(uuid4()),
                "sessionId": session_id,
                "sessionExerciseId": entry_id,
                "reps": 8,
                "weightKg": "100",
            },
            at=started + timedelta(minutes=5),
        ),
        op(
            "set.log",
            {
                "id": str(uuid4()),
                "sessionId": session_id,
                "sessionExerciseId": entry_id,
                "reps": 6,
                "weightKg": "110",
            },
            at=started + timedelta(minutes=9),
        ),
        op(
            "session.complete",
            {"id": session_id, "perceivedEffort": 8},
            at=started + timedelta(minutes=45),
        ),
    ]
    return operations, session_id


class TestSyncHappyPath:
    async def test_a_full_offline_workout_lands(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        operations, session_id = offline_workout(bench_id)
        body = await flush(client, headers, operations)

        assert [r["status"] for r in body["results"]] == ["applied"] * 5
        assert body["serverTime"]

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert session.status_code == 200
        stored = session.json()
        assert stored["status"] == "completed"
        # 8x100 + 6x110 = 1460.
        assert stored["totalVolumeKg"] == "1460.00"
        assert len(stored["exercises"][0]["sets"]) == 2

    async def test_completion_returns_the_records_it_set(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """The client needs the PR list to fire its celebration after a flush."""
        operations, _ = offline_workout(bench_id)
        body = await flush(client, headers, operations)

        complete_result = body["results"][-1]["result"]
        records = {r["recordType"] for r in complete_result["newPersonalRecords"]}
        assert records == {"max_weight", "max_reps", "max_volume_set", "est_1rm"}
        assert complete_result["totalVolumeKg"] == "1460.00"

    async def test_the_workout_reaches_history_and_the_calendar(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        operations, session_id = offline_workout(bench_id)
        await flush(client, headers, operations)

        history = await client.get("/v1/workouts/sessions", headers=headers)
        assert [i["id"] for i in history.json()["items"]] == [session_id]

        calendar = await client.get("/v1/workouts/sessions/calendar", headers=headers)
        assert calendar.json()[0]["workoutCount"] == 1


class TestSyncIdempotency:
    async def test_replaying_the_whole_batch_changes_nothing(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        operations, session_id = offline_workout(bench_id)
        await flush(client, headers, operations)

        replay = await flush(client, headers, operations)
        assert [r["status"] for r in replay["results"]] == ["duplicate"] * 5

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert len(session.json()["exercises"][0]["sets"]) == 2
        assert session.json()["totalVolumeKg"] == "1460.00"

        history = await client.get("/v1/workouts/sessions", headers=headers)
        assert len(history.json()["items"]) == 1

    async def test_kill_mid_flush_then_retry_the_whole_log(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """The exit-criteria case: the app dies after some operations landed.

        The client does not know how far it got, so it replays everything. The already
        applied prefix reports duplicate; the remainder applies exactly once.
        """
        operations, session_id = offline_workout(bench_id)

        # First flush dies after the two sets, before the complete.
        partial = await flush(client, headers, operations[:4])
        assert [r["status"] for r in partial["results"]] == ["applied"] * 4

        # The phone restarts and flushes its entire queue again.
        full = await flush(client, headers, operations)
        assert [r["status"] for r in full["results"]] == ["duplicate"] * 4 + ["applied"]

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        stored = session.json()
        assert stored["status"] == "completed"
        assert len(stored["exercises"][0]["sets"]) == 2
        assert stored["totalVolumeKg"] == "1460.00"

    async def test_the_same_set_id_in_two_batches_is_one_set(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """Different opIds naming the same set — a client that regenerated its queue."""
        session_id, entry_id, set_id = str(uuid4()), str(uuid4()), str(uuid4())
        payload = {
            "id": set_id,
            "sessionId": session_id,
            "sessionExerciseId": entry_id,
            "reps": 5,
            "weightKg": "90",
        }
        await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Dupe Test"}),
                op(
                    "exercise.add",
                    {"id": entry_id, "sessionId": session_id, "exerciseId": bench_id},
                ),
                op("set.log", payload),
            ],
        )
        second = await flush(client, headers, [op("set.log", payload)])
        assert second["results"][0]["status"] == "applied"

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert len(session.json()["exercises"][0]["sets"]) == 1

    async def test_session_create_replayed_with_a_new_op_id_is_not_a_second_session(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        session_id = str(uuid4())
        payload = {"id": session_id, "name": "Once Only"}
        await flush(client, headers, [op("session.create", payload)])
        second = await flush(client, headers, [op("session.create", payload)])

        assert second["results"][0]["status"] == "applied"
        assert second["results"][0]["result"]["sessionId"] == session_id


class TestSyncPartialSuccess:
    async def test_one_bad_operation_does_not_reject_the_batch(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = str(uuid4()), str(uuid4())
        operations = [
            op("session.create", {"id": session_id, "name": "Partial"}),
            op("exercise.add", {"id": entry_id, "sessionId": session_id, "exerciseId": bench_id}),
            # References an exercise entry that does not exist.
            op(
                "set.log",
                {
                    "id": str(uuid4()),
                    "sessionId": session_id,
                    "sessionExerciseId": str(uuid4()),
                    "reps": 8,
                    "weightKg": "100",
                },
            ),
            op(
                "set.log",
                {
                    "id": str(uuid4()),
                    "sessionId": session_id,
                    "sessionExerciseId": entry_id,
                    "reps": 8,
                    "weightKg": "100",
                },
            ),
        ]
        body = await flush(client, headers, operations)
        statuses = [r["status"] for r in body["results"]]
        assert statuses == ["applied", "applied", "rejected", "applied"]
        assert body["results"][2]["reason"] == "not_found"

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert len(session.json()["exercises"][0]["sets"]) == 1

    async def test_an_unknown_operation_type_is_rejected_not_fatal(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        session_id = str(uuid4())
        body = await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Unknown Op"}),
                op("nutrition.log", {"id": str(uuid4())}),
            ],
        )
        assert [r["status"] for r in body["results"]] == ["applied", "rejected"]
        assert "unknown operation type" in body["results"][1]["reason"]

    async def test_a_malformed_payload_is_rejected_with_a_reason(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        body = await flush(client, headers, [op("session.create", {"name": "no id"})])
        assert body["results"][0]["status"] == "rejected"
        assert "malformed payload" in body["results"][0]["reason"]

    async def test_a_rejected_operation_can_be_retried_later(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        """Rejected operations are not recorded as applied, so a fixed retry lands."""
        session_id, entry_id = str(uuid4()), str(uuid4())
        set_payload = {
            "id": str(uuid4()),
            "sessionId": session_id,
            "sessionExerciseId": entry_id,
            "reps": 8,
            "weightKg": "100",
        }
        early = op("set.log", set_payload)

        # Arrives before the exercise it belongs to.
        first = await flush(client, headers, [early])
        assert first["results"][0]["status"] == "rejected"

        await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Retry"}),
                op(
                    "exercise.add",
                    {"id": entry_id, "sessionId": session_id, "exerciseId": bench_id},
                ),
            ],
        )
        retry = await flush(client, headers, [early])
        assert retry["results"][0]["status"] == "applied"

    async def test_deleting_an_already_deleted_set_succeeds(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """Deletes are tombstones: a set already gone is success, not a rejection."""
        body = await flush(client, headers, [op("set.delete", {"id": str(uuid4())})])
        assert body["results"][0]["status"] == "applied"


class TestSyncSafety:
    async def test_a_wrong_client_clock_cannot_write_into_the_future(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        session_id = str(uuid4())
        far_future = datetime.now(UTC) + timedelta(days=365 * 4)
        await flush(
            client,
            headers,
            [
                op(
                    "session.create",
                    {
                        "id": session_id,
                        "name": "Time Traveller",
                        "startedAt": far_future.isoformat(),
                    },
                    at=far_future,
                )
            ],
        )
        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        started = datetime.fromisoformat(session.json()["startedAt"])
        assert started <= datetime.now(UTC) + timedelta(minutes=1)

    async def test_sync_cannot_touch_another_users_session(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        owner = auth_header(
            await register_and_verify(client, email_sender, email="sync-owner@example.com")
        )
        bench = await exercise_id_for(client, owner, "Barbell Bench Press")
        operations, session_id = offline_workout(bench)
        await flush(client, owner, operations[:2])

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="sync-intruder@example.com")
        )
        body = await flush(
            client,
            intruder,
            [
                op(
                    "set.log",
                    {
                        "id": str(uuid4()),
                        "sessionId": session_id,
                        "sessionExerciseId": operations[1]["payload"]["id"],
                        "reps": 8,
                        "weightKg": "100",
                    },
                )
            ],
        )
        assert body["results"][0]["status"] == "rejected"
        assert body["results"][0]["reason"] == "not_found"

    async def test_op_ids_are_scoped_per_user(
        self, client: AsyncClient, email_sender: CapturingEmailSender, bench_id: str
    ) -> None:
        """Two devices generating the same opId must not silence one another."""
        first_user = auth_header(
            await register_and_verify(client, email_sender, email="scope-a@example.com")
        )
        second_user = auth_header(
            await register_and_verify(client, email_sender, email="scope-b@example.com")
        )
        shared_op_id = str(uuid4())

        for user in (first_user, second_user):
            body = await flush(
                client,
                user,
                [
                    {
                        "opId": shared_op_id,
                        "type": "session.create",
                        "at": datetime.now(UTC).isoformat(),
                        "payload": {"id": str(uuid4()), "name": "Shared Op Id"},
                    }
                ],
            )
            assert body["results"][0]["status"] == "applied"

    async def test_an_oversized_batch_is_refused(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        operations = [op("set.delete", {"id": str(uuid4())}) for _ in range(501)]
        response = await client.post(
            "/v1/workouts/sessions/sync",
            json={"deviceId": str(uuid4()), "operations": operations},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_an_empty_batch_is_accepted(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        body = await flush(client, headers, [])
        assert body["results"] == []

    async def test_sync_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post("/v1/workouts/sessions/sync", json={"operations": []})
        assert response.status_code == 401


class TestRemovingAndReorderingOffline:
    """Adding the wrong exercise, and putting the list back in the right order.

    Both were reachable online long before they were syncable, which meant the phone
    could not queue them: a user who added squats by mistake in a basement gym had no way
    to take them out again until they had signal.
    """

    @pytest.fixture
    async def squat_id(self, client: AsyncClient, headers: dict[str, str]) -> str:
        return await exercise_id_for(client, headers, "Back Squat")

    async def test_an_exercise_added_by_mistake_can_be_removed_offline(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = str(uuid4()), str(uuid4())
        body = await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Push"}),
                op(
                    "exercise.add",
                    {"id": entry_id, "sessionId": session_id, "exerciseId": bench_id},
                ),
                op("exercise.remove", {"id": entry_id, "sessionId": session_id}),
            ],
        )
        assert [r["status"] for r in body["results"]] == ["applied"] * 3

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert session.json()["exercises"] == []

    async def test_reorder_carries_the_whole_order_not_a_move(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str, squat_id: str
    ) -> None:
        session_id = str(uuid4())
        first, second = str(uuid4()), str(uuid4())
        await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Full body"}),
                op("exercise.add", {"id": first, "sessionId": session_id, "exerciseId": bench_id}),
                op("exercise.add", {"id": second, "sessionId": session_id, "exerciseId": squat_id}),
                op("exercise.order", {"sessionId": session_id, "exerciseIds": [second, first]}),
            ],
        )

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert [e["id"] for e in session.json()["exercises"]] == [second, first]

    async def test_replaying_a_reorder_lands_on_the_same_order(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str, squat_id: str
    ) -> None:
        # The reason the operation carries the full order. A "move up one" replayed after
        # the first application would move the wrong exercise; an absolute order is a
        # statement about the end state, so applying it twice changes nothing.
        session_id = str(uuid4())
        first, second = str(uuid4()), str(uuid4())
        await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Full body"}),
                op("exercise.add", {"id": first, "sessionId": session_id, "exerciseId": bench_id}),
                op("exercise.add", {"id": second, "sessionId": session_id, "exerciseId": squat_id}),
            ],
        )
        order = op("exercise.order", {"sessionId": session_id, "exerciseIds": [second, first]})

        # A distinct opId, so the sync log's idempotency is not what is being tested here
        # — the operation's own shape is.
        await flush(client, headers, [order])
        again = dict(order, opId=str(uuid4()))
        body = await flush(client, headers, [again])

        assert body["results"][0]["status"] == "applied"
        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert [e["id"] for e in session.json()["exercises"]] == [second, first]

    async def test_a_partial_order_is_rejected_rather_than_dropping_exercises(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str, squat_id: str
    ) -> None:
        session_id = str(uuid4())
        first, second = str(uuid4()), str(uuid4())
        await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Full body"}),
                op("exercise.add", {"id": first, "sessionId": session_id, "exerciseId": bench_id}),
                op("exercise.add", {"id": second, "sessionId": session_id, "exerciseId": squat_id}),
            ],
        )
        body = await flush(
            client,
            headers,
            [op("exercise.order", {"sessionId": session_id, "exerciseIds": [first]})],
        )
        assert body["results"][0]["status"] == "rejected"

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert len(session.json()["exercises"]) == 2

    async def test_a_reorder_without_ids_is_rejected_not_a_server_error(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        body = await flush(client, headers, [op("exercise.order", {"sessionId": str(uuid4())})])
        result = body["results"][0]
        assert result["status"] == "rejected"
        assert "exerciseIds" in result["reason"]


class TestPausedTimeSurvivesTheQueue:
    """A pause happens offline, so the only place it can be reported is the flush."""

    async def test_the_recorded_duration_excludes_paused_time(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session_id, entry_id = str(uuid4()), str(uuid4())
        started = datetime.now(UTC) - timedelta(minutes=60)

        await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Interrupted"}, at=started),
                op(
                    "exercise.add",
                    {"id": entry_id, "sessionId": session_id, "exerciseId": bench_id},
                    at=started + timedelta(minutes=1),
                ),
                op(
                    "set.log",
                    {
                        "id": str(uuid4()),
                        "sessionId": session_id,
                        "sessionExerciseId": entry_id,
                        "setNumber": 1,
                        "reps": 8,
                        "weightKg": "80",
                        "isCompleted": True,
                    },
                    at=started + timedelta(minutes=2),
                ),
                op(
                    "session.complete",
                    {
                        "id": session_id,
                        "completedAt": (started + timedelta(minutes=60)).isoformat(),
                        "pausedSeconds": 15 * 60,
                    },
                ),
            ],
        )

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert session.json()["durationSeconds"] == 45 * 60

    async def test_a_completion_without_a_pause_still_uses_wall_clock(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        # The field is additive: a client that predates it sends nothing and gets the
        # behaviour it has always had.
        session_id = str(uuid4())
        started = datetime.now(UTC) - timedelta(minutes=30)

        await flush(
            client,
            headers,
            [
                op("session.create", {"id": session_id, "name": "Straight through"}, at=started),
                op(
                    "session.complete",
                    {
                        "id": session_id,
                        "completedAt": (started + timedelta(minutes=30)).isoformat(),
                    },
                ),
            ],
        )

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert session.json()["durationSeconds"] == 30 * 60


class TestStartingFromARoutineOffline:
    """The client owns the exercise list, so the server must not add its own.

    Starting from a routine online lets the server expand the plan into the session.
    Offline it cannot: the phone needs those exercises on screen immediately, so it
    creates them locally with its own ids and queues an `exercise.add` for each. If the
    flush then also asked the server to seed, every exercise would appear twice — once
    under the server's id and once under the client's.
    """

    @pytest.fixture
    async def routine_id(self, client: AsyncClient, headers: dict[str, str], bench_id: str) -> str:
        response = await client.post(
            "/v1/workouts/routines",
            json={
                "name": "Push A",
                "exercises": [{"exerciseId": bench_id, "sets": [{"targetRepsMin": 8}]}],
            },
            headers=headers,
        )
        assert response.status_code in (200, 201), response.text
        return response.json()["id"]

    async def test_a_routine_workout_logged_offline_has_each_exercise_once(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str, routine_id: str
    ) -> None:
        session_id, entry_id = str(uuid4()), str(uuid4())
        body = await flush(
            client,
            headers,
            [
                op(
                    "session.create",
                    {"id": session_id, "name": "Push A", "routineId": routine_id},
                ),
                op(
                    "exercise.add",
                    {"id": entry_id, "sessionId": session_id, "exerciseId": bench_id},
                ),
            ],
        )
        assert [r["status"] for r in body["results"]] == ["applied", "applied"]

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        exercises = session.json()["exercises"]

        assert len(exercises) == 1, "the routine was seeded on top of the client's own list"
        assert exercises[0]["id"] == entry_id

    async def test_the_routine_is_still_attributed(
        self, client: AsyncClient, headers: dict[str, str], routine_id: str
    ) -> None:
        # Not seeding must not mean forgetting which plan was followed — that link is
        # what "last performed" and routine history are built on.
        session_id = str(uuid4())
        await flush(
            client,
            headers,
            [op("session.create", {"id": session_id, "name": "Push A", "routineId": routine_id})],
        )

        session = await client.get(f"/v1/workouts/sessions/{session_id}", headers=headers)
        assert session.json()["routineId"] == routine_id
