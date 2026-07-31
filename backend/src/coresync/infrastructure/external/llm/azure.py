"""Azure OpenAI adapter.

Built directly on httpx rather than the vendor SDK. The surface actually used here is
two endpoints, and owning the request means owning the timeout, the retry policy and the
streaming parser — the three things that decide whether a coach feels responsive or
broken when the provider is having a bad day.

Nothing in this module makes a safety decision. Triage runs before the call and the
output guard runs after it, in code the provider cannot influence.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from typing import Any

import httpx
import structlog

from coresync.core.errors import UpstreamUnavailableError
from coresync.domain.coaching.entities import TaskClass
from coresync.domain.coaching.ports import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    ToolInvocation,
    ToolSpec,
)
from coresync.infrastructure.external.llm.router import ModelRouter, estimate_cost_usd

logger = structlog.get_logger(__name__)

# Retried because they are transient by definition. 400 and 401 are not: retrying a
# malformed request or a bad key just burns latency on a failure that will recur.
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5

_SSE_DONE = "[DONE]"


class AzureOpenAIGateway:
    """Provider adapter implementing :class:`LLMGateway`."""

    provider_name = "azure_openai"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        router: ModelRouter,
        api_version: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._client = client
        self._router = router
        self._api_version = api_version
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------ public
    def model_for(self, task_class: TaskClass) -> str:
        return self._router.deployment_for(task_class)

    def estimate_cost_usd(
        self, *, model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0
    ) -> Decimal:
        return estimate_cost_usd(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        deployment = self.model_for(request.task_class)
        payload = self._build_payload(request, stream=False)
        data = await self._post_json(deployment, payload)
        return _parse_completion(data, deployment)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[CompletionChunk]:
        """Token-by-token output.

        Streaming is not a nicety here: a coaching answer takes several seconds to
        generate, and a user watching a spinner for that long assumes it has hung.
        """
        deployment = self.model_for(request.task_class)
        payload = self._build_payload(request, stream=True)
        url = self._url(deployment)

        prompt_tokens = completion_tokens = 0
        try:
            async with self._client.stream(
                "POST", url, json=payload, timeout=self._timeout
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise self._error_for(response.status_code, body.decode(errors="replace"))

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == _SSE_DONE:
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        # A truncated frame is not worth failing the whole answer over.
                        logger.warning("llm_stream_bad_frame", deployment=deployment)
                        continue

                    usage = event.get("usage") or {}
                    if usage:
                        prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                        completion_tokens = usage.get("completion_tokens", completion_tokens)

                    for choice in event.get("choices", ()):
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield CompletionChunk(delta=delta, model=deployment)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError("the AI provider is unavailable") from exc

        yield CompletionChunk(
            is_final=True,
            model=deployment,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    # ----------------------------------------------------------------- internals
    def _url(self, deployment: str) -> str:
        return f"/openai/deployments/{deployment}/chat/completions?api-version={self._api_version}"

    def _build_payload(self, request: CompletionRequest, *, stream: bool) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.system_prompt},
            *request.messages,
            *request.tool_results,
        ]
        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": stream,
        }
        if stream:
            # Without this the final frame carries no usage and every streamed call is
            # metered as zero cost.
            payload["stream_options"] = {"include_usage": True}
        if request.tools:
            payload["tools"] = [_tool_payload(t) for t in request.tools]
            payload["tool_choice"] = "auto"
        return payload

    async def _post_json(self, deployment: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._url(deployment)
        last_error: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._client.post(url, json=payload, timeout=self._timeout)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code < 400:
                    result: dict[str, Any] = response.json()
                    return result
                if response.status_code not in _RETRYABLE_STATUS:
                    raise self._error_for(response.status_code, response.text)
                last_error = self._error_for(response.status_code, response.text)

            if attempt < _MAX_ATTEMPTS:
                # Exponential backoff. Azure sends Retry-After on 429s but it is often
                # longer than a user will wait, so the request is failed rather than
                # parked — the caller degrades to a clear message.
                await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

        logger.warning("llm_unavailable", deployment=deployment, error=str(last_error))
        raise UpstreamUnavailableError("the AI provider is unavailable") from last_error

    def _error_for(self, status: int, body: str) -> Exception:
        # The body can echo prompt fragments, so it is truncated and never surfaced to
        # the user.
        logger.warning("llm_error_response", status=status, body=body[:200])
        return UpstreamUnavailableError("the AI provider rejected the request")


class AzureOpenAIEmbeddingGateway:
    """Embeddings, split from the chat gateway because it fails independently.

    Retrieval degrading to nothing is survivable — the coach answers from the context
    bundle alone. Conflating the two would take chat down with it.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        deployment: str,
        api_version: str,
        dimensions: int = 1536,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client
        self._deployment = deployment
        self._api_version = api_version
        self._dimensions = dimensions
        self._timeout = timeout_seconds

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"/openai/deployments/{self._deployment}/embeddings?api-version={self._api_version}"
        try:
            response = await self._client.post(
                url,
                json={"input": list(texts), "dimensions": self._dimensions},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError("the embedding provider is unavailable") from exc

        if response.status_code >= 400:
            logger.warning("embedding_error", status=response.status_code)
            raise UpstreamUnavailableError("the embedding provider rejected the request")

        data = response.json().get("data", [])
        # Sorted by index: the provider does not guarantee response order, and a silent
        # mismatch here pairs every chunk with the wrong vector.
        ordered = sorted(data, key=lambda row: row.get("index", 0))
        return [row["embedding"] for row in ordered]


# ------------------------------------------------------------------- parsing
def _tool_payload(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_completion(data: dict[str, Any], deployment: str) -> CompletionResponse:
    choices = data.get("choices") or [{}]
    message = choices[0].get("message") or {}
    usage = data.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)

    tool_calls: list[ToolInvocation] = []
    for call in message.get("tool_calls") or ():
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            # A model that emits malformed arguments has failed the call; recording it
            # with empty arguments lets the executor reject it cleanly and keeps the
            # attempt in the audit trail.
            logger.warning("llm_bad_tool_arguments", tool=function.get("name"))
            arguments = {}
        tool_calls.append(
            ToolInvocation(
                call_id=call.get("id", ""),
                name=function.get("name", ""),
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )

    return CompletionResponse(
        content=message.get("content") or "",
        tool_calls=tuple(tool_calls),
        model=data.get("model") or deployment,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cached_tokens=cached,
        finish_reason=choices[0].get("finish_reason") or "stop",
    )


def build_azure_client(*, endpoint: str, api_key: str) -> httpx.AsyncClient:
    """Shared client for both gateways, so connections are pooled across features."""
    return httpx.AsyncClient(
        base_url=endpoint.rstrip("/"),
        headers={"api-key": api_key, "content-type": "application/json"},
    )
