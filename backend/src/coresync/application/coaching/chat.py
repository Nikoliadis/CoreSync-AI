"""The chat use case.

The order of operations is the safety design, not an implementation detail:

1. Quota check — before any provider cost is incurred.
2. Input triage — a self-harm disclosure never reaches the model at all.
3. Context assembly and the tool loop.
4. Output guard — what the model wrote is checked before the user sees it.
5. Metering — recorded for failures too, because a failed call still costs money.

Steps 2 and 4 are deterministic code. The model participates in none of the decisions
that matter (docs/10 §7).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import structlog

from coresync.application.coaching.context_assembler import ContextAssembler
from coresync.application.coaching.dto import ChatReplyDTO, ConversationDTO, MessageDTO, UsageDTO
from coresync.application.coaching.prompts import PROMPT_VERSION, build_system_prompt
from coresync.application.coaching.tools import ToolContext, ToolRegistry, ToolResult
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError, QuotaExceededError, ValidationError
from coresync.domain.coaching.context import CoachContext
from coresync.domain.coaching.entities import (
    Conversation,
    Message,
    MessageRole,
    TaskClass,
    ToolCall,
    UsageRecord,
)
from coresync.domain.coaching.ports import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    LLMGateway,
    ToolInvocation,
)
from coresync.domain.coaching.safety import (
    FALLBACK_RESPONSE,
    SAFE_RESPONSES,
    InputTriage,
    OutputGuard,
    SafetyCategory,
    StreamingOutputGuard,
)

logger = structlog.get_logger(__name__)

MAX_MESSAGE_LENGTH = 2000
FEATURE = "chat"


def conversation_dto(conversation: Conversation) -> ConversationDTO:
    return ConversationDTO(
        id=conversation.id,
        title=conversation.title,
        last_message_at=conversation.last_message_at,
        message_count=conversation.message_count,
        is_archived=conversation.is_archived,
    )


def message_dto(message: Message) -> MessageDTO:
    return MessageDTO(
        id=message.id,
        role=message.role.value,
        content=message.content,
        created_at=message.created_at,
        model=message.model,
        safety_category=message.safety_category,
    )


@dataclass(frozen=True, slots=True)
class ChatCommand:
    user_id: UUID
    content: str
    conversation_id: UUID | None = None
    local_date: date | None = None


@dataclass(frozen=True, slots=True)
class ChatQuota:
    daily_message_limit: int
    daily_cost_ceiling_usd: Decimal


@dataclass(frozen=True, slots=True)
class ChatStreamEvent:
    """One step of a streamed turn.

    ``delta`` appends; ``replace`` discards everything shown so far and substitutes
    ``delta`` — the escape hatch the output guard needs, since text already on screen
    cannot be unsent. ``message`` closes the turn with the persisted reply, so the
    client ends up with the same object the non-streaming endpoint returns.
    """

    kind: Literal["delta", "replace", "tools", "message"]
    delta: str = ""
    tools: tuple[str, ...] = ()
    reply: ChatReplyDTO | None = None


class SendMessageUseCase:
    """One coaching turn, end to end."""

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        gateway: LLMGateway,
        assembler: ContextAssembler,
        registry: ToolRegistry,
        quota: ChatQuota,
        clock: Clock,
        max_tool_iterations: int = 4,
        context_message_limit: int = 12,
        triage: InputTriage | None = None,
        guard: OutputGuard | None = None,
    ) -> None:
        self._uow = uow
        self._gateway = gateway
        self._assembler = assembler
        self._registry = registry
        self._quota = quota
        self._clock = clock
        self._max_tool_iterations = max_tool_iterations
        self._context_message_limit = context_message_limit
        self._triage = triage or InputTriage()
        self._guard = guard or OutputGuard()

    async def execute(self, command: ChatCommand) -> ChatReplyDTO:
        content = command.content.strip()
        if not content:
            raise ValidationError("A message cannot be empty.")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValidationError(f"Messages are limited to {MAX_MESSAGE_LENGTH} characters.")

        async with self._uow:
            user = await self._uow.users.get_by_id(command.user_id)
            if user is None:
                raise NotFoundError("user", command.user_id)
            # The user's day, not UTC's: a quota that resets at 02:00 local is a bug
            # report waiting to happen.
            today = command.local_date or local_date_for(self._clock.now(), user.timezone)

            await self._enforce_quota(command.user_id, today)

            conversation = await self._resolve_conversation(command, content)
            user_message = Message.create(
                conversation_id=conversation.id, role=MessageRole.USER, content=content
            )

            context = await self._assembler.build(command.user_id, today=today)

            # Triage runs on the raw message, before anything reaches the provider. The
            # minor check subsumes the general one.
            verdict = self._triage.screen_minor(content, age=context.profile.age)
            if verdict.is_blocked and verdict.category is not None:
                reply = await self._safe_reply(conversation, user_message, verdict.category)
            else:
                reply = await self._coach(conversation, user_message, context, today=today)

            await self._uow.commit()
            return reply

    # ------------------------------------------------------------------ steps
    async def _enforce_quota(self, user_id: UUID, today: date) -> None:
        usage = await self._uow.ai_usage.daily_usage(user_id, today)
        if usage.message_count >= self._quota.daily_message_limit:
            raise QuotaExceededError(
                "You've reached today's coaching message limit. It resets tomorrow."
            )
        if usage.cost_usd >= self._quota.daily_cost_ceiling_usd:
            # A separate ceiling because a handful of very long conversations can cost
            # more than many short ones; the message count alone does not bound spend.
            logger.warning("ai_cost_ceiling_hit", user_id=str(user_id), cost=str(usage.cost_usd))
            raise QuotaExceededError("You've reached today's coaching limit. It resets tomorrow.")

    async def _resolve_conversation(self, command: ChatCommand, content: str) -> Conversation:
        if command.conversation_id is not None:
            conversation = await self._uow.conversations.get(
                command.conversation_id, command.user_id
            )
            if conversation is None:
                raise NotFoundError("That conversation does not exist.")
            return conversation

        # Titled from the opening message so the list is scannable without a model call.
        title = content[:60].strip() or None
        conversation = Conversation.start(user_id=command.user_id, title=title)
        await self._uow.conversations.add(conversation)
        return conversation

    async def _safe_reply(
        self, conversation: Conversation, user_message: Message, category: SafetyCategory
    ) -> ChatReplyDTO:
        """A scripted response, with no provider call at all.

        Both messages are still stored: the transcript must reflect what the user
        experienced, and the category — never the text — makes the interception
        auditable.
        """
        user_message.safety_category = category.value
        reply = Message.create(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=SAFE_RESPONSES[category],
            safety_category=category.value,
            prompt_version=PROMPT_VERSION,
        )
        await self._persist_turn(conversation, user_message, reply)
        logger.info(
            "ai_message_intercepted",
            user_id=str(conversation.user_id),
            category=category.value,
        )
        return ChatReplyDTO(conversation_id=conversation.id, message=message_dto(reply))

    async def _coach(
        self,
        conversation: Conversation,
        user_message: Message,
        context: CoachContext,
        *,
        today: date,
    ) -> ChatReplyDTO:
        system_prompt = build_system_prompt(context)
        history = await self._uow.messages.recent_for_context(
            conversation.id, limit=self._context_message_limit
        )
        messages: list[dict[str, Any]] = [
            {"role": m.role.value, "content": m.content} for m in history
        ]
        messages.append({"role": MessageRole.USER.value, "content": user_message.content})

        tool_context = ToolContext(uow=self._uow, user_id=conversation.user_id, today=today)
        tool_results: list[dict[str, Any]] = []
        executed: list[ToolResult] = []
        response: CompletionResponse | None = None
        started = time.monotonic()

        for iteration in range(self._max_tool_iterations):
            request = CompletionRequest(
                system_prompt=system_prompt,
                messages=messages,
                task_class=TaskClass.CHAT,
                tools=self._registry.specs,
                tool_results=tuple(tool_results),
            )
            try:
                response = await self._gateway.complete(request)
            except Exception:
                # The partial turn is discarded, but the cost is not: a provider failure
                # still consumed tokens, and a dashboard blind to failures understates
                # spend exactly when something is going wrong. Rolling back first is what
                # keeps the usage row from being swept away with the abandoned turn.
                await self._uow.rollback()
                await self._meter(
                    conversation.user_id,
                    model=self._gateway.model_for(TaskClass.CHAT),
                    response=None,
                    started=started,
                    status="error",
                    today=today,
                )
                await self._uow.commit()
                raise

            if not response.wants_tools:
                break

            tool_results, batch = await self._run_tools(response, tool_context)
            executed.extend(batch)
            # The assistant turn that requested the tools has to be replayed, or the
            # provider rejects the tool results as unsolicited.
            messages.append(
                {
                    "role": MessageRole.ASSISTANT.value,
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in response.tool_calls
                    ],
                }
            )
            if iteration == self._max_tool_iterations - 1:
                logger.warning("ai_tool_loop_exhausted", conversation_id=str(conversation.id))

        content = response.content if response else ""
        # The guard inspects what the model actually wrote. A model talked into an unsafe
        # calorie target states it confidently, so the number is checked, not the intent.
        if not content or self._guard.inspect(content).must_regenerate:
            if content:
                logger.warning(
                    "ai_output_blocked",
                    conversation_id=str(conversation.id),
                    reasons=self._guard.inspect(content).reasons,
                )
            content = FALLBACK_RESPONSE

        reply = Message.create(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=content,
            context_snapshot=context.to_prompt_dict(),
            prompt_tokens=response.prompt_tokens if response else 0,
            completion_tokens=response.completion_tokens if response else 0,
            model=response.model if response else None,
            prompt_version=PROMPT_VERSION,
        )
        await self._persist_turn(conversation, user_message, reply, executed)
        await self._meter(
            conversation.user_id,
            model=reply.model or self._gateway.model_for(TaskClass.CHAT),
            response=response,
            started=started,
            status="ok",
            today=today,
        )

        return ChatReplyDTO(
            conversation_id=conversation.id,
            message=message_dto(reply),
            tools_used=tuple(result.name for result in executed),
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
        )

    # ------------------------------------------------------------------ streaming
    async def stream(self, command: ChatCommand) -> AsyncIterator[ChatStreamEvent]:
        """The same turn, emitted token by token.

        Deliberately shares every safety decision with :meth:`execute` — quota, then
        triage, then the tool loop, then the output guard. A second code path for
        streaming is how the two drift until one of them stops enforcing something.

        The difference is the guard: it runs incrementally through
        :class:`StreamingOutputGuard`, which withholds the tail of the text so nothing
        is shown that a later token could turn into an unsafe pattern.
        """
        content = command.content.strip()
        if not content:
            raise ValidationError("A message cannot be empty.")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValidationError(f"Messages are limited to {MAX_MESSAGE_LENGTH} characters.")

        async with self._uow:
            user = await self._uow.users.get_by_id(command.user_id)
            if user is None:
                raise NotFoundError("user", command.user_id)
            today = command.local_date or local_date_for(self._clock.now(), user.timezone)

            await self._enforce_quota(command.user_id, today)

            conversation = await self._resolve_conversation(command, content)
            user_message = Message.create(
                conversation_id=conversation.id, role=MessageRole.USER, content=content
            )
            context = await self._assembler.build(command.user_id, today=today)

            verdict = self._triage.screen_minor(content, age=context.profile.age)
            if verdict.is_blocked and verdict.category is not None:
                reply = await self._safe_reply(conversation, user_message, verdict.category)
                await self._uow.commit()
                # Scripted responses are not streamed. Revealing a crisis referral one
                # word at a time would be a strange thing to do to someone in distress.
                yield ChatStreamEvent(kind="message", reply=reply)
                return

            async for event in self._coach_streaming(
                conversation, user_message, context, today=today
            ):
                yield event

            await self._uow.commit()

    async def _coach_streaming(
        self,
        conversation: Conversation,
        user_message: Message,
        context: CoachContext,
        *,
        today: date,
    ) -> AsyncIterator[ChatStreamEvent]:
        system_prompt = build_system_prompt(context)
        history = await self._uow.messages.recent_for_context(
            conversation.id, limit=self._context_message_limit
        )
        messages: list[dict[str, Any]] = [
            {"role": m.role.value, "content": m.content} for m in history
        ]
        messages.append({"role": MessageRole.USER.value, "content": user_message.content})

        tool_context = ToolContext(uow=self._uow, user_id=conversation.user_id, today=today)
        tool_results: list[dict[str, Any]] = []
        executed: list[ToolResult] = []
        guard = StreamingOutputGuard(self._guard)
        started = time.monotonic()

        model = self._gateway.model_for(TaskClass.CHAT)
        prompt_tokens = completion_tokens = cached_tokens = 0
        blocked = False

        for iteration in range(self._max_tool_iterations):
            request = CompletionRequest(
                system_prompt=system_prompt,
                messages=messages,
                task_class=TaskClass.CHAT,
                tools=self._registry.specs,
                tool_results=tuple(tool_results),
            )

            final: CompletionChunk | None = None
            try:
                async for chunk in self._gateway.stream(request):
                    if chunk.is_final:
                        final = chunk
                        break

                    if not chunk.delta:
                        continue

                    released, chunk_verdict = guard.push(chunk.delta)
                    if chunk_verdict.must_regenerate:
                        logger.warning(
                            "ai_output_blocked",
                            conversation_id=str(conversation.id),
                            reasons=chunk_verdict.reasons,
                        )
                        blocked = True
                        break
                    if released:
                        yield ChatStreamEvent(kind="delta", delta=released)
            except Exception:
                await self._uow.rollback()
                await self._meter(
                    conversation.user_id,
                    model=model,
                    response=None,
                    started=started,
                    status="error",
                    today=today,
                )
                await self._uow.commit()
                raise

            if final is not None:
                model = final.model or model
                prompt_tokens += final.prompt_tokens
                completion_tokens += final.completion_tokens
                cached_tokens += final.cached_tokens

            if blocked or final is None or not final.wants_tools:
                break

            # Tools were requested, so nothing user-visible was generated this round.
            batch_results, batch = await self._run_tool_calls(final.tool_calls, tool_context)
            tool_results = batch_results
            executed.extend(batch)
            yield ChatStreamEvent(kind="tools", tools=tuple(result.name for result in batch))

            messages.append(
                {
                    "role": MessageRole.ASSISTANT.value,
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in final.tool_calls
                    ],
                }
            )
            if iteration == self._max_tool_iterations - 1:
                logger.warning("ai_tool_loop_exhausted", conversation_id=str(conversation.id))

        if not blocked:
            remainder, final_verdict = guard.finish()
            if final_verdict.must_regenerate:
                logger.warning(
                    "ai_output_blocked",
                    conversation_id=str(conversation.id),
                    reasons=final_verdict.reasons,
                )
                blocked = True
            elif remainder:
                yield ChatStreamEvent(kind="delta", delta=remainder)

        content = guard.text
        if blocked or not content.strip():
            # Whatever was already shown is replaced wholesale. The withheld tail means
            # the unsafe fragment itself never reached the client.
            content = FALLBACK_RESPONSE
            yield ChatStreamEvent(kind="replace", delta=content)

        reply = Message.create(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=content,
            context_snapshot=context.to_prompt_dict(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
            prompt_version=PROMPT_VERSION,
        )
        await self._persist_turn(conversation, user_message, reply, executed)
        await self._meter(
            conversation.user_id,
            model=model,
            response=CompletionResponse(
                content=content,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
            ),
            started=started,
            status="ok",
            today=today,
        )

        yield ChatStreamEvent(
            kind="message",
            reply=ChatReplyDTO(
                conversation_id=conversation.id,
                message=message_dto(reply),
                tools_used=tuple(result.name for result in executed),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
        )

    async def _run_tool_calls(
        self, calls: Sequence[ToolInvocation], context: ToolContext
    ) -> tuple[list[dict[str, Any]], list[ToolResult]]:
        payloads: list[dict[str, Any]] = []
        results: list[ToolResult] = []
        for call in calls:
            result = await self._registry.execute(call.name, call.arguments, context=context)
            results.append(result)
            payloads.append(
                {
                    "role": MessageRole.TOOL.value,
                    "tool_call_id": call.call_id,
                    "content": json.dumps(result.payload, default=str),
                }
            )
        return payloads, results

    async def _run_tools(
        self, response: CompletionResponse, context: ToolContext
    ) -> tuple[list[dict[str, Any]], list[ToolResult]]:
        payloads: list[dict[str, Any]] = []
        results: list[ToolResult] = []
        for call in response.tool_calls:
            result = await self._registry.execute(call.name, call.arguments, context=context)
            results.append(result)
            payloads.append(
                {
                    "role": MessageRole.TOOL.value,
                    "tool_call_id": call.call_id,
                    "content": json.dumps(result.payload, default=str),
                }
            )
        return payloads, results

    async def _persist_turn(
        self,
        conversation: Conversation,
        user_message: Message,
        reply: Message,
        executed: list[ToolResult] | None = None,
    ) -> None:
        await self._uow.messages.add(user_message)
        await self._uow.messages.add(reply)
        if executed:
            await self._uow.messages.add_tool_calls(
                [
                    ToolCall.create(
                        message_id=reply.id,
                        tool_name=result.name,
                        arguments=result.arguments,
                        result_summary=result.summary,
                        duration_ms=result.duration_ms,
                        is_error=result.is_error,
                        error_code=result.error_code,
                    )
                    for result in executed
                ]
            )
        conversation.message_count += 2
        conversation.last_message_at = datetime.now(tz=UTC)
        await self._uow.conversations.update(conversation)

    async def _meter(
        self,
        user_id: UUID,
        *,
        model: str,
        response: CompletionResponse | None,
        started: float,
        status: str,
        today: date,
    ) -> None:
        prompt_tokens = response.prompt_tokens if response else 0
        completion_tokens = response.completion_tokens if response else 0
        cached_tokens = response.cached_tokens if response else 0
        cost = self._gateway.estimate_cost_usd(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )
        await self._uow.ai_usage.record(
            UsageRecord.create(
                user_id=user_id,
                feature=FEATURE,
                provider="azure_openai",
                model=model,
                task_class=TaskClass.CHAT,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                cost_usd=cost,
                latency_ms=int((time.monotonic() - started) * 1000),
                status=status,
            ),
            local_date=today,
        )


class GetUsageUseCase:
    def __init__(self, *, uow: UnitOfWork, quota: ChatQuota, clock: Clock) -> None:
        self._uow = uow
        self._quota = quota
        self._clock = clock

    async def execute(self, user_id: UUID, *, today: date | None = None) -> UsageDTO:
        async with self._uow:
            on = today or await self._today_for(user_id)
            usage = await self._uow.ai_usage.daily_usage(user_id, on)
            return UsageDTO(
                messages_used=usage.message_count,
                messages_limit=self._quota.daily_message_limit,
                tokens_used=usage.total_tokens,
            )

    async def _today_for(self, user_id: UUID) -> date:
        user = await self._uow.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user", user_id)
        return local_date_for(self._clock.now(), user.timezone)
