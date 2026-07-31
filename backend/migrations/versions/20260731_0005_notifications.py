"""Notifications, delivery outbox and per-user preferences (Phase 6).

The outbox is the reason this is three tables rather than one. A notification is
written in the same transaction as the event that caused it, and the delivery
attempts hang off it separately — so a crash between "PR detected" and "push sent"
loses nothing, and a failed push does not retry the email alongside it.

Revision ID: 0005_notifications
Revises: 0004_ai_coach
Created: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_notifications"
down_revision: str | None = "0004_ai_coach"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMPED = ("notifications", "notification_preferences")


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deep_link", sa.String(200)),
        sa.Column(
            "data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("read_at", sa.DateTime(timezone=True)),
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
            "category IN ('workout_reminder','pr_celebration','streak_risk',"
            "'insight_ready','weekly_report','system')",
            name="category_valid",
        ),
    )
    # The unread badge is read on every app open; a partial index keeps it off the
    # lifetime of already-read rows.
    op.execute(
        """
        CREATE INDEX ix_notifications_user_unread
        ON notifications (user_id, created_at DESC)
        WHERE read_at IS NULL
        """
    )
    op.execute(
        "CREATE INDEX ix_notifications_user_recent ON notifications (user_id, created_at DESC)"
    )

    op.create_table(
        "notification_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(10), nullable=False),
        # When it may be sent. Quiet hours push this forward rather than dropping the
        # row, so a late-night PR still arrives at breakfast.
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("channel IN ('push','email','in_app')", name="channel_valid"),
        sa.CheckConstraint(
            "status IN ('pending','sent','failed','skipped')", name="delivery_status_valid"
        ),
    )
    # The dispatcher's only query. Partial, because sent rows are the overwhelming
    # majority and it never looks at them again.
    op.execute(
        """
        CREATE INDEX ix_outbox_due
        ON notification_outbox (scheduled_for)
        WHERE status = 'pending'
        """
    )
    op.create_index("ix_outbox_notification", "notification_outbox", ["notification_id"])

    op.create_table(
        "notification_preferences",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "enabled_categories",
            postgresql.ARRAY(sa.String(30)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("quiet_hours_start", sa.Integer()),
        sa.Column("quiet_hours_end", sa.Integer()),
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
            "quiet_hours_start IS NULL OR (quiet_hours_start >= 0 AND quiet_hours_start <= 23)",
            name="quiet_start_valid",
        ),
        sa.CheckConstraint(
            "quiet_hours_end IS NULL OR (quiet_hours_end >= 0 AND quiet_hours_end <= 23)",
            name="quiet_end_valid",
        ),
    )

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
    op.drop_table("notification_preferences")
    op.drop_table("notification_outbox")
    op.drop_table("notifications")
