"""/v1/ai — the coach.

Two shapes of the same turn. ``POST /ai/chat`` returns the finished reply, which is what
a client with retries and offline queues wants. ``POST /ai/chat/stream`` emits the same
answer as server-sent events, because a coaching reply takes several seconds and a user
watching a spinner that long assumes it has hung.

Both go through the same use case, so the safety path cannot diverge between them.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from coresync.application.coaching.chat import (
    ChatCommand,
    GetUsageUseCase,
    SendMessageUseCase,
    conversation_dto,
    message_dto,
)
from coresync.application.coaching.insights import (
    AcknowledgeInsightUseCase,
    GenerateInsightsUseCase,
    ListInsightsUseCase,
)
from coresync.core.errors import NotFoundError
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.coaching import (
    AcknowledgeInsightRequest,
    ChatReplyResponse,
    ConversationListResponse,
    ConversationResponse,
    InsightListResponse,
    InsightResponse,
    MessageListResponse,
    MessageResponse,
    SendMessageRequest,
    UsageResponse,
)
from coresync.presentation.schemas.common import ErrorResponse

router = APIRouter(prefix="/ai", tags=["ai"])

_CONVERSATION_LIMIT = 50
_MESSAGE_PAGE_LIMIT = 100


# ------------------------------------------------------------------------ chat
@router.post(
    "/chat",
    response_model=ChatReplyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        402: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Send a message to the coach",
    description=(
        "Runs one coaching turn: quota check, safety triage, context assembly, the tool "
        "loop, then an output guard before the reply is returned. Messages that trigger "
        "triage are answered from a scripted response and never reach the model."
    ),
)
async def send_message(
    body: SendMessageRequest,
    user: deps.CurrentUser,
    use_case: Annotated[SendMessageUseCase, Depends(deps.send_message_use_case)],
) -> ChatReplyResponse:
    reply = await use_case.execute(
        ChatCommand(
            user_id=user.id,
            content=body.content,
            conversation_id=body.conversation_id,
        )
    )
    return ChatReplyResponse(
        conversation_id=reply.conversation_id,
        message=MessageResponse.model_validate(reply.message),
        tools_used=list(reply.tools_used),
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
    )


@router.post(
    "/chat/stream",
    responses={
        200: {"content": {"text/event-stream": {}}},
        402: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Send a message and stream the reply",
    description=(
        "Server-sent events, token by token.\n\n"
        "`delta` appends text. `replace` discards everything shown so far and "
        "substitutes its payload — the output guard withholds the tail of the reply, so "
        "if it trips mid-generation the unsafe fragment is never emitted and the client "
        "is told to swap in a safe answer. `tools` names tools that ran. `message` "
        "closes the turn with the persisted reply. `error` carries a user-safe message "
        "when the failure happens after the status line has already been sent."
    ),
)
async def send_message_streaming(
    body: SendMessageRequest,
    user: deps.CurrentUser,
    use_case: Annotated[SendMessageUseCase, Depends(deps.send_message_use_case)],
) -> StreamingResponse:
    command = ChatCommand(
        user_id=user.id,
        content=body.content,
        conversation_id=body.conversation_id,
    )

    async def events() -> AsyncIterator[str]:
        try:
            async for event in use_case.stream(command):
                if event.kind == "delta":
                    yield _sse("delta", {"text": event.delta})
                elif event.kind == "replace":
                    yield _sse("replace", {"text": event.delta})
                elif event.kind == "tools":
                    yield _sse("tools", {"tools": list(event.tools)})
                elif event.kind == "message" and event.reply is not None:
                    yield _sse(
                        "message",
                        {
                            "conversationId": str(event.reply.conversation_id),
                            "message": MessageResponse.model_validate(
                                event.reply.message
                            ).model_dump(by_alias=True, mode="json"),
                            "toolsUsed": list(event.reply.tools_used),
                        },
                    )
        except Exception as exc:
            # The status line is already sent, so the only honest channel left is an
            # event the client can render. The message is the user-safe one.
            yield _sse("error", {"message": _safe_message(exc)})
            return

        yield _sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Nginx buffers proxied responses by default, which defeats streaming
            # entirely; this is the documented opt-out.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _safe_message(exc: Exception) -> str:
    """Never leak an internal message into the stream."""
    user_message = getattr(exc, "user_message", None)
    return str(user_message) if user_message else "The coach is unavailable right now."


# --------------------------------------------------------------- conversations
@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="List conversations",
    description="Most recently active first. Deleted conversations are excluded.",
)
async def list_conversations(
    user: deps.CurrentUser,
    uow: deps.Uow,
) -> ConversationListResponse:
    async with uow:
        conversations = await uow.conversations.list_for_user(user.id, limit=_CONVERSATION_LIMIT)
    return ConversationListResponse(
        conversations=[
            ConversationResponse.model_validate(conversation_dto(c)) for c in conversations
        ]
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Read a conversation",
    description="Oldest first. Includes messages that triage intercepted, with the "
    "category that caused it.",
)
async def list_messages(
    conversation_id: UUID,
    user: deps.CurrentUser,
    uow: deps.Uow,
    limit: Annotated[int, Query(ge=1, le=_MESSAGE_PAGE_LIMIT)] = 50,
) -> MessageListResponse:
    async with uow:
        conversation = await uow.conversations.get(conversation_id, user.id)
        if conversation is None:
            raise NotFoundError("That conversation does not exist.")
        messages = await uow.messages.list_for_conversation(conversation_id, limit=limit)
    return MessageListResponse(
        conversation_id=conversation_id,
        messages=[MessageResponse.model_validate(message_dto(m)) for m in messages],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Delete a conversation",
    description="Soft delete — the transcript is retained and stops appearing in the list.",
)
async def delete_conversation(
    conversation_id: UUID,
    user: deps.CurrentUser,
    uow: deps.Uow,
) -> None:
    async with uow:
        conversation = await uow.conversations.get(conversation_id, user.id)
        if conversation is None:
            raise NotFoundError("That conversation does not exist.")
        await uow.conversations.delete(conversation_id, user.id)
        await uow.commit()


# -------------------------------------------------------------------- insights
@router.get(
    "/insights",
    response_model=InsightListResponse,
    summary="Unacknowledged insights",
    description=(
        "Proactive observations found by deterministic detectors over the user's "
        "aggregates. Each carries the evidence that produced it."
    ),
)
async def list_insights(
    user: deps.CurrentUser,
    use_case: Annotated[ListInsightsUseCase, Depends(deps.list_insights_use_case)],
) -> InsightListResponse:
    insights = await use_case.execute(user.id)
    return InsightListResponse(insights=[InsightResponse.model_validate(i) for i in insights])


@router.post(
    "/insights/generate",
    response_model=InsightListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run the insight detectors now",
    description=(
        "Normally scheduled. Exposed so a client can refresh on demand. Repeats of a "
        "type raised in the last fortnight are suppressed — the same warning three weeks "
        "running is noise."
    ),
)
async def generate_insights(
    user: deps.CurrentUser,
    use_case: Annotated[GenerateInsightsUseCase, Depends(deps.generate_insights_use_case)],
) -> InsightListResponse:
    insights = await use_case.execute(user.id)
    return InsightListResponse(insights=[InsightResponse.model_validate(i) for i in insights])


@router.post(
    "/insights/{insight_id}/acknowledge",
    response_model=InsightResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Acknowledge an insight",
    description=(
        "Dismisses it and optionally records whether it was useful. That feedback is the "
        "only measurement of insight precision that comes from real users."
    ),
)
async def acknowledge_insight(
    insight_id: UUID,
    body: AcknowledgeInsightRequest,
    user: deps.CurrentUser,
    use_case: Annotated[AcknowledgeInsightUseCase, Depends(deps.acknowledge_insight_use_case)],
) -> InsightResponse:
    insight = await use_case.execute(insight_id, user.id, feedback=body.feedback)
    return InsightResponse.model_validate(insight)


# ----------------------------------------------------------------------- usage
@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="Today's coaching allowance",
    description="Resets at the user's local midnight, not UTC's.",
)
async def get_usage(
    user: deps.CurrentUser,
    use_case: Annotated[GetUsageUseCase, Depends(deps.ai_usage_use_case)],
) -> UsageResponse:
    usage = await use_case.execute(user.id)
    return UsageResponse(
        messages_used=usage.messages_used,
        messages_limit=usage.messages_limit,
        messages_remaining=usage.messages_remaining,
        tokens_used=usage.tokens_used,
    )
