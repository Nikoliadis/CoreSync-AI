"""The tools the coach may call.

Three rules govern this module, and all three exist because a language model is an
untrusted caller (docs/10 §4):

1. **Allow-list.** A tool the registry does not know is not executed. There is no dynamic
   dispatch on a model-supplied name.
2. **Server-injected scope.** ``user_id`` comes from the authenticated session and is
   never a tool parameter. The schemas below contain no user identifier, so a model
   cannot address another user's data even if it is talked into trying.
3. **Read-only.** Nothing here writes. A prompt-injected "log 500kg to my bench" has
   nothing to call.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.domain.catalog.repositories import ExerciseFilter
from coresync.domain.coaching.ports import ToolSpec

logger = structlog.get_logger(__name__)

# Caps on what a single tool call may return. A model handed 400 sessions will either
# time out or produce worse answers than one handed 20; both are worse than a truncated
# result the model knows is truncated.
_MAX_ROWS = 20
_MAX_HISTORY_DAYS = 365


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a tool is allowed to know. Note that the caller cannot supply it."""

    uow: UnitOfWork
    user_id: UUID
    today: date


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler


@dataclass(frozen=True, slots=True)
class ToolResult:
    name: str
    payload: dict[str, Any]
    duration_ms: int
    # Kept so the persisted call records what the model actually asked for. An audit
    # trail without the arguments cannot answer the question it exists for.
    arguments: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    error_code: str | None = None

    @property
    def summary(self) -> str:
        """A short description for the audit trail, not the model's copy of the data."""
        if self.is_error:
            return f"error:{self.error_code}"
        return ",".join(f"{k}={_describe(v)}" for k, v in list(self.payload.items())[:4])


def _describe(value: Any) -> str:
    if isinstance(value, list):
        return f"[{len(value)}]"
    if isinstance(value, dict):
        return f"{{{len(value)}}}"
    return str(value)[:40]


def _clamp_days(arguments: dict[str, Any], default: int) -> int:
    raw = arguments.get("days", default)
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(days, _MAX_HISTORY_DAYS))


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


# --------------------------------------------------------------------- tools
async def _get_workout_history(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    days = _clamp_days(arguments, 30)
    start = ctx.today - timedelta(days=days - 1)
    calendar = await ctx.uow.summaries.range(ctx.user_id, date_from=start, date_to=ctx.today)
    trained = [day for day in calendar if day.workout_count > 0][-_MAX_ROWS:]
    return {
        "days": days,
        "sessions": [
            {
                "date": day.local_date.isoformat(),
                "workouts": day.workout_count,
                "volumeKg": str(day.total_volume_kg),
                "sets": day.total_sets,
                "durationMin": day.duration_seconds // 60,
            }
            for day in trained
        ],
    }


async def _get_exercise_progress(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("exercise_name", "")).strip()
    if not name:
        return {"error": "exercise_name is required"}

    matches, _ = await ctx.uow.exercises.search(
        ctx.user_id, ExerciseFilter(query=name), limit=1, offset=0
    )
    if not matches:
        return {"exercise": name, "found": False}

    exercise = matches[0]
    days = _clamp_days(arguments, 90)
    history = await ctx.uow.sessions.exercise_history(ctx.user_id, exercise.id, limit=_MAX_ROWS)
    cutoff = ctx.today - timedelta(days=days)
    recent = [entry for entry in history if entry.local_date >= cutoff]

    stats = await ctx.uow.exercise_stats.get_many(ctx.user_id, [exercise.id])
    stat = stats.get(exercise.id)
    return {
        "exercise": exercise.name,
        "found": True,
        "totalSessions": stat.total_sessions if stat else 0,
        "bestEst1rm": _money(stat.best_est_1rm) if stat else None,
        "lastPerformed": stat.last_performed_on.isoformat()
        if stat and stat.last_performed_on
        else None,
        "recentSessions": [
            {
                "date": entry.local_date.isoformat(),
                "sets": len(entry.sets),
                "volumeKg": str(entry.total_volume_kg),
            }
            for entry in recent
        ],
    }


async def _get_weight_history(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    days = _clamp_days(arguments, 90)
    start = ctx.today - timedelta(days=days - 1)
    logs = await ctx.uow.weights.list_range(ctx.user_id, start, ctx.today)
    # Thinned to the most recent entries: the trend is already in the context bundle, and
    # the model needs the shape of the series, not every weigh-in.
    recent = logs[-_MAX_ROWS:]
    return {
        "days": days,
        "entries": [
            {
                "date": log.local_date.isoformat(),
                "weightKg": str(log.weight_kg),
                "trendKg": _money(log.trend_weight_kg),
            }
            for log in recent
        ],
    }


async def _get_personal_records(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    records = await ctx.uow.records.list_current(ctx.user_id)
    if not records:
        return {"records": []}
    names = {
        e.id: e.name
        for e in await ctx.uow.exercises.get_many(
            list({r.exercise_id for r in records}), ctx.user_id
        )
    }
    ordered = sorted(records, key=lambda r: r.achieved_on, reverse=True)[:_MAX_ROWS]
    return {
        "records": [
            {
                "exercise": names.get(r.exercise_id, "unknown"),
                "type": r.record_type.value,
                "value": str(r.value),
                "reps": r.reps_at_value,
                "achievedOn": r.achieved_on.isoformat(),
            }
            for r in ordered
        ]
    }


async def _get_body_measurements(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    latest = await ctx.uow.measurements.get_latest(ctx.user_id)
    if latest is None:
        return {"measurements": None}
    return {
        "measurements": {
            "date": latest.local_date.isoformat(),
            "sites": {site.value: str(value) for site, value in latest.sites.items()},
        }
    }


async def _get_routines(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    routines = await ctx.uow.routines.list_for_user(ctx.user_id)
    return {
        "routines": [
            {
                "name": routine.name,
                "exerciseCount": len(routine.exercises),
                "lastPerformed": routine.last_performed_at.date().isoformat()
                if routine.last_performed_at
                else None,
            }
            for routine in routines[:_MAX_ROWS]
        ]
    }


_DAYS_PARAM = {
    "type": "integer",
    "description": f"How many days back to look (1-{_MAX_HISTORY_DAYS}).",
    "minimum": 1,
    "maximum": _MAX_HISTORY_DAYS,
}

# Note the absence of any user identifier in every schema below. That is the point.
_TOOLS: tuple[RegisteredTool, ...] = (
    RegisteredTool(
        ToolSpec(
            name="get_workout_history",
            description="Recent training sessions with volume, sets and duration per day.",
            parameters={"type": "object", "properties": {"days": _DAYS_PARAM}},
        ),
        _get_workout_history,
    ),
    RegisteredTool(
        ToolSpec(
            name="get_exercise_progress",
            description=(
                "History and best estimated 1RM for one exercise, found by name. "
                "Use when asked about a specific lift."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "exercise_name": {
                        "type": "string",
                        "description": "Exercise name, e.g. 'barbell back squat'.",
                    },
                    "days": _DAYS_PARAM,
                },
                "required": ["exercise_name"],
            },
        ),
        _get_exercise_progress,
    ),
    RegisteredTool(
        ToolSpec(
            name="get_weight_history",
            description="Body-weight log with the smoothed trend value for each entry.",
            parameters={"type": "object", "properties": {"days": _DAYS_PARAM}},
        ),
        _get_weight_history,
    ),
    RegisteredTool(
        ToolSpec(
            name="get_personal_records",
            description="Current personal records across all exercises.",
            parameters={"type": "object", "properties": {}},
        ),
        _get_personal_records,
    ),
    RegisteredTool(
        ToolSpec(
            name="get_body_measurements",
            description="The most recent body measurements, in centimetres.",
            parameters={"type": "object", "properties": {}},
        ),
        _get_body_measurements,
    ),
    RegisteredTool(
        ToolSpec(
            name="get_routines",
            description="The user's saved routines and when each was last performed.",
            parameters={"type": "object", "properties": {}},
        ),
        _get_routines,
    ),
)

_BY_NAME: dict[str, RegisteredTool] = {tool.spec.name: tool for tool in _TOOLS}


class ToolRegistry:
    """Executes allow-listed tools with server-supplied scope."""

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec for tool in _TOOLS)

    def is_known(self, name: str) -> bool:
        return name in _BY_NAME

    async def execute(
        self, name: str, arguments: dict[str, Any], *, context: ToolContext
    ) -> ToolResult:
        started = time.monotonic()
        tool = _BY_NAME.get(name)
        if tool is None:
            # Logged rather than raised: an unknown tool name is a signal worth keeping,
            # and the model handles the error message better than a dropped turn.
            logger.warning("unknown_tool_requested", tool=name, user_id=str(context.user_id))
            return ToolResult(
                name=name,
                payload={"error": "unknown tool"},
                duration_ms=0,
                arguments=arguments,
                is_error=True,
                error_code="unknown_tool",
            )

        try:
            payload = await tool.handler(context, arguments)
        except Exception as exc:
            # One failing tool must not lose the whole answer; the model is told the call
            # failed and can respond without it.
            logger.exception("tool_failed", tool=name)
            return ToolResult(
                name=name,
                payload={"error": "tool failed"},
                duration_ms=int((time.monotonic() - started) * 1000),
                arguments=arguments,
                is_error=True,
                error_code=type(exc).__name__,
            )

        return ToolResult(
            name=name,
            payload=payload,
            duration_ms=int((time.monotonic() - started) * 1000),
            arguments=arguments,
        )
