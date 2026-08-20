"""ORM models for the nutrition domain."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from coresync.infrastructure.database.base import Base, SoftDeleteMixin, TimestampMixin


class FoodBrandModel(Base):
    __tablename__ = "food_brands"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class FoodModel(SoftDeleteMixin, TimestampMixin, Base):
    """A food, with macros denormalised per 100 g.

    Every diary read needs exactly those five numbers; joining `food_nutrients` four
    times per entry to assemble them would be absurd (docs/03 §7).
    """

    __tablename__ = "foods"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("food_brands.id", ondelete="SET NULL")
    )
    # NULL means public. A custom food is searchable only by its owner.
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    trust_tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    calories_per_100g: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    protein_per_100g: Mapped[Decimal] = mapped_column(
        Numeric(9, 3), nullable=False, server_default="0"
    )
    carbs_per_100g: Mapped[Decimal] = mapped_column(
        Numeric(9, 3), nullable=False, server_default="0"
    )
    fat_per_100g: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False, server_default="0")
    # Ethanol, at 7 kcal/g. Without it the energy check rejects every alcoholic drink.
    alcohol_per_100g: Mapped[Decimal] = mapped_column(
        Numeric(9, 3), nullable=False, server_default="0"
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_liquid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    servings: Mapped[list[FoodServingModel]] = relationship(
        back_populates="food", cascade="all, delete-orphan", lazy="selectin"
    )
    barcodes: Mapped[list[FoodBarcodeModel]] = relationship(
        back_populates="food", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("source IN ('curated','off','usda','user')", name="food_source_valid"),
        CheckConstraint("trust_tier BETWEEN 1 AND 4", name="trust_tier_valid"),
        CheckConstraint("calories_per_100g >= 0", name="calories_positive"),
        CheckConstraint(
            "protein_per_100g >= 0 AND carbs_per_100g >= 0 AND fat_per_100g >= 0",
            name="macros_positive",
        ),
        # The last line against a misplaced decimal point.
        CheckConstraint(
            "calories_per_100g = 0 OR "
            "abs(calories_per_100g - (protein_per_100g*4 + carbs_per_100g*4 "
            "+ fat_per_100g*9 + alcohol_per_100g*7)) "
            "<= greatest(50, calories_per_100g * 0.25)",
            name="energy_sane",
        ),
        Index(
            "ix_foods_owner", "owner_user_id", postgresql_where=text("owner_user_id IS NOT NULL")
        ),
    )


class FoodServingModel(Base):
    """A household unit and its gram equivalent."""

    __tablename__ = "food_servings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    food_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    grams: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    food: Mapped[FoodModel] = relationship(back_populates="servings")

    __table_args__ = (
        CheckConstraint("grams > 0", name="serving_grams_positive"),
        Index("ix_food_servings_food", "food_id"),
    )


class FoodBarcodeModel(Base):
    """One product carries several EANs across regions and pack sizes."""

    __tablename__ = "food_barcodes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    food_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), nullable=False
    )
    barcode: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    food: Mapped[FoodModel] = relationship(back_populates="barcodes")

    __table_args__ = (Index("ix_food_barcodes_food", "food_id"),)


class NutrientModel(Base):
    """Reference list. Adding vitamin K is one row, not a migration."""

    __tablename__ = "nutrients"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("unit IN ('g','mg','mcg','IU')", name="nutrient_unit_valid"),
        CheckConstraint(
            "category IN ('macro','vitamin','mineral','other')", name="nutrient_category_valid"
        ),
    )


class FoodNutrientModel(Base):
    __tablename__ = "food_nutrients"

    food_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True
    )
    nutrient_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("nutrients.id", ondelete="RESTRICT"), primary_key=True
    )
    amount_per_100g: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    __table_args__ = (CheckConstraint("amount_per_100g >= 0", name="nutrient_amount_positive"),)


class RecipeModel(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "recipes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    servings_count: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)

    ingredients: Mapped[list[RecipeIngredientModel]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("servings_count > 0", name="servings_positive"),
        Index("ix_recipes_user", "user_id"),
    )


class RecipeIngredientModel(Base):
    """References a food rather than copying it.

    A recipe is a *definition*, so it stays correct as food data is corrected — the
    opposite of a diary entry, which is a *record* and snapshots instead.
    """

    __tablename__ = "recipe_ingredients"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    recipe_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False
    )
    food_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("foods.id", ondelete="RESTRICT"), nullable=False
    )
    grams: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    recipe: Mapped[RecipeModel] = relationship(back_populates="ingredients")

    __table_args__ = (
        CheckConstraint("grams > 0", name="ingredient_grams_positive"),
        Index("ix_recipe_ingredients_recipe", "recipe_id"),
    )


class DiaryEntryModel(SoftDeleteMixin, TimestampMixin, Base):
    """One logged item, with its nutrition snapshotted at the moment of logging.

    Recomputing from `foods` on read would mean a moderator correction silently
    rewrites the user's history, and every trend and AI conclusion built on it
    (docs/03 §7).
    """

    __tablename__ = "diary_entries"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(Text, nullable=False)
    # RESTRICT: you cannot delete a food somebody has eaten.
    food_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("foods.id", ondelete="RESTRICT")
    )
    recipe_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recipes.id", ondelete="RESTRICT")
    )
    serving_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("food_servings.id", ondelete="SET NULL")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False)
    total_grams: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False, server_default="0")
    display_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    calories: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    protein_g: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False, server_default="0")
    carbs_g: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False, server_default="0")
    fat_g: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False, server_default="0")
    alcohol_g: Mapped[Decimal] = mapped_column(Numeric(9, 3), nullable=False, server_default="0")
    micronutrients: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "meal_type IN ('breakfast','lunch','dinner','snack')", name="meal_type_valid"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        # A food, a recipe, or a bare quick-add — never two at once.
        CheckConstraint("num_nonnulls(food_id, recipe_id) <= 1", name="diary_source_valid"),
    )


class WaterLogModel(Base):
    """Separate from any daily summary: the timestamps drive reminder timing."""

    __tablename__ = "water_logs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    millilitres: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("millilitres > 0", name="water_positive"),
        Index("ix_water_logs_user_date", "user_id", "local_date"),
    )


class FavoriteFoodModel(Base):
    __tablename__ = "favorite_foods"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    food_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
