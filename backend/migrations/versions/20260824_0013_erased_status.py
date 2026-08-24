"""An `erased` account status (Phase 6).

Account deletion is a soft delete with a thirty-day grace period, and the hard erasure
that follows it has never existed — the use case docstring said it "runs as a separate
scheduled job" and no such job was written.

Erasure here anonymises rather than deleting the row. Personal data goes: email, name,
date of birth, every weigh-in, measurement, photo, diary entry and workout. What stays is
the account row with a scrubbed identity and the derived daily aggregates, so platform
statistics remain truthful about what happened rather than rewriting history every time
somebody leaves.

`erased` is distinct from `deleted` because they mean different things operationally.
`deleted` is reversible and the user may still change their mind; `erased` is finished,
and a row in that state must never be treated as recoverable or counted as a user.

Revision ID: 0013_erased_status
Revises: 0012_food_submissions
Created: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_erased_status"
down_revision: str | None = "0012_food_submissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_users_status_valid"


def upgrade() -> None:
    op.execute(f"ALTER TABLE users DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE users ADD CONSTRAINT {_CONSTRAINT} "
        "CHECK (status IN ('pending','active','suspended','deleted','erased'))"
    )


def downgrade() -> None:
    # Anything already erased becomes `deleted` again, or the narrowed constraint cannot
    # be applied. The data is gone either way — this only restores a legal status value.
    op.execute("UPDATE users SET status = 'deleted' WHERE status = 'erased'")
    op.execute(f"ALTER TABLE users DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE users ADD CONSTRAINT {_CONSTRAINT} "
        "CHECK (status IN ('pending','active','suspended','deleted'))"
    )
