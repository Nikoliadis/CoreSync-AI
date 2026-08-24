"""Let a deleted user's foods take their recipe ingredients with them (Phase 3).

Migration 0008 gave ``recipe_ingredients.food_id`` ON DELETE RESTRICT, reasoning that a
food should not vanish from under a recipe and silently change its totals. That reasoning
is right about the case it considered and wrong about the one it did not.

Foods are soft-deleted. A user removing their own custom food sets ``deleted_at`` and the
row stays, so RESTRICT never fires on the path it was written for. The only hard delete of
a food is the cascade from deleting its owner — and there RESTRICT blocks the erasure
entirely: ``DELETE FROM users`` cascades to that user's custom foods, and the ingredient
rows refuse to let go.

The effect is that **any user who put one of their own foods into a recipe cannot be
deleted**. Account deletion already exists as a soft delete with a thirty-day grace
period, and the hard-erasure job that follows it would fail on exactly these users. That
is a right-to-erasure obligation failing closed, which is not a tradeoff anyone chose.

CASCADE instead. The domain was already built for a missing ingredient: ``total_macros``
skips one rather than counting it as zero, and ``has_missing_ingredients`` surfaces the
gap so the under-reported total is visible rather than quietly wrong.

``diary_entries.food_id`` has the same defect for the same reason and needs the opposite
fix. CASCADE there would delete the record of what somebody ate, which is the one thing
the diary exists to keep. The entry already snapshots its macros and its display name, so
SET NULL costs nothing: the row survives intact and only the back-reference goes. Entries
from quick-add already carry a null food_id, so nothing downstream is surprised by one.

Revision ID: 0010_ingredient_cascade
Revises: 0009_alcohol
Created: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_ingredient_cascade"
down_revision: str | None = "0009_alcohol"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INGREDIENT_FK = "fk_recipe_ingredients_food_id_foods"
_DIARY_FK = "fk_diary_entries_food_id_foods"


def upgrade() -> None:
    # Raw SQL rather than op.drop_constraint: the metadata naming convention re-prefixes
    # a name that already carries its prefix, which is how 0006 ended up repairing
    # seventy constraints called `ck_foods_ck_foods_...`.
    op.execute(f"ALTER TABLE recipe_ingredients DROP CONSTRAINT {_INGREDIENT_FK}")
    op.execute(
        f"ALTER TABLE recipe_ingredients ADD CONSTRAINT {_INGREDIENT_FK} "
        "FOREIGN KEY (food_id) REFERENCES foods (id) ON DELETE CASCADE"
    )

    op.execute(f"ALTER TABLE diary_entries DROP CONSTRAINT {_DIARY_FK}")
    op.execute(
        f"ALTER TABLE diary_entries ADD CONSTRAINT {_DIARY_FK} "
        "FOREIGN KEY (food_id) REFERENCES foods (id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE diary_entries DROP CONSTRAINT {_DIARY_FK}")
    op.execute(
        f"ALTER TABLE diary_entries ADD CONSTRAINT {_DIARY_FK} "
        "FOREIGN KEY (food_id) REFERENCES foods (id) ON DELETE RESTRICT"
    )

    op.execute(f"ALTER TABLE recipe_ingredients DROP CONSTRAINT {_INGREDIENT_FK}")
    op.execute(
        f"ALTER TABLE recipe_ingredients ADD CONSTRAINT {_INGREDIENT_FK} "
        "FOREIGN KEY (food_id) REFERENCES foods (id) ON DELETE RESTRICT"
    )
