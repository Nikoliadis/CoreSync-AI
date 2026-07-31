"""The Azure adapter, against a mock transport.

Worth testing without a provider because the interesting behaviour is entirely ours: what
gets retried, what does not, how a malformed tool argument is handled, and whether usage
is captured when streaming. Every one of those is a silent failure in production —
a request that hangs, a cost that reports as zero, a tool call that crashes the turn.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from coresync.core.errors import UpstreamUnavailableError
from coresync.domain.coaching.entities import TaskClass
from coresync.domain.coaching.ports import CompletionRequest, ToolSpec
from coresync.infrastructure.external.llm.azure import (
    AzureOpenAIEmbeddingGateway,
    AzureOpenAIGateway,
)
from coresync.infrastructure.external.llm.router import ModelRouter

pytestmark = pytest.mark.asyncio

ROUTER = ModelRouter(
    chat_deployment="gpt-4o",
    mini_deployment="gpt-4o-mini",
    embedding_deployment="text-embedding-3-small",
)


def _gateway(handler: Any) -> AzureOpenAIGateway:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.openai.azure.com"
    )
    return AzureOpenAIGateway(client=client, router=ROUTER, api_version="2024-10-21")


def _request(task_class: TaskClass = TaskClass.CHAT, **kwargs: Any) -> CompletionRequest:
    return CompletionRequest(
        system_prompt="You are the coach.",
        messages=[{"role": "user", "content": "hello"}],
        task_class=task_class,
        **kwargs,
    )


def _completion_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "gpt-4o",
        "choices": [{"message": {"content": "Hello there."}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 35},
    }
    body.update(overrides)
    return body


class TestCompletion:
    async def test_a_successful_call_is_parsed(self) -> None:
        gateway = _gateway(lambda request: httpx.Response(200, json=_completion_body()))
        response = await gateway.complete(_request())

        assert response.content == "Hello there."
        assert response.prompt_tokens == 120
        assert response.completion_tokens == 35
        assert response.finish_reason == "stop"
        assert not response.wants_tools

    async def test_the_deployment_and_api_version_are_in_the_url(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json=_completion_body())

        await _gateway(handler).complete(_request())
        assert "/openai/deployments/gpt-4o/chat/completions" in seen[0]
        assert "api-version=2024-10-21" in seen[0]

    async def test_the_task_class_selects_the_cheap_deployment(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json=_completion_body())

        await _gateway(handler).complete(_request(task_class=TaskClass.SUMMARISATION))
        assert "/deployments/gpt-4o-mini/" in seen[0]

    async def test_the_system_prompt_leads_the_message_list(self) -> None:
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_completion_body())

        await _gateway(handler).complete(_request())
        messages = captured[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are the coach."

    async def test_cached_prompt_tokens_are_read_from_the_usage_details(self) -> None:
        body = _completion_body(
            usage={
                "prompt_tokens": 1000,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 800},
            }
        )
        gateway = _gateway(lambda request: httpx.Response(200, json=body))
        assert (await gateway.complete(_request())).cached_tokens == 800

    async def test_a_missing_usage_block_does_not_crash_the_turn(self) -> None:
        body = {"choices": [{"message": {"content": "hi"}}]}
        gateway = _gateway(lambda request: httpx.Response(200, json=body))
        response = await gateway.complete(_request())
        assert response.prompt_tokens == 0
        assert response.content == "hi"


class TestTools:
    async def test_tool_specs_are_sent_when_provided(self) -> None:
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_completion_body())

        spec = ToolSpec(
            name="get_routines", description="d", parameters={"type": "object", "properties": {}}
        )
        await _gateway(handler).complete(_request(tools=(spec,)))

        assert captured[0]["tools"][0]["function"]["name"] == "get_routines"
        assert captured[0]["tool_choice"] == "auto"

    async def test_no_tools_key_is_sent_when_there_are_none(self) -> None:
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_completion_body())

        await _gateway(handler).complete(_request())
        assert "tools" not in captured[0]

    async def test_a_tool_call_is_parsed_with_its_arguments(self) -> None:
        body = _completion_body(
            choices=[
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-7",
                                "function": {
                                    "name": "get_weight_history",
                                    "arguments": '{"days": 30}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        )
        gateway = _gateway(lambda request: httpx.Response(200, json=body))
        response = await gateway.complete(_request())

        assert response.wants_tools
        call = response.tool_calls[0]
        assert call.call_id == "call-7"
        assert call.name == "get_weight_history"
        assert call.arguments == {"days": 30}

    async def test_malformed_tool_arguments_degrade_to_an_empty_dict(self) -> None:
        """A model emitting broken JSON must not take the whole turn down."""
        body = _completion_body(
            choices=[
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {"id": "c", "function": {"name": "get_routines", "arguments": "{oops"}}
                        ],
                    }
                }
            ]
        )
        gateway = _gateway(lambda request: httpx.Response(200, json=body))
        response = await gateway.complete(_request())
        assert response.tool_calls[0].arguments == {}


class TestFailureHandling:
    async def test_a_bad_request_is_not_retried(self) -> None:
        """Retrying a malformed request just burns latency on a certain failure."""
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(400, json={"error": "bad request"})

        with pytest.raises(UpstreamUnavailableError):
            await _gateway(handler).complete(_request())
        assert attempts == 1

    async def test_a_server_error_is_retried_then_surfaces(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503)

        with pytest.raises(UpstreamUnavailableError):
            await _gateway(handler).complete(_request())
        assert attempts == 3

    async def test_a_retry_that_succeeds_returns_the_answer(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429)
            return httpx.Response(200, json=_completion_body())

        response = await _gateway(handler).complete(_request())
        assert response.content == "Hello there."
        assert attempts == 2

    async def test_a_transport_error_becomes_an_upstream_error(self) -> None:
        """Never a raw httpx exception: the caller maps our error type to a 503."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with pytest.raises(UpstreamUnavailableError):
            await _gateway(handler).complete(_request())

    async def test_the_provider_body_is_not_echoed_to_the_caller(self) -> None:
        """Error bodies can contain prompt fragments."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="prompt fragment: user weighs 82kg")

        with pytest.raises(UpstreamUnavailableError) as excinfo:
            await _gateway(handler).complete(_request())
        assert "82kg" not in str(excinfo.value)


class TestStreaming:
    async def test_deltas_are_yielded_and_usage_lands_on_the_final_chunk(self) -> None:
        frames = [
            'data: {"choices":[{"delta":{"content":"Your "}}]}',
            'data: {"choices":[{"delta":{"content":"squat"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":90,"completion_tokens":12}}',
            "data: [DONE]",
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="\n\n".join(frames))

        chunks = [chunk async for chunk in _gateway(handler).stream(_request())]

        assert "".join(c.delta for c in chunks if not c.is_final) == "Your squat"
        final = chunks[-1]
        assert final.is_final
        assert final.prompt_tokens == 90
        assert final.completion_tokens == 12

    async def test_usage_is_requested_so_streamed_calls_are_not_metered_as_free(self) -> None:
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, text="data: [DONE]\n\n")

        [chunk async for chunk in _gateway(handler).stream(_request())]
        assert captured[0]["stream"] is True
        assert captured[0]["stream_options"] == {"include_usage": True}

    async def test_a_truncated_frame_is_skipped_rather_than_fatal(self) -> None:
        frames = [
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            "data: {not json",
            "data: [DONE]",
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="\n\n".join(frames))

        chunks = [chunk async for chunk in _gateway(handler).stream(_request())]
        assert "".join(c.delta for c in chunks) == "ok"

    async def test_an_error_status_raises_before_any_delta(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="upstream on fire")

        with pytest.raises(UpstreamUnavailableError):
            [chunk async for chunk in _gateway(handler).stream(_request())]


class TestEmbeddings:
    async def test_vectors_are_returned_in_input_order(self) -> None:
        """The provider does not guarantee order; a silent mismatch mispairs every chunk."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.2, 0.2]},
                        {"index": 0, "embedding": [0.1, 0.1]},
                    ]
                },
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://example.openai.azure.com"
        )
        gateway = AzureOpenAIEmbeddingGateway(
            client=client, deployment="text-embedding-3-small", api_version="2024-10-21"
        )

        vectors = await gateway.embed(["first", "second"])
        assert vectors == [[0.1, 0.1], [0.2, 0.2]]

    async def test_an_empty_input_makes_no_request(self) -> None:
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={"data": []})

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://example.openai.azure.com"
        )
        gateway = AzureOpenAIEmbeddingGateway(
            client=client, deployment="d", api_version="2024-10-21"
        )
        assert await gateway.embed([]) == []
        assert not called

    async def test_an_embedding_failure_does_not_masquerade_as_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://example.openai.azure.com"
        )
        gateway = AzureOpenAIEmbeddingGateway(
            client=client, deployment="d", api_version="2024-10-21"
        )
        with pytest.raises(UpstreamUnavailableError):
            await gateway.embed(["text"])
