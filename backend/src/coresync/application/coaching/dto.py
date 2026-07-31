"""DTOs for the coaching endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConversationDTO:
    id: UUID
    title: str | None
    last_message_at: datetime | None
    message_count: int
    is_archived: bool


@dataclass(frozen=True, slots=True)
class MessageDTO:
    id: UUID
    role: str
    content: str
    created_at: datetime | None
    model: str | None = None
    # Present when triage intercepted the turn, so a client can style it differently
    # from ordinary coaching output.
    safety_category: str | None = None


@dataclass(frozen=True, slots=True)
class ChatReplyDTO:
    conversation_id: UUID
    message: MessageDTO
    tools_used: tuple[str, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class InsightDTO:
    id: UUID
    insight_type: str
    severity: str
    title: str
    body: str
    evidence: dict[str, Any]
    created_at: datetime | None
    acknowledged_at: datetime | None
    feedback: str | None


@dataclass(frozen=True, slots=True)
class UsageDTO:
    """What the user has spent today against their allowance."""

    messages_used: int
    messages_limit: int
    tokens_used: int

    @property
    def messages_remaining(self) -> int:
        return max(0, self.messages_limit - self.messages_used)


@dataclass(frozen=True, slots=True)
class CoachContextDTO:
    """The context bundle, exposed so a user can see what the coach was told.

    Not a debugging affordance: an AI that reasons over your health data should be able
    to show you exactly what it read (docs/10 §7.3).
    """

    today: str
    flags: tuple[str, ...]
    bundle: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportDTO:
    period_start: str
    period_end: str
    title: str
    body: str
    highlights: tuple[str, ...] = ()
    total_volume_kg: Decimal | None = None
