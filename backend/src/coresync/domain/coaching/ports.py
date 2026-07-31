"""Ports for the coaching domain.

The gateway is provider-agnostic on purpose. Azure OpenAI is the first adapter, but the
whole point of the abstraction is that a provider outage, a price change or a better model
elsewhere is an adapter swap rather than a rewrite — and that the coach can be faked
entirely in tests, which is the only way the safety and grounding suites can run
deterministically.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from coresync.domain.coaching.entities import (
    Conversation,
    DailyUsage,
    Insight,
    Message,
    TaskClass,
    ToolCall,
    UsageRecord,
)


# ------------------------------------------------------------------- gateway
@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the model is allowed to call.

    ``parameters`` is a JSON Schema. Note the absence of any user identifier: scoping is
    injected by the executor from the authenticated session and is never a model-supplied
    argument, so the model cannot address another user even if it tries (docs/10 §4).
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """A tool call the model asked for."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    system_prompt: str
    messages: list[dict[str, Any]]
    task_class: TaskClass
    tools: Sequence[ToolSpec] = ()
    max_tokens: int = 1200
    temperature: float = 0.4
    # Set when continuing a tool loop, so the adapter can send tool results back.
    tool_results: Sequence[dict[str, Any]] = ()


@dataclass(frozen=True, slots=True)
class CompletionResponse:
    content: str
    tool_calls: tuple[ToolInvocation, ...] = ()
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    finish_reason: str = "stop"

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass(frozen=True, slots=True)
class CompletionChunk:
    """One streamed fragment. ``is_final`` carries the usage totals."""

    delta: str = ""
    is_final: bool = False
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMGateway(Protocol):
    """The provider boundary.

    Implementations are responsible for retries, timeouts and translating provider errors
    into the shared error types. They are *not* responsible for safety — that is decided
    before and after this call, in code the provider cannot influence.
    """

    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]: ...

    def model_for(self, task_class: TaskClass) -> str:
        """Which model this provider uses for a task class."""
        ...

    def estimate_cost_usd(
        self, *, model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0
    ) -> Decimal: ...


class EmbeddingGateway(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    @property
    def dimensions(self) -> int: ...


class ContentSafetyPort(Protocol):
    """Provider-side content safety, layered after our own guards.

    Optional by design: an outage here must not take the coach down, because our
    deterministic triage and output guard already cover the cases that matter.
    """

    async def is_acceptable(self, text: str) -> bool: ...


# --------------------------------------------------------------- retrieval
@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    id: UUID
    scope: str
    chunk_text: str
    source_type: str
    source_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    similarity: float = 0.0


class KnowledgeRepository(Protocol):
    """Retrieval over the knowledge base and the user's own summaries.

    ``owner_user_id`` is a required parameter, not an optional filter. A missing scope
    here leaks one user's data into another's coaching answer — the worst failure this
    system has — so the signature makes the unscoped query unexpressible (docs/10 §3.2).
    """

    async def search(
        self,
        *,
        embedding: Sequence[float],
        owner_user_id: UUID | None,
        scopes: Sequence[str],
        limit: int,
    ) -> list[KnowledgeChunk]:
        """``owner_user_id=None`` searches global knowledge only, never another user's."""
        ...

    async def add(
        self,
        chunk: KnowledgeChunk,
        embedding: Sequence[float],
        *,
        owner_user_id: UUID | None = None,
    ) -> None:
        """Set ``owner_user_id`` only for ``user_summary`` chunks.

        Global knowledge with an owner, or a user summary without one, is rejected by the
        database — the two halves of the scoping rule are checked in both layers.
        """
        ...


# ------------------------------------------------------------- persistence
class ConversationRepository(Protocol):
    async def get(self, conversation_id: UUID, user_id: UUID) -> Conversation | None: ...

    async def list_for_user(self, user_id: UUID, *, limit: int) -> list[Conversation]: ...

    async def add(self, conversation: Conversation) -> None: ...

    async def update(self, conversation: Conversation) -> None: ...

    async def delete(self, conversation_id: UUID, user_id: UUID) -> None: ...


class MessageRepository(Protocol):
    async def list_for_conversation(
        self, conversation_id: UUID, *, limit: int, before: datetime | None = None
    ) -> list[Message]: ...

    async def recent_for_context(self, conversation_id: UUID, *, limit: int) -> list[Message]:
        """The tail of the thread, oldest first, for prompt assembly."""
        ...

    async def add(self, message: Message) -> None: ...

    async def add_tool_calls(self, calls: Sequence[ToolCall]) -> None: ...


class InsightRepository(Protocol):
    async def list_active(self, user_id: UUID) -> list[Insight]: ...

    async def get(self, insight_id: UUID, user_id: UUID) -> Insight | None: ...

    async def add_many(self, insights: Sequence[Insight]) -> None: ...

    async def update(self, insight: Insight) -> None: ...

    async def recent_types(self, user_id: UUID, *, since: date) -> set[str]:
        """Insight types already raised recently.

        Used to suppress repeats: the same plateau warning three weeks running is noise,
        and noise is how users learn to ignore the coach.
        """
        ...


class UsageRepository(Protocol):
    async def record(self, usage: UsageRecord, *, local_date: date | None = None) -> None:
        """``local_date`` is the *user's* day, so a quota resets at their midnight."""
        ...

    async def daily_usage(self, user_id: UUID, on: date) -> DailyUsage: ...
