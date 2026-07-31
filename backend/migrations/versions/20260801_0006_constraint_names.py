"""Repair doubled CHECK constraint names from migrations 0001 and 0002.

Those two migrations passed already-prefixed names (``ck_exercises_force_type_valid``)
to constraints that the metadata naming convention then prefixed again, producing
``ck_exercises_ck_exercises_force_type_valid``. Seventy constraints are affected, and
three exceeded Postgres' 63-character identifier limit and were truncated to a hash —
``ck_daily_activity_summaries_ck_daily_activity_summaries_6afb`` tells you nothing at
all about which rule a violation broke.

Purely a rename: ``ALTER TABLE … RENAME CONSTRAINT`` is a catalogue update, with no
table rewrite, no lock beyond a brief ACCESS EXCLUSIVE, and no effect on data.

Migrations 0003 onward pass bare names and are already correct, so nothing here needs
to change to stop it recurring.

Revision ID: 0006_constraint_names
Revises: 0005_notifications
Created: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_constraint_names"
down_revision: str | None = "0005_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Three constraints on this table overflowed the 63-character identifier limit and
# were truncated to a hash, so their intended names cannot be recovered from the
# catalogue. They are identified by the column each one guards — matching the whole
# expression is too brittle, since Postgres renders `>= 0` as `>= (0)::numeric` on a
# numeric column. Names read back from the `sa.CheckConstraint(...)` calls in 0002.
TRUNCATED_TABLE = "daily_activity_summaries"
TRUNCATED_BY_COLUMN: dict[str, str] = {
    "workout_count": "ck_daily_activity_summaries_workout_count_positive",
    "total_volume_kg": "ck_daily_activity_summaries_volume_positive",
    "total_sets": "ck_daily_activity_summaries_sets_positive",
}


def upgrade() -> None:
    connection = op.get_bind()

    # Data-driven rather than a hard-coded list of seventy: the exact set depends on
    # which migrations a given database has run, and a list would drift.
    rows = connection.execute(
        sa.text(
            """
            SELECT c.conname, t.relname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public'
              AND c.contype = 'c'
              AND c.conname LIKE 'ck_' || t.relname || '_ck_' || t.relname || '_%'
            """
        )
    ).all()

    for conname, table in rows:
        # Strip exactly one repetition, leaving `ck_<table>_<rule>`.
        repaired = conname[len(f"ck_{table}_") :]
        if repaired == conname:
            continue
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{conname}" TO "{repaired}"')

    # Second pass, for the names that were truncated to a hash before this migration
    # ever saw them. Written separately so the whole thing stays idempotent: a
    # half-repaired database re-run of this migration still lands in the right place.
    hashed = connection.execute(
        sa.text(
            """
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE contype = 'c'
              -- CAST rather than `:name::regclass`: the driver parses the `::` as the
              -- start of another bind parameter and the statement fails to compile.
              AND conrelid = CAST(:table_name AS regclass)
              AND conname ~ '_[0-9a-f]{4}$'
            """
        ),
        {"table_name": TRUNCATED_TABLE},
    ).all()

    for conname, definition in hashed:
        for column, intended in TRUNCATED_BY_COLUMN.items():
            if column in (definition or ""):
                op.execute(
                    f'ALTER TABLE "{TRUNCATED_TABLE}" RENAME CONSTRAINT "{conname}" TO "{intended}"'
                )
                break


def downgrade() -> None:
    """Deliberately a no-op.

    Restoring the doubled names would mean reconstructing the truncation hashes that
    Postgres generated, which are not reproducible from the repaired names. Since the
    old names carried no information, there is nothing worth restoring — and a
    downgrade that silently produced *different* wrong names would be worse than one
    that does nothing.
    """
