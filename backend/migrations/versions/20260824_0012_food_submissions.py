"""Moderation queue for user-submitted foods (Phase 3).

A custom food is private to the person who made it. Some of them are genuinely useful to
everyone — a supermarket own-brand, a local bakery item — and the way that data gets into
a shared catalogue without becoming a liability is that a human looks at it first.

The queue is a separate table rather than a status column on `foods` because a food and
its review are different lifecycles: the food exists and is usable the whole time, the
review is a thing that happens to it once and may happen again after an edit.

Approval promotes to trust tier 2 (official), not tier 1. Tier 1 means a curator wrote
those numbers; tier 2 means a reviewer checked somebody else's. Collapsing the two would
put the verified badge on data nobody authored.

Revision ID: 0012_food_submissions
Revises: 0011_nutrition_summaries
Created: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_food_submissions"
down_revision: str | None = "0011_nutrition_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "food_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "food_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("foods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by",
            postgresql.UUID(as_uuid=True),
            # The submitter can delete their account while the item sits in the queue.
            # The review still needs to happen, so the row survives without them.
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')", name="submission_status_valid"
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (reviewed_at IS NULL)",
            name="submission_review_consistent",
        ),
    )

    # One open submission per food. A partial unique index rather than a plain one, so a
    # food rejected once can be fixed and submitted again — the alternative is a user
    # locked out of the queue by their own first attempt.
    op.create_index(
        "uq_food_submissions_pending",
        "food_submissions",
        ["food_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_food_submissions_queue",
        "food_submissions",
        ["status", sa.text("created_at ASC")],
    )


def downgrade() -> None:
    op.drop_index("ix_food_submissions_queue", table_name="food_submissions")
    op.drop_index("uq_food_submissions_pending", table_name="food_submissions")
    op.drop_table("food_submissions")
