"""AI coach tables and the pgvector extension (Phase 5).

Hand-written like the others. Two things here are load-bearing and autogenerate emits
neither: the ``vector`` extension (no earlier migration creates it — only the container
init SQL does, which does not run for test databases or a managed Postgres) and the
scope/owner constraint on ``ai_embeddings``, which is the structural half of the
guarantee that one user's summaries can never be retrieved into another's answer.

Revision ID: 0004_ai_coach
Revises: 0003_progress_body
Created: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004_ai_coach"
down_revision: str | None = "0003_progress_body"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches text-embedding-3-small. Changing this is a re-embedding exercise, not a column
# alteration, so it is pinned in one place and asserted against the adapter in tests.
EMBEDDING_DIMENSIONS = 1536

_TIMESTAMPED = ("ai_conversations", "ai_messages", "ai_insights")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ai_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200)),
        sa.Column("summary", sa.Text()),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        """
        CREATE INDEX ix_ai_conversations_user_recent
        ON ai_conversations (user_id, last_message_at DESC)
        WHERE deleted_at IS NULL
        """
    )

    op.create_table(
        "ai_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # The bundle that produced this reply, so "why did the coach say that?" stays
        # answerable months later.
        sa.Column(
            "context_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(80)),
        sa.Column("prompt_version", sa.String(40)),
        # The category only. The text that triggered triage is never stored here.
        sa.Column("safety_category", sa.String(30)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("role IN ('user','assistant','system','tool')", name="role_valid"),
    )
    op.create_index("ix_ai_messages_conversation", "ai_messages", ["conversation_id", "created_at"])

    op.create_table(
        "ai_tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(60), nullable=False),
        sa.Column(
            "arguments", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("result_summary", sa.Text()),
        sa.Column("result_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_error", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("error_code", sa.String(60)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_ai_tool_calls_message", "ai_tool_calls", ["message_id"])

    op.create_table(
        "ai_insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("insight_type", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("feedback", sa.String(20)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "insight_type IN ('plateau','deficit_mismatch','low_protein',"
            "'volume_imbalance','overreaching','streak_risk')",
            name="insight_type_valid",
        ),
        sa.CheckConstraint("severity IN ('info','suggestion','warning')", name="severity_valid"),
        sa.CheckConstraint(
            "feedback IS NULL OR feedback IN ('helpful','not_helpful')", name="feedback_valid"
        ),
    )
    op.execute(
        """
        CREATE INDEX ix_ai_insights_user_active
        ON ai_insights (user_id, created_at DESC)
        WHERE acknowledged_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_ai_insights_user_type
        ON ai_insights (user_id, insight_type, created_at DESC)
        """
    )

    op.create_table(
        "ai_usage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("task_class", sa.String(20), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("error_code", sa.String(60)),
        # The user's local day, so a quota resets at their midnight rather than UTC's.
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("status IN ('ok','error','filtered','timeout')", name="status_valid"),
        sa.CheckConstraint("cost_usd >= 0", name="cost_positive"),
    )
    op.create_index("ix_ai_usage_user_day", "ai_usage_logs", ["user_id", "local_date"])
    op.execute("CREATE INDEX ix_ai_usage_cost ON ai_usage_logs (created_at DESC, feature)")

    op.create_table(
        "ai_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(20), nullable=False),
        # NULL means global knowledge; non-NULL means one user's private summaries.
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
        ),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True)),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "scope IN ('knowledge','user_summary','exercise','food')", name="scope_valid"
        ),
        # A user-scoped chunk must name its owner and global knowledge must not. Without
        # this a mis-set scope makes private text retrievable by everyone.
        sa.CheckConstraint(
            "(scope = 'user_summary') = (owner_user_id IS NOT NULL)", name="scope_matches_owner"
        ),
    )
    # HNSW over cosine distance: higher build cost than IVFFlat but no training step and
    # no rebuild as the corpus grows, which suits a table written to continuously.
    op.execute(
        """
        CREATE INDEX ix_ai_embeddings_hnsw
        ON ai_embeddings USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
    op.create_index("ix_ai_embeddings_scope", "ai_embeddings", ["scope", "owner_user_id"])

    for table in _TIMESTAMPED:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in _TIMESTAMPED:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.drop_table("ai_embeddings")
    op.drop_table("ai_usage_logs")
    op.drop_table("ai_insights")
    op.drop_table("ai_tool_calls")
    op.drop_table("ai_messages")
    op.drop_table("ai_conversations")
    # The extension is left in place: other schemas may depend on it, and dropping it
    # would cascade to their columns.
