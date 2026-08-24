"""Daily nutrition summaries (Phase 3).

The diary currently recomputes a day's totals from its raw entries on every read. That
is correct and fine at one user; it is the wrong shape for the screens that are supposed
to read it — a dashboard showing thirty days would run thirty aggregations, and a
nutrition streak asks "did they log on each of the last N days", which is a question
about days rather than entries.

The mirror of ``daily_activity_summaries`` on the training side, deliberately: the two
are read together by the dashboard, and a different shape for each would put the join in
the client.

``entry_count`` is what the streak is computed from, not the calorie total. Someone who
logged a single black coffee has logged that day; requiring a calorie threshold would
mean a fasting day silently breaks a streak the person believes they kept.

Revision ID: 0011_nutrition_summaries
Revises: 0010_ingredient_cascade
Created: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_nutrition_summaries"
down_revision: str | None = "0010_ingredient_cascade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_nutrition_summaries",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("local_date", sa.Date(), primary_key=True),
        sa.Column("calories", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("protein_g", sa.Numeric(10, 3), nullable=False, server_default="0"),
        sa.Column("carbs_g", sa.Numeric(10, 3), nullable=False, server_default="0"),
        sa.Column("fat_g", sa.Numeric(10, 3), nullable=False, server_default="0"),
        sa.Column("alcohol_g", sa.Numeric(10, 3), nullable=False, server_default="0"),
        sa.Column("water_ml", sa.Numeric(10, 3), nullable=False, server_default="0"),
        # The streak's unit of account. A day with any entry is a logged day.
        sa.Column("entry_count", sa.SmallInteger(), nullable=False, server_default="0"),
        # The targets that were in force on that day, copied here so a historical chart
        # does not have to re-resolve a versioned target for every point it draws.
        sa.Column("target_calories", sa.Numeric(10, 2), nullable=True),
        sa.Column("target_protein_g", sa.Numeric(10, 3), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("calories >= 0", name="summary_calories_positive"),
        sa.CheckConstraint("entry_count >= 0", name="summary_entries_positive"),
    )
    op.create_index(
        "ix_daily_nutrition_user_date",
        "daily_nutrition_summaries",
        ["user_id", sa.text("local_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_nutrition_user_date", table_name="daily_nutrition_summaries")
    op.drop_table("daily_nutrition_summaries")
