"""/v1/workouts/sessions — live logging, history and offline sync.

The performance-critical group. `POST .../sets` is the hottest write in the product and
is deliberately given a generous rate limit: never throttle a lifter mid-workout.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from coresync.application.workout.sessions import (
    AddSessionExerciseCommand,
    AddSessionExerciseUseCase,
    CompleteSessionCommand,
    CompleteSessionUseCase,
    DeleteSessionUseCase,
    DeleteSetUseCase,
    DiscardSessionUseCase,
    GetActiveSessionUseCase,
    GetCalendarUseCase,
    GetSessionUseCase,
    ListHistoryQuery,
    ListSessionHistoryUseCase,
    LogSetCommand,
    LogSetUseCase,
    RemoveSessionExerciseUseCase,
    ReorderSessionExercisesUseCase,
    StartSessionCommand,
    StartSessionUseCase,
    UpdateSessionCommand,
    UpdateSessionExerciseCommand,
    UpdateSessionExerciseUseCase,
    UpdateSessionUseCase,
    UpdateSetCommand,
    UpdateSetUseCase,
)
from coresync.application.workout.sync import (
    SyncBatchCommand,
    SyncOperation,
    SyncWorkoutsUseCase,
)
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.common import ErrorResponse
from coresync.presentation.schemas.exercises import PersonalRecordResponse
from coresync.presentation.schemas.workouts import (
    AddSessionExerciseRequest,
    CalendarDayResponse,
    CompletedSessionResponse,
    CompleteSessionRequest,
    LogSetRequest,
    ReorderExercisesRequest,
    SessionHistoryResponse,
    SessionSetResponse,
    SessionSummaryResponse,
    StartSessionRequest,
    StreakResponse,
    SyncOperationResultResponse,
    SyncRequest,
    SyncResponse,
    UpdateSessionExerciseRequest,
    UpdateSessionRequest,
    UpdateSetRequest,
    WorkoutSessionResponse,
)

router = APIRouter(prefix="/workouts/sessions", tags=["workouts"])


def _session_response(session) -> WorkoutSessionResponse:
    return WorkoutSessionResponse.model_validate(vars(session))


# ------------------------------------------------------------------------- read
@router.get(
    "",
    response_model=SessionHistoryResponse,
    summary="Workout history, cursor-paginated",
    description=(
        "Keyset pagination on (localDate, id). An offset would drift as new sessions land "
        "at the head of the list mid-scroll."
    ),
)
async def list_history(
    user: deps.CurrentUser,
    use_case: Annotated[ListSessionHistoryUseCase, Depends(deps.session_history_use_case)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> SessionHistoryResponse:
    page = await use_case.execute(
        ListHistoryQuery(
            user_id=user.id,
            limit=limit,
            cursor=cursor,
            date_from=date_from,
            date_to=date_to,
        )
    )
    return SessionHistoryResponse(
        items=[SessionSummaryResponse(**vars(row)) for row in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/active",
    response_model=WorkoutSessionResponse | None,
    summary="The workout in progress, if any",
    description="Called on every app resume, so it stays one scoped read.",
)
async def get_active(
    response: Response,
    user: deps.CurrentUser,
    use_case: Annotated[GetActiveSessionUseCase, Depends(deps.active_session_use_case)],
) -> WorkoutSessionResponse | None:
    session = await use_case.execute(user.id)
    if session is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return _session_response(session)


@router.get(
    "/calendar",
    response_model=list[CalendarDayResponse],
    summary="Heatmap data for a date range",
    description="Served from the daily activity aggregate, never by scanning raw sets.",
)
async def calendar(
    user: deps.CurrentUser,
    use_case: Annotated[GetCalendarUseCase, Depends(deps.calendar_use_case)],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[CalendarDayResponse]:
    days = await use_case.execute(user.id, date_from=date_from, date_to=date_to)
    return [CalendarDayResponse(**vars(d)) for d in days]


# ------------------------------------------------------------------ offline sync
@router.post(
    "/sync",
    response_model=SyncResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Bulk offline sync",
    description=(
        "Drains the client's write-ahead log. Operations apply in client order; each is "
        "idempotent on its `opId`, so replaying a batch is always safe. Partial success is "
        "expressible — one bad operation returns `rejected` with a reason and the rest of "
        "the batch still lands."
    ),
)
async def sync(
    body: SyncRequest,
    user: deps.CurrentUser,
    use_case: Annotated[SyncWorkoutsUseCase, Depends(deps.sync_use_case)],
) -> SyncResponse:
    result = await use_case.execute(
        SyncBatchCommand(
            user_id=user.id,
            device_id=body.device_id,
            operations=[
                SyncOperation(op_id=op.op_id, type=op.type, at=op.at, payload=op.payload)
                for op in body.operations
            ],
        )
    )
    return SyncResponse(
        results=[SyncOperationResultResponse(**vars(r)) for r in result.results],
        server_time=result.server_time,
    )


# ------------------------------------------------------------------ session life
@router.post(
    "",
    response_model=WorkoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Start a workout",
    description=(
        "Optionally seeded from a routine. Idempotent on `clientSessionId`, so a "
        "double-tapped start on gym Wi-Fi returns the existing session rather than "
        "creating a second one."
    ),
)
async def start_session(
    body: StartSessionRequest,
    user: deps.CurrentUser,
    use_case: Annotated[StartSessionUseCase, Depends(deps.start_session_use_case)],
) -> WorkoutSessionResponse:
    session = await use_case.execute(
        StartSessionCommand(
            user_id=user.id,
            routine_id=body.routine_id,
            name=body.name,
            notes=body.notes,
            client_session_id=body.client_session_id,
            started_at=body.started_at,
        )
    )
    return _session_response(session)


@router.get(
    "/{session_id}",
    response_model=WorkoutSessionResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Full session with exercises and sets",
)
async def get_session(
    session_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[GetSessionUseCase, Depends(deps.get_session_use_case)],
) -> WorkoutSessionResponse:
    return _session_response(await use_case.execute(user.id, session_id))


@router.patch(
    "/{session_id}",
    response_model=WorkoutSessionResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Update name, notes or perceived effort",
)
async def update_session(
    session_id: UUID,
    body: UpdateSessionRequest,
    user: deps.CurrentUser,
    use_case: Annotated[UpdateSessionUseCase, Depends(deps.update_session_use_case)],
) -> WorkoutSessionResponse:
    session = await use_case.execute(
        UpdateSessionCommand(
            user_id=user.id,
            session_id=session_id,
            name=body.name,
            notes=body.notes,
            perceived_effort=body.perceived_effort,
        )
    )
    return _session_response(session)


@router.post(
    "/{session_id}/complete",
    response_model=CompletedSessionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Finish a workout",
    description=(
        "Computes volume, detects personal records, updates the daily aggregate, the "
        "per-exercise statistics and the streak — all in one transaction. New records come "
        "back with the response so the celebration fires immediately."
    ),
)
async def complete_session(
    session_id: UUID,
    body: CompleteSessionRequest,
    user: deps.CurrentUser,
    use_case: Annotated[CompleteSessionUseCase, Depends(deps.complete_session_use_case)],
) -> CompletedSessionResponse:
    result = await use_case.execute(
        CompleteSessionCommand(
            user_id=user.id,
            session_id=session_id,
            perceived_effort=body.perceived_effort,
            completed_at=body.completed_at,
        )
    )
    return CompletedSessionResponse(
        session=_session_response(result.session),
        new_records=[PersonalRecordResponse(**vars(r)) for r in result.new_records],
        streak=StreakResponse(**vars(result.streak)) if result.streak else None,
    )


@router.post(
    "/{session_id}/discard",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Abandon a workout without saving it to history",
    description=(
        "Any records the session set are removed and whatever they superseded is "
        "restored, so discarding never costs a PR the user still holds."
    ),
)
async def discard_session(
    session_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DiscardSessionUseCase, Depends(deps.discard_session_use_case)],
) -> None:
    await use_case.execute(user.id, session_id)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Soft-delete a completed session",
)
async def delete_session(
    session_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteSessionUseCase, Depends(deps.delete_session_use_case)],
) -> None:
    await use_case.execute(user.id, session_id)


# -------------------------------------------------------------- session contents
@router.post(
    "/{session_id}/exercises",
    response_model=WorkoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Add an exercise to the running session",
)
async def add_exercise(
    session_id: UUID,
    body: AddSessionExerciseRequest,
    user: deps.CurrentUser,
    use_case: Annotated[AddSessionExerciseUseCase, Depends(deps.add_session_exercise_use_case)],
) -> WorkoutSessionResponse:
    session = await use_case.execute(
        AddSessionExerciseCommand(
            user_id=user.id,
            session_id=session_id,
            exercise_id=body.exercise_id,
            superset_group=body.superset_group,
            rest_seconds=body.rest_seconds,
            notes=body.notes,
        )
    )
    return _session_response(session)


@router.put(
    "/{session_id}/exercises/order",
    response_model=WorkoutSessionResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Reorder the session's exercises atomically",
)
async def reorder_exercises(
    session_id: UUID,
    body: ReorderExercisesRequest,
    user: deps.CurrentUser,
    use_case: Annotated[
        ReorderSessionExercisesUseCase, Depends(deps.reorder_session_exercises_use_case)
    ],
) -> WorkoutSessionResponse:
    session = await use_case.execute(user.id, session_id, body.exercise_ids)
    return _session_response(session)


@router.patch(
    "/{session_id}/exercises/{session_exercise_id}",
    response_model=WorkoutSessionResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Update notes, rest seconds or superset group",
)
async def update_exercise(
    session_id: UUID,
    session_exercise_id: UUID,
    body: UpdateSessionExerciseRequest,
    user: deps.CurrentUser,
    use_case: Annotated[
        UpdateSessionExerciseUseCase, Depends(deps.update_session_exercise_use_case)
    ],
) -> WorkoutSessionResponse:
    session = await use_case.execute(
        UpdateSessionExerciseCommand(
            user_id=user.id,
            session_id=session_id,
            session_exercise_id=session_exercise_id,
            rest_seconds=body.rest_seconds,
            notes=body.notes,
            superset_group=body.superset_group,
        )
    )
    return _session_response(session)


@router.delete(
    "/{session_id}/exercises/{session_exercise_id}",
    response_model=WorkoutSessionResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Remove an exercise from the session",
)
async def remove_exercise(
    session_id: UUID,
    session_exercise_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[
        RemoveSessionExerciseUseCase, Depends(deps.remove_session_exercise_use_case)
    ],
) -> WorkoutSessionResponse:
    session = await use_case.execute(user.id, session_id, session_exercise_id)
    return _session_response(session)


@router.post(
    "/{session_id}/exercises/{session_exercise_id}/sets",
    response_model=SessionSetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Log a set",
    description=(
        "The hottest write in the product. Send `id` to name the set client-side so an "
        "offline flush that arrives twice is one row, not two."
    ),
)
async def log_set(
    session_id: UUID,
    session_exercise_id: UUID,
    body: LogSetRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LogSetUseCase, Depends(deps.log_set_use_case)],
) -> SessionSetResponse:
    logged = await use_case.execute(
        LogSetCommand(
            user_id=user.id,
            session_id=session_id,
            session_exercise_id=session_exercise_id,
            set_type=body.set_type,
            reps=body.reps,
            weight_kg=body.weight_kg,
            duration_seconds=body.duration_seconds,
            distance_m=body.distance_m,
            rpe=body.rpe,
            is_completed=body.is_completed,
            set_id=body.id,
            completed_at=body.completed_at,
        )
    )
    return SessionSetResponse(**vars(logged))


@router.patch(
    "/{session_id}/exercises/{session_exercise_id}/sets/{set_id}",
    response_model=SessionSetResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Correct a set",
)
async def update_set(
    session_id: UUID,
    session_exercise_id: UUID,
    set_id: UUID,
    body: UpdateSetRequest,
    user: deps.CurrentUser,
    use_case: Annotated[UpdateSetUseCase, Depends(deps.update_set_use_case)],
) -> SessionSetResponse:
    updated = await use_case.execute(
        UpdateSetCommand(
            user_id=user.id,
            set_id=set_id,
            set_type=body.set_type,
            reps=body.reps,
            weight_kg=body.weight_kg,
            duration_seconds=body.duration_seconds,
            distance_m=body.distance_m,
            rpe=body.rpe,
            is_completed=body.is_completed,
        )
    )
    return SessionSetResponse(**vars(updated))


@router.delete(
    "/{session_id}/exercises/{session_exercise_id}/sets/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Remove a set",
)
async def delete_set(
    session_id: UUID,
    session_exercise_id: UUID,
    set_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteSetUseCase, Depends(deps.delete_set_use_case)],
) -> None:
    await use_case.execute(user.id, set_id)
