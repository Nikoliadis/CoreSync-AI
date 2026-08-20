"""Earned achievements (Phase 6).

One table. The composite primary key on `(user_id, code)` is the whole design: it makes
double-awarding impossible at the database level rather than relying on the evaluator
checking first, which matters because the evaluator can run concurrently from a request
and a scheduled job.

There is deliberately no `revoked_at`. An achievement that can be taken away is a
punishment wearing a trophy's clothes (docs/09 §1).

Revision ID: 0007_achievements
Revises: 0006_constraint_names
Created: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_achievements"
down_revision: str | None = "0006_constraint_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_achievements",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Not a foreign key: definitions live in code and are versioned with it, so a
        # row naming a retired achievement still reads fine rather than blocking a
        # deploy.
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column(
            "earned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        "CREATE INDEX ix_user_achievements_user ON user_achievements (user_id, earned_at DESC)"
    )


def downgrade() -> None:
    op.drop_table("user_achievements")
