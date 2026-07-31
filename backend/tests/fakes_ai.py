"""Test doubles for the AI provider.

A scripted gateway rather than a recorded one. The safety, tool-loop and cost tests need
to assert on exact behaviour for an exact model output, including outputs a real provider
would rarely produce — an unsafe calorie number, a leaked system prompt, a call to a tool
that does not exist. Those are the cases that matter, and they are unreachable with a
live model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from decimal import Decimal

from coresync.domain.coaching.entities import TaskClass
from coresync.domain.coaching.ports import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    ToolInvocation,
)
from coresync.infrastructure.external.llm.router import estimate_cost_usd


class ScriptedGateway:
    """Returns queued responses in order, recording every request it received."""

    def __init__(self, responses: Sequence[CompletionResponse] | None = None) -> None:
        self._queue: list[CompletionResponse] = list(responses or [])
        self.requests: list[CompletionRequest] = []
        self.failure: Exception | None = None

    def queue(self, response: CompletionResponse) -> ScriptedGateway:
        self._queue.append(response)
        return self

    def fail_with(self, error: Exception) -> ScriptedGateway:
        self.failure = error
        return self

    @property
    def call_count(self) -> int:
        return len(self.requests)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        if not self._queue:
            return CompletionResponse(content="ok", model="gpt-4o-mini")
        return self._queue.pop(0)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        response = await self.complete(request)
        yield CompletionChunk(delta=response.content, model=response.model)
        yield CompletionChunk(
            is_final=True,
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    def model_for(self, task_class: TaskClass) -> str:
        return "gpt-4o" if task_class is TaskClass.CHAT else "gpt-4o-mini"

    def estimate_cost_usd(
        self, *, model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0
    ) -> Decimal:
        # The real pricing function: cost assertions should break when pricing logic
        # breaks, not agree with a second wrong implementation.
        return estimate_cost_usd(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )


def reply(
    content: str, *, prompt_tokens: int = 100, completion_tokens: int = 50, model: str = "gpt-4o"
) -> CompletionResponse:
    return CompletionResponse(
        content=content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def tool_request(
    name: str, arguments: dict[str, object], *, call_id: str = "call-1"
) -> CompletionResponse:
    return CompletionResponse(
        content="",
        tool_calls=(ToolInvocation(call_id=call_id, name=name, arguments=arguments),),
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=20,
        finish_reason="tool_calls",
    )


class StubEmbeddingGateway:
    """Deterministic vectors, so retrieval ordering is assertable."""

    def __init__(self, dimensions: int = 1536) -> None:
        self._dimensions = dimensions
        self.calls: list[list[str]] = []

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        # Spread the text's characters across the space so different strings land in
        # different directions without needing a real model.
        for index, character in enumerate(text[: self._dimensions]):
            vector[index] = (ord(character) % 32) / 32.0
        vector[0] = vector[0] or 1.0
        return vector
