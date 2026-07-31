"""SQLAlchemy repositories for the AI coach."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.domain.coaching.entities import (
    Conversation,
    DailyUsage,
    Insight,
    InsightSeverity,
    InsightType,
    Message,
    MessageRole,
    ToolCall,
    UsageRecord,
)
from coresync.domain.coaching.ports import KnowledgeChunk
from coresync.infrastructure.database.models.coaching import (
    AiConversationModel,
    AiEmbeddingModel,
    AiInsightModel,
    AiMessageModel,
    AiToolCallModel,
    AiUsageLogModel,
)

_ZERO = Decimal("0")


# ------------------------------------------------------------------- mapping
def _conversation_to_entity(model: AiConversationModel) -> Conversation:
    return Conversation(
        id=model.id,
        user_id=model.user_id,
        title=model.title,
        summary=model.summary,
        last_message_at=model.last_message_at,
        message_count=model.message_count,
        is_archived=model.is_archived,
    )


def _message_to_entity(model: AiMessageModel) -> Message:
    return Message(
        id=model.id,
        conversation_id=model.conversation_id,
        role=MessageRole(model.role),
        content=model.content,
        context_snapshot=model.context_snapshot,
        prompt_tokens=model.prompt_tokens,
        completion_tokens=model.completion_tokens,
        model=model.model,
        prompt_version=model.prompt_version,
        safety_category=model.safety_category,
        created_at=model.created_at,
    )


def _insight_to_entity(model: AiInsightModel) -> Insight:
    return Insight(
        id=model.id,
        user_id=model.user_id,
        insight_type=InsightType(model.insight_type),
        severity=InsightSeverity(model.severity),
        title=model.title,
        body=model.body,
        evidence=model.evidence,
        acknowledged_at=model.acknowledged_at,
        feedback=model.feedback,
        created_at=model.created_at,
    )


# ------------------------------------------------------------- conversations
class SqlAlchemyConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _live(self) -> Select[tuple[AiConversationModel]]:
        return select(AiConversationModel).where(AiConversationModel.deleted_at.is_(None))

    async def get(self, conversation_id: UUID, user_id: UUID) -> Conversation | None:
        # user_id is part of the predicate, not a check afterwards: a missing filter here
        # is an IDOR, and the signature makes forgetting it impossible.
        stmt = self._live().where(
            AiConversationModel.id == conversation_id,
            AiConversationModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _conversation_to_entity(model) if model else None

    async def list_for_user(self, user_id: UUID, *, limit: int) -> list[Conversation]:
        stmt = (
            self._live()
            .where(AiConversationModel.user_id == user_id)
            .order_by(AiConversationModel.last_message_at.desc().nullslast())
            .limit(limit)
        )
        return [_conversation_to_entity(m) for m in (await self._session.execute(stmt)).scalars()]

    async def add(self, conversation: Conversation) -> None:
        self._session.add(
            AiConversationModel(
                id=conversation.id,
                user_id=conversation.user_id,
                title=conversation.title,
                summary=conversation.summary,
                last_message_at=conversation.last_message_at,
                message_count=conversation.message_count,
                is_archived=conversation.is_archived,
            )
        )
        await self._session.flush()

    async def update(self, conversation: Conversation) -> None:
        stmt = self._live().where(
            AiConversationModel.id == conversation.id,
            AiConversationModel.user_id == conversation.user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return
        model.title = conversation.title
        model.summary = conversation.summary
        model.last_message_at = conversation.last_message_at
        model.message_count = conversation.message_count
        model.is_archived = conversation.is_archived
        await self._session.flush()

    async def delete(self, conversation_id: UUID, user_id: UUID) -> None:
        """Soft delete.

        The transcript is retained because a coaching conversation is health-adjacent
        context a user may later want restored or exported; hard erasure is the account
        deletion path, not this one.
        """
        stmt = self._live().where(
            AiConversationModel.id == conversation_id,
            AiConversationModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return
        model.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()


# ----------------------------------------------------------------- messages
class SqlAlchemyMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_conversation(
        self, conversation_id: UUID, *, limit: int, before: datetime | None = None
    ) -> list[Message]:
        stmt = select(AiMessageModel).where(AiMessageModel.conversation_id == conversation_id)
        if before is not None:
            stmt = stmt.where(AiMessageModel.created_at < before)
        stmt = stmt.order_by(AiMessageModel.created_at.desc()).limit(limit)
        models = list((await self._session.execute(stmt)).scalars())
        # Newest-first for pagination, oldest-first for reading.
        return [_message_to_entity(m) for m in reversed(models)]

    async def recent_for_context(self, conversation_id: UUID, *, limit: int) -> list[Message]:
        """The tail of the thread, oldest first.

        Tool messages are excluded: their content is raw JSON already summarised into the
        assistant turn that followed, so replaying them wastes context without adding
        anything the model does not already have.
        """
        stmt = (
            select(AiMessageModel)
            .where(
                AiMessageModel.conversation_id == conversation_id,
                AiMessageModel.role.in_((MessageRole.USER.value, MessageRole.ASSISTANT.value)),
            )
            .order_by(AiMessageModel.created_at.desc())
            .limit(limit)
        )
        models = list((await self._session.execute(stmt)).scalars())
        return [_message_to_entity(m) for m in reversed(models)]

    async def add(self, message: Message) -> None:
        self._session.add(
            AiMessageModel(
                id=message.id,
                conversation_id=message.conversation_id,
                role=message.role.value,
                content=message.content,
                context_snapshot=message.context_snapshot,
                prompt_tokens=message.prompt_tokens,
                completion_tokens=message.completion_tokens,
                model=message.model,
                prompt_version=message.prompt_version,
                safety_category=message.safety_category,
            )
        )
        await self._session.flush()

    async def add_tool_calls(self, calls: Sequence[ToolCall]) -> None:
        if not calls:
            return
        self._session.add_all(
            [
                AiToolCallModel(
                    id=call.id,
                    message_id=call.message_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    result_summary=call.result_summary,
                    result_bytes=call.result_bytes,
                    duration_ms=call.duration_ms,
                    is_error=call.is_error,
                    error_code=call.error_code,
                )
                for call in calls
            ]
        )
        await self._session.flush()


# ----------------------------------------------------------------- insights
class SqlAlchemyInsightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self, user_id: UUID) -> list[Insight]:
        stmt = (
            select(AiInsightModel)
            .where(
                AiInsightModel.user_id == user_id,
                AiInsightModel.acknowledged_at.is_(None),
            )
            .order_by(AiInsightModel.created_at.desc())
        )
        return [_insight_to_entity(m) for m in (await self._session.execute(stmt)).scalars()]

    async def get(self, insight_id: UUID, user_id: UUID) -> Insight | None:
        stmt = select(AiInsightModel).where(
            AiInsightModel.id == insight_id,
            AiInsightModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _insight_to_entity(model) if model else None

    async def add_many(self, insights: Sequence[Insight]) -> None:
        if not insights:
            return
        self._session.add_all(
            [
                AiInsightModel(
                    id=insight.id,
                    user_id=insight.user_id,
                    insight_type=insight.insight_type.value,
                    severity=insight.severity.value,
                    title=insight.title,
                    body=insight.body,
                    evidence=insight.evidence,
                    acknowledged_at=insight.acknowledged_at,
                    feedback=insight.feedback,
                )
                for insight in insights
            ]
        )
        await self._session.flush()

    async def update(self, insight: Insight) -> None:
        stmt = select(AiInsightModel).where(
            AiInsightModel.id == insight.id,
            AiInsightModel.user_id == insight.user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return
        model.acknowledged_at = insight.acknowledged_at
        model.feedback = insight.feedback
        await self._session.flush()

    async def recent_types(self, user_id: UUID, *, since: date) -> set[str]:
        stmt = (
            select(AiInsightModel.insight_type)
            .where(
                AiInsightModel.user_id == user_id,
                func.date(AiInsightModel.created_at) >= since,
            )
            .distinct()
        )
        return set((await self._session.execute(stmt)).scalars())


# -------------------------------------------------------------------- usage
class SqlAlchemyUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, usage: UsageRecord, *, local_date: date | None = None) -> None:
        self._session.add(
            AiUsageLogModel(
                id=usage.id,
                user_id=usage.user_id,
                feature=usage.feature,
                provider=usage.provider,
                model=usage.model,
                task_class=usage.task_class.value,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cached_tokens=usage.cached_tokens,
                cost_usd=usage.cost_usd,
                latency_ms=usage.latency_ms,
                status=usage.status,
                error_code=usage.error_code,
                local_date=local_date or datetime.now(tz=UTC).date(),
            )
        )
        await self._session.flush()

    async def daily_usage(self, user_id: UUID, on: date) -> DailyUsage:
        """A user's spend for one local day.

        Counts only chat messages towards the message quota — background insight
        generation is our cost, not something the user asked for, so charging it against
        their allowance would silently shrink the product they were sold.
        """
        stmt = select(
            func.count(AiUsageLogModel.id).filter(AiUsageLogModel.feature == "chat"),
            func.coalesce(
                func.sum(AiUsageLogModel.prompt_tokens + AiUsageLogModel.completion_tokens), 0
            ),
            func.coalesce(func.sum(AiUsageLogModel.cost_usd), _ZERO),
        ).where(
            AiUsageLogModel.user_id == user_id,
            AiUsageLogModel.local_date == on,
        )
        message_count, total_tokens, cost = (await self._session.execute(stmt)).one()
        return DailyUsage(
            user_id=user_id,
            local_date=on,
            message_count=int(message_count or 0),
            total_tokens=int(total_tokens or 0),
            cost_usd=Decimal(cost or 0),
        )


# ---------------------------------------------------------------- knowledge
class SqlAlchemyKnowledgeRepository:
    """Vector retrieval, scoped by owner.

    The ``owner_user_id`` predicate below is the single most security-sensitive line in
    the AI feature: without it a similarity search happily returns another user's private
    summaries, and the model will quote them verbatim (docs/10 §3.2).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        embedding: Sequence[float],
        owner_user_id: UUID | None,
        scopes: Sequence[str],
        limit: int,
    ) -> list[KnowledgeChunk]:
        if not scopes or limit <= 0:
            return []

        vector = list(embedding)
        distance = AiEmbeddingModel.embedding.cosine_distance(vector)
        # Global rows are readable by everyone; owned rows only by their owner. Expressed
        # as one predicate so there is no code path that reaches the owned rows without it.
        visible: ColumnElement[bool] = AiEmbeddingModel.owner_user_id.is_(None)
        if owner_user_id is not None:
            visible = or_(visible, AiEmbeddingModel.owner_user_id == owner_user_id)

        stmt = (
            select(AiEmbeddingModel, distance.label("distance"))
            .where(AiEmbeddingModel.scope.in_(list(scopes)), visible)
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            KnowledgeChunk(
                id=model.id,
                scope=model.scope,
                chunk_text=model.chunk_text,
                source_type=model.source_type,
                source_id=model.source_id,
                metadata=model.embedding_metadata,
                # Cosine distance in [0, 2]; similarity is the friendlier direction.
                similarity=float(1.0 - dist),
            )
            for model, dist in rows
        ]

    async def add(
        self,
        chunk: KnowledgeChunk,
        embedding: Sequence[float],
        *,
        owner_user_id: UUID | None = None,
    ) -> None:
        """``owner_user_id`` must be set for ``user_summary`` chunks and unset otherwise.

        The database enforces the same rule, so a mismatch fails loudly rather than
        quietly publishing one user's summary into the global corpus.
        """
        self._session.add(
            AiEmbeddingModel(
                id=chunk.id,
                scope=chunk.scope,
                owner_user_id=owner_user_id,
                source_type=chunk.source_type,
                source_id=chunk.source_id,
                chunk_text=chunk.chunk_text,
                embedding=list(embedding),
                embedding_metadata=chunk.metadata,
            )
        )
        await self._session.flush()
