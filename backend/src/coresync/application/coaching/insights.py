"""Proactive insights.

The division of labour is the whole design: **code finds the pattern, the model phrases
it**. A model asked to find problems in a wall of JSON invents them inconsistently, which
is precisely how an insight feed becomes noise users learn to ignore. Detection is
deterministic and unit-testable; only the wording is generated, and even that degrades to
a written fallback when the provider is unavailable (docs/10 §8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from coresync.application.coaching.context_assembler import ContextAssembler
from coresync.application.coaching.dto import InsightDTO
from coresync.application.coaching.prompts import build_insight_prompt
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError, ValidationError
from coresync.domain.coaching.context import CoachContext, ContextFlag
from coresync.domain.coaching.entities import (
    Insight,
    InsightSeverity,
    InsightType,
    TaskClass,
    UsageRecord,
)
from coresync.domain.coaching.ports import CompletionRequest, LLMGateway
from coresync.domain.coaching.safety import OutputGuard

logger = structlog.get_logger(__name__)

FEATURE = "insights"
# The same observation three weeks running is noise. Repeats of a type are suppressed
# within this window.
SUPPRESSION_DAYS = 14
MAX_PER_RUN = 3
_VALID_FEEDBACK = ("helpful", "not_helpful")


def insight_dto(insight: Insight) -> InsightDTO:
    return InsightDTO(
        id=insight.id,
        insight_type=insight.insight_type.value,
        severity=insight.severity.value,
        title=insight.title,
        body=insight.body,
        evidence=insight.evidence,
        created_at=insight.created_at,
        acknowledged_at=insight.acknowledged_at,
        feedback=insight.feedback,
    )


@dataclass(frozen=True, slots=True)
class DetectedPattern:
    """What the deterministic pass found, before any wording exists."""

    insight_type: InsightType
    severity: InsightSeverity
    observation: str
    evidence: dict[str, Any]
    fallback_title: str
    fallback_body: str


# Each flag maps to at most one insight. Flags with no entry — NUTRITION_NOT_TRACKED, for
# instance — are context for the chat coach, not something worth interrupting someone
# over.
def detect_patterns(context: CoachContext) -> list[DetectedPattern]:
    patterns: list[DetectedPattern] = []
    flags = set(context.flags)

    if ContextFlag.SQUAT_PLATEAU in flags and context.stalled_exercises:
        stalled = context.stalled_exercises[0]
        patterns.append(
            DetectedPattern(
                insight_type=InsightType.PLATEAU,
                severity=InsightSeverity.SUGGESTION,
                observation=(
                    f"{stalled.exercise} has not produced a new best in "
                    f"{stalled.weeks_without_progress} weeks despite regular training."
                ),
                evidence={
                    "exercise": stalled.exercise,
                    "weeksWithoutProgress": stalled.weeks_without_progress,
                    "lastBestEst1rm": str(stalled.last_best_est_1rm)
                    if stalled.last_best_est_1rm
                    else None,
                },
                fallback_title=f"{stalled.exercise} has stalled",
                fallback_body=(
                    f"No new best on {stalled.exercise} in "
                    f"{stalled.weeks_without_progress} weeks. Try dropping to 85% for a "
                    f"week, then building back — a small deload often restarts progress "
                    f"faster than pushing through."
                ),
            )
        )

    if ContextFlag.OVERREACHING in flags:
        week = context.training_7d
        patterns.append(
            DetectedPattern(
                insight_type=InsightType.OVERREACHING,
                severity=InsightSeverity.WARNING,
                observation=(
                    f"This week's volume ({week.total_volume_kg}kg across "
                    f"{week.sessions} sessions) is well above the 30-day average."
                ),
                evidence={
                    "weekVolumeKg": str(week.total_volume_kg),
                    "monthVolumeKg": str(context.training_30d.total_volume_kg),
                    "weekSessions": week.sessions,
                },
                fallback_title="Volume spiked this week",
                fallback_body=(
                    f"You moved {week.total_volume_kg}kg this week, well above your "
                    f"recent average. That is how progress happens and also how injuries "
                    f"do — keep next week closer to your usual and let it consolidate."
                ),
            )
        )

    if ContextFlag.VOLUME_IMBALANCE in flags:
        volumes = context.training_7d.volume_by_muscle_group
        if volumes:
            neglected = min(volumes, key=lambda group: volumes[group])
            patterns.append(
                DetectedPattern(
                    insight_type=InsightType.VOLUME_IMBALANCE,
                    severity=InsightSeverity.SUGGESTION,
                    observation=f"{neglected} is getting far less work than everything else.",
                    evidence={
                        "neglectedGroup": neglected,
                        "volumeByMuscleGroup": {k: str(v) for k, v in volumes.items()},
                    },
                    fallback_title=f"{neglected} is falling behind",
                    fallback_body=(
                        f"Your {neglected} work is a small fraction of this week's "
                        f"training. Adding two or three sets to one session is usually "
                        f"enough to keep it from becoming a weak link."
                    ),
                )
            )

    if ContextFlag.STREAK_AT_RISK in flags and context.workout_streak > 0:
        patterns.append(
            DetectedPattern(
                insight_type=InsightType.STREAK_RISK,
                severity=InsightSeverity.INFO,
                observation=(
                    f"A {context.workout_streak}-week streak with "
                    f"{context.days_since_last_workout} days since the last session."
                ),
                evidence={
                    "streak": context.workout_streak,
                    "daysSinceLastWorkout": context.days_since_last_workout,
                },
                fallback_title=f"{context.workout_streak}-week streak on the line",
                fallback_body=(
                    "You have not trained in a couple of days and your streak is at "
                    "risk. Even a short session counts — consistency beats intensity "
                    "over a year."
                ),
            )
        )

    return patterns[:MAX_PER_RUN]


class GenerateInsightsUseCase:
    """Runs the detectors, then asks the model only to phrase what was found."""

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        gateway: LLMGateway | None,
        assembler: ContextAssembler,
        clock: Clock,
        guard: OutputGuard | None = None,
    ) -> None:
        self._uow = uow
        self._gateway = gateway
        self._assembler = assembler
        self._clock = clock
        self._guard = guard or OutputGuard()

    async def execute(self, user_id: UUID, *, today: date | None = None) -> list[InsightDTO]:
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            on = today or local_date_for(self._clock.now(), user.timezone)

            context = await self._assembler.build(user_id, today=on)
            patterns = detect_patterns(context)
            if not patterns:
                return []

            recent = await self._uow.insights.recent_types(
                user_id, since=on - timedelta(days=SUPPRESSION_DAYS)
            )
            fresh = [p for p in patterns if p.insight_type.value not in recent]
            if not fresh:
                return []

            insights: list[Insight] = []
            for pattern in fresh:
                title, body = await self._phrase(pattern, context, user_id, today=on)
                insights.append(
                    Insight.create(
                        user_id=user_id,
                        insight_type=pattern.insight_type,
                        severity=pattern.severity,
                        title=title,
                        body=body,
                        evidence=pattern.evidence,
                    )
                )

            await self._uow.insights.add_many(insights)
            await self._uow.commit()
            return [insight_dto(i) for i in insights]

    async def _phrase(
        self, pattern: DetectedPattern, context: CoachContext, user_id: UUID, *, today: date
    ) -> tuple[str, str]:
        """Model wording, with the hand-written version as the floor.

        The fallback is not an error path — it is a perfectly good insight. The model
        makes it warmer and more specific; it is never the reason the insight exists.
        """
        if self._gateway is None:
            return pattern.fallback_title, pattern.fallback_body

        prompt = build_insight_prompt(
            context,
            observation=pattern.observation,
            evidence=json.dumps(pattern.evidence, default=str),
        )
        try:
            response = await self._gateway.complete(
                CompletionRequest(
                    system_prompt=prompt,
                    messages=[{"role": "user", "content": "Write it."}],
                    # The cheap tier: phrasing a known observation is a mechanical task.
                    task_class=TaskClass.SUMMARISATION,
                    max_tokens=300,
                    temperature=0.6,
                )
            )
        except Exception:
            logger.warning("insight_generation_failed", insight=pattern.insight_type.value)
            return pattern.fallback_title, pattern.fallback_body

        await self._meter(user_id, response_model=response.model, response=response, today=today)

        if self._guard.inspect(response.content).must_regenerate:
            logger.warning("insight_output_blocked", insight=pattern.insight_type.value)
            return pattern.fallback_title, pattern.fallback_body

        try:
            parsed = json.loads(_strip_fences(response.content))
            title = str(parsed["title"]).strip()[:200]
            body = str(parsed["body"]).strip()
        except (json.JSONDecodeError, KeyError, TypeError):
            return pattern.fallback_title, pattern.fallback_body

        if not title or not body:
            return pattern.fallback_title, pattern.fallback_body
        return title, body

    async def _meter(
        self, user_id: UUID, *, response_model: str, response: Any, today: date
    ) -> None:
        if self._gateway is None:
            return
        cost = self._gateway.estimate_cost_usd(
            model=response_model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            cached_tokens=response.cached_tokens,
        )
        await self._uow.ai_usage.record(
            UsageRecord.create(
                user_id=user_id,
                # Not "chat": background generation is our cost, and charging it against
                # the user's message allowance would silently shrink what they were sold.
                feature=FEATURE,
                provider="azure_openai",
                model=response_model,
                task_class=TaskClass.SUMMARISATION,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                cached_tokens=response.cached_tokens,
                cost_usd=cost,
            ),
            local_date=today,
        )


def _strip_fences(content: str) -> str:
    """Models wrap JSON in ```json fences often enough to be worth handling."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


class ListInsightsUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> list[InsightDTO]:
        async with self._uow:
            active = await self._uow.insights.list_active(user_id)
        return [insight_dto(i) for i in active]


class AcknowledgeInsightUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, insight_id: UUID, user_id: UUID, *, feedback: str | None = None
    ) -> InsightDTO:
        if feedback is not None and feedback not in _VALID_FEEDBACK:
            raise ValidationError(f"feedback must be one of {list(_VALID_FEEDBACK)}")

        async with self._uow:
            insight = await self._uow.insights.get(insight_id, user_id)
            if insight is None:
                raise NotFoundError("That insight does not exist.")

            insight.acknowledge(datetime.now(tz=UTC))
            if feedback is not None:
                # Feedback is the only measurement of the 85% precision gate that comes
                # from real users rather than a fixture.
                insight.feedback = feedback
            await self._uow.insights.update(insight)
            await self._uow.commit()
            return insight_dto(insight)
