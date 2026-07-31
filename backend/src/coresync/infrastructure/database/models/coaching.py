"""ORM models for the AI coach."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from coresync.infrastructure.database.base import Base, SoftDeleteMixin, TimestampMixin

EMBEDDING_DIMENSIONS = 1536


class AiConversationModel(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "ai_conversations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    # A rolling précis of older turns, so a long relationship stays coherent without the
    # context growing without bound.
    summary: Mapped[str | None] = mapped_column(Text)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    messages: Mapped[list[AiMessageModel]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_ai_conversations_user_recent",
            "user_id",
            text("last_message_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class AiMessageModel(TimestampMixin, Base):
    __tablename__ = "ai_messages"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # The bundle that produced this reply. Makes "why did the coach say that?" answerable
    # months later, which is mandatory for a health-adjacent product.
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    # Set when the message was intercepted by triage. The category is recorded; the text
    # that triggered it is not analysed further (docs/10 §7.2).
    safety_category: Mapped[str | None] = mapped_column(String(30))

    conversation: Mapped[AiConversationModel] = relationship(back_populates="messages")
    tool_calls: Mapped[list[AiToolCallModel]] = relationship(
        back_populates="message", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system','tool')", name="role_valid"),
        Index("ix_ai_messages_conversation", "conversation_id", "created_at"),
    )


class AiToolCallModel(Base):
    """Every tool invocation, with arguments.

    The audit trail behind a coaching answer, and the record that would show an injection
    attempt reaching the tool layer (docs/10 §4).
    """

    __tablename__ = "ai_tool_calls"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ai_messages.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    result_summary: Mapped[str | None] = mapped_column(Text)
    result_bytes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_error: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    error_code: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    message: Mapped[AiMessageModel] = relationship(back_populates="tool_calls")

    __table_args__ = (Index("ix_ai_tool_calls_message", "message_id"),)


class AiInsightModel(TimestampMixin, Base):
    __tablename__ = "ai_insights"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    insight_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # The data that justified it. An insight a user cannot interrogate is an assertion.
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feedback: Mapped[str | None] = mapped_column(String(20))

    __table_args__ = (
        CheckConstraint(
            "insight_type IN ('plateau','deficit_mismatch','low_protein',"
            "'volume_imbalance','overreaching','streak_risk')",
            name="insight_type_valid",
        ),
        CheckConstraint("severity IN ('info','suggestion','warning')", name="severity_valid"),
        CheckConstraint(
            "feedback IS NULL OR feedback IN ('helpful','not_helpful')", name="feedback_valid"
        ),
        Index(
            "ix_ai_insights_user_active",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("acknowledged_at IS NULL"),
        ),
        Index("ix_ai_insights_user_type", "user_id", "insight_type", text("created_at DESC")),
    )


class AiUsageLogModel(Base):
    """Per-call token and cost metering.

    Written for failures as well as successes: a provider that errors after consuming
    prompt tokens still costs money, and a cost dashboard that only counts successes
    understates spend exactly when something is going wrong.
    """

    __tablename__ = "ai_usage_logs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feature: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    task_class: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60))
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('ok','error','filtered','timeout')", name="status_valid"),
        CheckConstraint("cost_usd >= 0", name="cost_positive"),
        # The quota lookup: one user's spend for one day.
        Index("ix_ai_usage_user_day", "user_id", "local_date"),
        Index("ix_ai_usage_cost", text("created_at DESC"), "feature"),
    )


class AiEmbeddingModel(Base):
    """The retrieval corpus.

    ``owner_user_id`` is the scope that matters: NULL is global knowledge, non-NULL is one
    user's private summaries. Every retrieval query filters on it — a miss here puts one
    user's data into another's coaching answer (docs/10 §3.2).
    """

    __tablename__ = "ai_embeddings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    embedding_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "scope IN ('knowledge','user_summary','exercise','food')", name="scope_valid"
        ),
        # A user-scoped chunk must name its owner, and global knowledge must not.
        CheckConstraint(
            "(scope = 'user_summary') = (owner_user_id IS NOT NULL)",
            name="scope_matches_owner",
        ),
        Index(
            "ix_ai_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_ai_embeddings_scope", "scope", "owner_user_id"),
    )
