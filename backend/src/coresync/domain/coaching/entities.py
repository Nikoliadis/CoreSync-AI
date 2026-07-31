"""Coaching entities: conversations, messages, tool calls, insights and usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from coresync.core.ids import uuid7


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class TaskClass(StrEnum):
    """What a call is for, which decides which model answers it.

    Roughly 60% of calls are the cheap path, and that split is the single largest cost
    lever after pre-computed context (docs/10 §9).
    """

    CLASSIFICATION = "classification"
    SUMMARISATION = "summarisation"
    CHAT = "chat"
    REPORT = "report"
    VISION = "vision"
    EMBEDDING = "embedding"


class InsightType(StrEnum):
    PLATEAU = "plateau"
    DEFICIT_MISMATCH = "deficit_mismatch"
    LOW_PROTEIN = "low_protein"
    VOLUME_IMBALANCE = "volume_imbalance"
    OVERREACHING = "overreaching"
    STREAK_RISK = "streak_risk"


class InsightSeverity(StrEnum):
    INFO = "info"
    SUGGESTION = "suggestion"
    WARNING = "warning"


@dataclass(slots=True)
class Conversation:
    """A thread with the coach.

    ``summary`` is a rolling précis of older messages, so a 200-message relationship still
    costs a couple of thousand context tokens instead of growing without bound
    (docs/03 §8).
    """

    id: UUID
    user_id: UUID
    title: str | None = None
    summary: str | None = None
    last_message_at: datetime | None = None
    message_count: int = 0
    is_archived: bool = False

    @classmethod
    def start(cls, *, user_id: UUID, title: str | None = None) -> Conversation:
        return cls(id=uuid7(), user_id=user_id, title=title)

    def is_owned_by(self, user_id: UUID) -> bool:
        return self.user_id == user_id


@dataclass(slots=True)
class Message:
    """One turn.

    ``context_snapshot`` records the assembled bundle that produced an assistant reply, so
    "why did the coach say that?" is answerable months later — mandatory for a
    health-adjacent product (docs/03 §8).
    """

    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str | None = None
    prompt_version: str | None = None
    safety_category: str | None = None
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        conversation_id: UUID,
        role: MessageRole,
        content: str,
        context_snapshot: dict[str, Any] | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        model: str | None = None,
        prompt_version: str | None = None,
        safety_category: str | None = None,
    ) -> Message:
        return cls(
            id=uuid7(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            context_snapshot=context_snapshot or {},
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
            prompt_version=prompt_version,
            safety_category=safety_category,
        )

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class ToolCall:
    """A recorded tool invocation.

    Every call is stored with its arguments. This is the audit trail that makes a coaching
    answer reconstructable, and the thing that would show an injection attempt having
    reached the tool layer (docs/10 §4).
    """

    id: UUID
    message_id: UUID
    tool_name: str
    arguments: dict[str, Any]
    result_summary: str | None = None
    result_bytes: int = 0
    duration_ms: int = 0
    is_error: bool = False
    error_code: str | None = None

    @classmethod
    def create(
        cls,
        *,
        message_id: UUID,
        tool_name: str,
        arguments: dict[str, Any],
        result_summary: str | None = None,
        result_bytes: int = 0,
        duration_ms: int = 0,
        is_error: bool = False,
        error_code: str | None = None,
    ) -> ToolCall:
        return cls(
            id=uuid7(),
            message_id=message_id,
            tool_name=tool_name,
            arguments=arguments,
            result_summary=result_summary,
            result_bytes=result_bytes,
            duration_ms=duration_ms,
            is_error=is_error,
            error_code=error_code,
        )


@dataclass(slots=True)
class Insight:
    """A proactive observation, generated asynchronously and stored.

    ``evidence`` holds the data that justified it. An insight a user cannot interrogate is
    an assertion, and a false plateau alert erodes trust faster than silence does
    (docs/10 §8).
    """

    id: UUID
    user_id: UUID
    insight_type: InsightType
    severity: InsightSeverity
    title: str
    body: str
    evidence: dict[str, Any] = field(default_factory=dict)
    acknowledged_at: datetime | None = None
    feedback: str | None = None
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        insight_type: InsightType,
        severity: InsightSeverity,
        title: str,
        body: str,
        evidence: dict[str, Any] | None = None,
    ) -> Insight:
        return cls(
            id=uuid7(),
            user_id=user_id,
            insight_type=insight_type,
            severity=severity,
            title=title,
            body=body,
            evidence=evidence or {},
        )

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None

    def acknowledge(self, at: datetime) -> None:
        self.acknowledged_at = at


@dataclass(slots=True)
class UsageRecord:
    """Per-call token and cost metering.

    Drives free-tier enforcement, per-user cost dashboards and abuse detection. Recorded
    for failures too — a provider erroring after consuming prompt tokens still costs
    money (docs/03 §8).
    """

    id: UUID
    user_id: UUID
    feature: str
    provider: str
    model: str
    task_class: TaskClass
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    status: str = "ok"
    error_code: str | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        feature: str,
        provider: str,
        model: str,
        task_class: TaskClass,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        cost_usd: Decimal = Decimal("0"),
        latency_ms: int = 0,
        status: str = "ok",
        error_code: str | None = None,
    ) -> UsageRecord:
        return cls(
            id=uuid7(),
            user_id=user_id,
            feature=feature,
            provider=provider,
            model=model,
            task_class=task_class,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
        )


@dataclass(frozen=True, slots=True)
class DailyUsage:
    """A user's spend so far today, for quota enforcement."""

    user_id: UUID
    local_date: date
    message_count: int
    total_tokens: int
    cost_usd: Decimal
