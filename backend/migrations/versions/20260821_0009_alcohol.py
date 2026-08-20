"""Track alcohol as a fourth energy source (Phase 3).

The energy-sanity constraint from 0008 reconciles calories against protein, carbohydrate
and fat at 4/4/9 kcal per gram. Ethanol carries **7 kcal/g** and is none of those, so
any drink whose calories come mostly from alcohol fails a check that is working exactly
as designed.

Red wine is the clearest case: 85 kcal per 100 g against 2.6 g carbohydrate, which
implies 11 kcal. That is a 74 kcal gap on a 50 kcal tolerance, so the row is rejected.
Beer slipped through only because its gap happened to fall under the absolute floor.

This is not a tolerance problem and widening the band would be the wrong fix — the band
is what catches a misplaced decimal point. The missing term is alcohol, so it is added
as a column and folded into the reconciliation.

Without this, a bulk import of European food data would silently drop every beer, wine
and spirit it contained.

Revision ID: 0009_alcohol
Revises: 0008_nutrition
Created: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_alcohol"
down_revision: str | None = "0008_nutrition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "foods",
        sa.Column("alcohol_per_100g", sa.Numeric(9, 3), nullable=False, server_default="0"),
    )
    op.add_column(
        "diary_entries",
        sa.Column("alcohol_g", sa.Numeric(9, 3), nullable=False, server_default="0"),
    )

    op.create_check_constraint("alcohol_positive", "foods", "alcohol_per_100g >= 0")

    # Replaced rather than amended: a CHECK constraint cannot be altered in place.
    op.drop_constraint("energy_sane", "foods", type_="check")
    op.create_check_constraint(
        "energy_sane",
        "foods",
        "calories_per_100g = 0 OR "
        "abs(calories_per_100g - (protein_per_100g*4 + carbs_per_100g*4 "
        "+ fat_per_100g*9 + alcohol_per_100g*7)) "
        "<= greatest(50, calories_per_100g * 0.25)",
    )


def downgrade() -> None:
    op.drop_constraint("energy_sane", "foods", type_="check")
    op.create_check_constraint(
        "energy_sane",
        "foods",
        "calories_per_100g = 0 OR "
        "abs(calories_per_100g - (protein_per_100g*4 + carbs_per_100g*4 + fat_per_100g*9)) "
        "<= greatest(50, calories_per_100g * 0.25)",
    )
    op.drop_constraint("alcohol_positive", "foods", type_="check")
    op.drop_column("diary_entries", "alcohol_g")
    op.drop_column("foods", "alcohol_per_100g")
