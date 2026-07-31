"""Wire schemas for the AI coach."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from coresync.presentation.schemas.common import ApiModel


class SendMessageRequest(ApiModel):
    content: str = Field(min_length=1, max_length=2000)
    # Omitted starts a new conversation. Supplied, it must belong to the caller — the
    # use case checks ownership rather than trusting the id.
    conversation_id: UUID | None = None


class MessageResponse(ApiModel):
    id: UUID
    role: str
    content: str
    created_at: datetime | None = None
    model: str | None = None
    # Set when the turn was intercepted by triage, so a client can present it as
    # support rather than coaching.
    safety_category: str | None = None


class ChatReplyResponse(ApiModel):
    conversation_id: UUID
    message: MessageResponse
    tools_used: list[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ConversationResponse(ApiModel):
    id: UUID
    title: str | None = None
    last_message_at: datetime | None = None
    message_count: int = 0
    is_archived: bool = False


class ConversationListResponse(ApiModel):
    conversations: list[ConversationResponse]


class MessageListResponse(ApiModel):
    conversation_id: UUID
    messages: list[MessageResponse]


class InsightResponse(ApiModel):
    id: UUID
    insight_type: str
    severity: str
    title: str
    body: str
    # The data that justified it. An insight a user cannot interrogate is an assertion.
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    acknowledged_at: datetime | None = None
    feedback: str | None = None


class InsightListResponse(ApiModel):
    insights: list[InsightResponse]


class AcknowledgeInsightRequest(ApiModel):
    feedback: str | None = Field(default=None, pattern="^(helpful|not_helpful)$")


class UsageResponse(ApiModel):
    messages_used: int
    messages_limit: int
    messages_remaining: int
    tokens_used: int


class CoachContextResponse(ApiModel):
    """Exactly what the coach was told, exposed to the user who owns it."""

    today: str
    flags: list[str]
    bundle: dict[str, Any]
