"""The nutrition domain (Phase 3).

Follows docs/03 §7. Three decisions in here are load-bearing and worth stating rather
than leaving to be rediscovered:

**Macros are denormalised onto `foods`.** Every diary read needs exactly five numbers.
Joining `food_nutrients` four times per entry to assemble them would be absurd, so the
macros live on the row and the full micronutrient set stays normalised beside it.

**`diary_entries` snapshots its nutrition.** Food data gets corrected — by moderators,
by upstream imports, by a brand reformulating. If yesterday's diary recalculated from
today's food row, the user's history would change under them and every trend and every
AI conclusion built on it would be wrong. A diary entry records what was true then.

**`diary_entries.food_id` is ON DELETE RESTRICT.** You cannot delete a food somebody
has eaten. Corrections happen by soft-delete and replacement, never by breaking history.

Revision ID: 0008_nutrition
Revises: 0007_achievements
Created: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_nutrition"
down_revision: str | None = "0007_achievements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMPED = ("foods", "recipes", "diary_entries")


def upgrade() -> None:
    # Fuzzy name search. Already present from 0001, but stated here so this migration
    # stands alone on a database that only ran part of the history.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # Diacritic-insensitive search. Not cosmetic for this product: Greek users type
    # "γιαουρτι" for "γιαούρτι" constantly, and without this the full-text match simply
    # fails while trigram similarity drops to 0.5. Same story for French, Spanish,
    # Portuguese and German product names, which is most of a European food database.
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    op.create_table(
        "food_brands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("CREATE UNIQUE INDEX uq_food_brands_name ON food_brands (lower(name))")

    op.create_table(
        "foods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "brand_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("food_brands.id", ondelete="SET NULL"),
        ),
        # NULL means public. A custom food is searchable only by its owner — the same
        # single-table pattern the exercise catalog uses.
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        # 1 = in-house curated, 2 = official reference, 3 = community, 4 = user.
        # Search ranks by this before anything else; the UI badges tier 1 as "Verified".
        sa.Column("trust_tier", sa.SmallInteger(), nullable=False),
        sa.Column("calories_per_100g", sa.Numeric(8, 2), nullable=False),
        sa.Column("protein_per_100g", sa.Numeric(9, 3), nullable=False, server_default="0"),
        sa.Column("carbs_per_100g", sa.Numeric(9, 3), nullable=False, server_default="0"),
        sa.Column("fat_per_100g", sa.Numeric(9, 3), nullable=False, server_default="0"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_liquid", sa.Boolean(), nullable=False, server_default="false"),
        # Popularity, which breaks ranking ties below trust tier.
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.CheckConstraint("source IN ('curated','off','usda','user')", name="food_source_valid"),
        sa.CheckConstraint("trust_tier BETWEEN 1 AND 4", name="trust_tier_valid"),
        sa.CheckConstraint("calories_per_100g >= 0", name="calories_positive"),
        sa.CheckConstraint(
            "protein_per_100g >= 0 AND carbs_per_100g >= 0 AND fat_per_100g >= 0",
            name="macros_positive",
        ),
        # Macros must roughly reconcile with calories at 4/4/9 kcal per gram. The floor
        # of 50 exists because 25% of a 20 kcal food is 5 kcal, which label rounding
        # alone can breach. This is the last line against a misplaced decimal point.
        sa.CheckConstraint(
            "calories_per_100g = 0 OR "
            "abs(calories_per_100g - (protein_per_100g*4 + carbs_per_100g*4 + fat_per_100g*9)) "
            "<= greatest(50, calories_per_100g * 0.25)",
            name="energy_sane",
        ),
    )

    # `unaccent` is not immutable by default, so it cannot be called directly in a
    # generated column. This wrapper pins the dictionary and declares the immutability
    # Postgres needs — the standard workaround, and safe because the dictionary is
    # fixed at definition time rather than resolved per call.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION immutable_unaccent(text)
        RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS
        $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
        """
    )

    # Generated rather than trigger-maintained: a tsvector that can drift out of step
    # with the name is a search index that lies. `simple` rather than a language
    # configuration because the catalogue is multilingual — English stemming applied to
    # Greek or French product names does more harm than no stemming at all.
    op.execute(
        """
        ALTER TABLE foods ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('simple', immutable_unaccent(coalesce(name,''))), 'A')
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_foods_search ON foods USING GIN (search_vector)")
    op.execute(
        """
        CREATE INDEX ix_foods_name_trgm
        ON foods USING GIN (immutable_unaccent(name) gin_trgm_ops)
        """
    )
    # The public-search hot path: never looks at custom or deleted rows.
    op.execute(
        """
        CREATE INDEX ix_foods_ranking ON foods (trust_tier, usage_count DESC)
        WHERE deleted_at IS NULL AND owner_user_id IS NULL
        """
    )
    op.execute(
        "CREATE INDEX ix_foods_owner ON foods (owner_user_id) WHERE owner_user_id IS NOT NULL"
    )

    op.create_table(
        "food_servings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "food_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("foods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("grams", sa.Numeric(9, 3), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.CheckConstraint("grams > 0", name="serving_grams_positive"),
    )
    op.create_index("ix_food_servings_food", "food_servings", ["food_id"])
    # At most one default per food, or the client has to guess which to preselect.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_food_servings_default
        ON food_servings (food_id) WHERE is_default
        """
    )

    op.create_table(
        "food_barcodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "food_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("foods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # One product carries several EANs across regions and pack sizes, which is why
        # this is a table and not a column on `foods`.
        sa.Column("barcode", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("CREATE UNIQUE INDEX uq_food_barcodes_code ON food_barcodes (barcode)")
    op.create_index("ix_food_barcodes_food", "food_barcodes", ["food_id"])

    op.create_table(
        "nutrients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.CheckConstraint("unit IN ('g','mg','mcg','IU')", name="nutrient_unit_valid"),
        sa.CheckConstraint(
            "category IN ('macro','vitamin','mineral','other')", name="nutrient_category_valid"
        ),
    )

    op.create_table(
        "food_nutrients",
        sa.Column(
            "food_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("foods.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "nutrient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nutrients.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("amount_per_100g", sa.Numeric(12, 4), nullable=False),
        sa.CheckConstraint("amount_per_100g >= 0", name="nutrient_amount_positive"),
    )

    op.create_table(
        "recipes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("servings_count", sa.Numeric(6, 2), nullable=False),
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
        sa.CheckConstraint("servings_count > 0", name="servings_positive"),
    )
    op.create_index("ix_recipes_user", "recipes", ["user_id"])

    op.create_table(
        "recipe_ingredients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recipe_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT: an ingredient references a food so the recipe stays correct as food
        # data is corrected. Deleting the food underneath it would silently change the
        # recipe's totals.
        sa.Column(
            "food_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("foods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("grams", sa.Numeric(9, 3), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("grams > 0", name="ingredient_grams_positive"),
    )
    op.create_index("ix_recipe_ingredients_recipe", "recipe_ingredients", ["recipe_id"])

    op.create_table(
        "diary_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.Text(), nullable=False),
        sa.Column(
            "food_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("foods.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "recipe_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recipes.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "serving_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("food_servings.id", ondelete="SET NULL"),
        ),
        sa.Column("quantity", sa.Numeric(9, 3), nullable=False),
        sa.Column("total_grams", sa.Numeric(9, 3), nullable=False, server_default="0"),
        # Shown in the diary list without a join.
        sa.Column("display_name", sa.Text(), nullable=False, server_default=""),
        # The snapshot. See the module docstring.
        sa.Column("calories", sa.Numeric(8, 2), nullable=False),
        sa.Column("protein_g", sa.Numeric(9, 3), nullable=False, server_default="0"),
        sa.Column("carbs_g", sa.Numeric(9, 3), nullable=False, server_default="0"),
        sa.Column("fat_g", sa.Numeric(9, 3), nullable=False, server_default="0"),
        sa.Column(
            "micronutrients",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
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
        sa.CheckConstraint(
            "meal_type IN ('breakfast','lunch','dinner','snack')", name="meal_type_valid"
        ),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        # A food, a recipe, or a bare quick-add — never two at once.
        sa.CheckConstraint("num_nonnulls(food_id, recipe_id) <= 1", name="diary_source_valid"),
    )
    op.execute(
        """
        CREATE INDEX ix_diary_user_date
        ON diary_entries (user_id, local_date DESC, meal_type)
        WHERE deleted_at IS NULL
        """
    )
    # Powers "recent foods" without a separate table.
    op.execute(
        """
        CREATE INDEX ix_diary_user_food_recent
        ON diary_entries (user_id, food_id, logged_at DESC)
        WHERE deleted_at IS NULL
        """
    )

    op.create_table(
        "water_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("millilitres", sa.Numeric(8, 2), nullable=False),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("millilitres > 0", name="water_positive"),
    )
    op.create_index("ix_water_logs_user_date", "water_logs", ["user_id", "local_date"])

    op.create_table(
        "favorite_foods",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "food_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("foods.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
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
    op.drop_table("favorite_foods")
    op.drop_table("water_logs")
    op.drop_table("diary_entries")
    op.drop_table("recipe_ingredients")
    op.drop_table("recipes")
    op.drop_table("food_nutrients")
    op.drop_table("nutrients")
    op.drop_table("food_barcodes")
    op.drop_table("food_servings")
    op.drop_table("foods")
    op.drop_table("food_brands")
    op.execute("DROP FUNCTION IF EXISTS immutable_unaccent(text)")
