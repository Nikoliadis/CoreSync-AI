"""Offline sync: draining the phone's write-ahead log.

The mobile client logs into local SQLite and appends an operation to a queue. When it
reconnects it flushes the whole queue here, in the order the user performed it. That
means this endpoint must be safe to call with operations it has already seen, in any
quantity, at any time — including immediately after a crash mid-flush.

Four properties make that safe (docs/04 §7):

1. **Client-generated UUIDv7 ids.** The client names the entity; the server accepts the
   name. Re-applying a create is therefore a no-op rather than a duplicate.
2. **``opId`` is the idempotency unit.** Applied ids are recorded, and a replay reports
   ``duplicate`` instead of applying twice.
3. **Partial success is expressible.** One bad operation returns ``rejected`` with a
   reason; the rest of the batch still lands.
4. **Client timestamps are bounded by server time**, so a phone with a wrong clock
   cannot write a workout into the future.

Each operation runs in its own transaction, delegating to the same use cases the online
endpoints call. That costs a transaction per operation, and buys two things worth more:
one failing operation cannot poison the rest of the batch, and there is exactly one
implementation of "log a set" to keep correct.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.workout.dto import (
    SyncOperationResultDTO,
    SyncResultDTO,
)
from coresync.application.workout.sessions import (
    AddSessionExerciseCommand,
    AddSessionExerciseUseCase,
    CompleteSessionCommand,
    CompleteSessionUseCase,
    DeleteSetUseCase,
    DiscardSessionUseCase,
    LogSetCommand,
    LogSetUseCase,
    RemoveSessionExerciseUseCase,
    ReorderSessionExercisesUseCase,
    StartSessionCommand,
    StartSessionUseCase,
    UpdateSessionCommand,
    UpdateSessionUseCase,
    UpdateSetCommand,
    UpdateSetUseCase,
)
from coresync.core.clock import Clock
from coresync.core.errors import AppError, ValidationError
from coresync.core.logging import get_logger

logger = get_logger(__name__)

MAX_OPERATIONS_PER_BATCH = 500

APPLIED = "applied"
DUPLICATE = "duplicate"
REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SyncOperation:
    op_id: UUID
    type: str
    at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SyncBatchCommand:
    user_id: UUID
    device_id: UUID | None
    operations: list[SyncOperation]


class SyncWorkoutsUseCase:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        start_session: StartSessionUseCase,
        update_session: UpdateSessionUseCase,
        add_exercise: AddSessionExerciseUseCase,
        remove_exercise: RemoveSessionExerciseUseCase,
        reorder_exercises: ReorderSessionExercisesUseCase,
        log_set: LogSetUseCase,
        update_set: UpdateSetUseCase,
        delete_set: DeleteSetUseCase,
        complete_session: CompleteSessionUseCase,
        discard_session: DiscardSessionUseCase,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._start_session = start_session
        self._update_session = update_session
        self._add_exercise = add_exercise
        self._remove_exercise = remove_exercise
        self._reorder_exercises = reorder_exercises
        self._log_set = log_set
        self._update_set = update_set
        self._delete_set = delete_set
        self._complete_session = complete_session
        self._discard_session = discard_session
        self._clock = clock

    async def execute(self, cmd: SyncBatchCommand) -> SyncResultDTO:
        if len(cmd.operations) > MAX_OPERATIONS_PER_BATCH:
            raise ValidationError(f"Send at most {MAX_OPERATIONS_PER_BATCH} operations per batch.")

        seen = await self._already_applied(cmd)
        results: list[SyncOperationResultDTO] = []
        applied_ids: list[UUID] = []

        for operation in cmd.operations:
            if operation.op_id in seen:
                results.append(SyncOperationResultDTO(op_id=operation.op_id, status=DUPLICATE))
                continue
            result = await self._apply(cmd.user_id, operation)
            results.append(result)
            if result.status == APPLIED:
                applied_ids.append(operation.op_id)

        # Recorded after the fact. A crash between applying and recording means the
        # operation replays — which is harmless precisely because the client named the
        # entity, so the retry lands on the same row.
        await self._record_applied(cmd, applied_ids)

        logger.info(
            "sync_batch_processed",
            user_id=str(cmd.user_id),
            total=len(cmd.operations),
            applied=len(applied_ids),
            duplicates=sum(1 for r in results if r.status == DUPLICATE),
            rejected=sum(1 for r in results if r.status == REJECTED),
        )
        return SyncResultDTO(results=results, server_time=self._clock.now())

    async def _already_applied(self, cmd: SyncBatchCommand) -> set[UUID]:
        uow: UnitOfWork = self._uow_factory()
        async with uow:
            return await uow.sync_log.seen(cmd.user_id, [o.op_id for o in cmd.operations])

    async def _record_applied(self, cmd: SyncBatchCommand, applied_ids: list[UUID]) -> None:
        if not applied_ids:
            return
        uow: UnitOfWork = self._uow_factory()
        async with uow:
            await uow.sync_log.record(cmd.user_id, cmd.device_id, applied_ids, self._clock.now())
            await uow.commit()

    async def _apply(self, user_id: UUID, operation: SyncOperation) -> SyncOperationResultDTO:
        try:
            handler = self._HANDLERS.get(operation.type)
            if handler is None:
                return SyncOperationResultDTO(
                    op_id=operation.op_id,
                    status=REJECTED,
                    reason=f"unknown operation type '{operation.type}'",
                )
            result = await handler(self, user_id, operation)
            return SyncOperationResultDTO(op_id=operation.op_id, status=APPLIED, result=result)
        except AppError as exc:
            # A rejected operation is data the client has to reconcile, not a server
            # fault: it surfaces the reason so the user can be told what was dropped.
            logger.info(
                "sync_operation_rejected",
                user_id=str(user_id),
                op_type=operation.type,
                error_code=exc.code,
            )
            return SyncOperationResultDTO(op_id=operation.op_id, status=REJECTED, reason=exc.code)
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            return SyncOperationResultDTO(
                op_id=operation.op_id, status=REJECTED, reason=f"malformed payload: {exc}"
            )

    # ------------------------------------------------------------------ handlers
    async def _op_session_create(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        payload = operation.payload
        session = await self._start_session.execute(
            StartSessionCommand(
                user_id=user_id,
                session_id=_uuid(payload, "id"),
                client_session_id=_optional_uuid(payload, "clientSessionId")
                or _uuid(payload, "id"),
                routine_id=_optional_uuid(payload, "routineId"),
                name=payload.get("name"),
                notes=payload.get("notes"),
                started_at=_optional_datetime(payload, "startedAt") or operation.at,
            )
        )
        return {"sessionId": str(session.id)}

    async def _op_session_update(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        payload = operation.payload
        await self._update_session.execute(
            UpdateSessionCommand(
                user_id=user_id,
                session_id=_uuid(payload, "id"),
                name=payload.get("name"),
                notes=payload.get("notes"),
                perceived_effort=_optional_int(payload, "perceivedEffort"),
            )
        )
        return {}

    async def _op_exercise_add(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        payload = operation.payload
        await self._add_exercise.execute(
            AddSessionExerciseCommand(
                user_id=user_id,
                session_id=_uuid(payload, "sessionId"),
                exercise_id=_uuid(payload, "exerciseId"),
                session_exercise_id=_uuid(payload, "id"),
                superset_group=_optional_uuid(payload, "supersetGroup"),
                rest_seconds=_optional_int(payload, "restSeconds"),
                notes=payload.get("notes"),
            )
        )
        return {}

    async def _op_exercise_remove(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        payload = operation.payload
        await self._remove_exercise.execute(
            user_id,
            _uuid(payload, "sessionId"),
            _uuid(payload, "id"),
        )
        return {}

    async def _op_exercise_order(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        """Reorder, sent as the whole resulting order rather than a move.

        A move ("this one, up one place") is only meaningful against the list the client
        had at the time. Replayed after some other operation has landed, it moves the
        wrong exercise. Sending the full order makes the operation idempotent and its
        outcome independent of what else is in the batch — which is the property the
        whole queue depends on.
        """
        payload = operation.payload
        raw = payload.get("exerciseIds")
        if not isinstance(raw, list):
            raise KeyError("missing 'exerciseIds'")
        ordered = [value if isinstance(value, UUID) else UUID(str(value)) for value in raw]
        await self._reorder_exercises.execute(user_id, _uuid(payload, "sessionId"), ordered)
        return {}

    async def _op_set_log(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        payload = operation.payload
        logged = await self._log_set.execute(
            LogSetCommand(
                user_id=user_id,
                session_id=_uuid(payload, "sessionId"),
                session_exercise_id=_uuid(payload, "sessionExerciseId"),
                set_id=_uuid(payload, "id"),
                set_number=_optional_int(payload, "setNumber"),
                set_type=payload.get("setType", "normal"),
                reps=_optional_int(payload, "reps"),
                weight_kg=_optional_decimal(payload, "weightKg"),
                duration_seconds=_optional_int(payload, "durationSeconds"),
                distance_m=_optional_decimal(payload, "distanceM"),
                rpe=_optional_decimal(payload, "rpe"),
                is_completed=bool(payload.get("isCompleted", True)),
                completed_at=_optional_datetime(payload, "completedAt") or operation.at,
            )
        )
        return {
            "setId": str(logged.id),
            "estimatedOneRepMax": _str_or_none(logged.estimated_one_rep_max),
        }

    async def _op_set_update(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        payload = operation.payload
        await self._update_set.execute(
            UpdateSetCommand(
                user_id=user_id,
                set_id=_uuid(payload, "id"),
                set_type=payload.get("setType"),
                reps=_optional_int(payload, "reps"),
                weight_kg=_optional_decimal(payload, "weightKg"),
                duration_seconds=_optional_int(payload, "durationSeconds"),
                distance_m=_optional_decimal(payload, "distanceM"),
                rpe=_optional_decimal(payload, "rpe"),
                is_completed=payload.get("isCompleted"),
            )
        )
        return {}

    async def _op_set_delete(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        # Deletes are tombstones in the client's log, so a delete that syncs after a
        # stale edit still wins. A set already gone is a success, not a rejection.
        try:
            await self._delete_set.execute(user_id, _uuid(operation.payload, "id"))
        except AppError as exc:
            if exc.code != "not_found":
                raise
        return {}

    async def _op_session_complete(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        payload = operation.payload
        completed = await self._complete_session.execute(
            CompleteSessionCommand(
                user_id=user_id,
                session_id=_uuid(payload, "id"),
                perceived_effort=_optional_int(payload, "perceivedEffort"),
                completed_at=_optional_datetime(payload, "completedAt") or operation.at,
                paused_seconds=_optional_int(payload, "pausedSeconds") or 0,
            )
        )
        return {
            "newPersonalRecords": [
                {
                    "exerciseId": str(record.exercise_id),
                    "recordType": record.record_type,
                    "value": str(record.value),
                    "previousValue": _str_or_none(record.previous_value),
                }
                for record in completed.new_records
            ],
            "totalVolumeKg": str(completed.session.total_volume_kg),
            "streak": completed.streak.current if completed.streak else None,
        }

    async def _op_session_discard(self, user_id: UUID, operation: SyncOperation) -> dict[str, Any]:
        await self._discard_session.execute(user_id, _uuid(operation.payload, "id"))
        return {}

    _HANDLERS: ClassVar[
        dict[str, Callable[[SyncWorkoutsUseCase, UUID, SyncOperation], Awaitable[dict[str, Any]]]]
    ] = {
        "session.create": _op_session_create,
        "session.update": _op_session_update,
        "exercise.add": _op_exercise_add,
        "exercise.remove": _op_exercise_remove,
        "exercise.order": _op_exercise_order,
        "set.log": _op_set_log,
        "set.update": _op_set_update,
        "set.delete": _op_set_delete,
        "session.complete": _op_session_complete,
        "session.discard": _op_session_discard,
    }


# ---------------------------------------------------------------- payload coercion
def _uuid(payload: dict[str, Any], key: str) -> UUID:
    value = payload.get(key)
    if value is None:
        raise KeyError(f"missing '{key}'")
    return value if isinstance(value, UUID) else UUID(str(value))


def _optional_uuid(payload: dict[str, Any], key: str) -> UUID | None:
    value = payload.get(key)
    if value is None:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return None if value is None else int(value)


def _optional_decimal(payload: dict[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    if value is None:
        return None
    # str() first: float -> Decimal would carry binary rounding noise into a stored
    # weight, and these numbers are summed into lifetime tonnage.
    return Decimal(str(value))


def _optional_datetime(payload: dict[str, Any], key: str) -> datetime | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _str_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
