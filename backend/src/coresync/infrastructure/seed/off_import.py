"""Bulk import of Open Food Facts products.

    python -m coresync.infrastructure.seed.off_import --country greece

Everything lands at trust tier 3 and unverified, so it fills the long tail without ever
outranking a curated row in search. Ids are derived from the barcode, so a re-run
updates in place rather than duplicating, and a run interrupted halfway can simply be
run again.

The energy check runs on every row before it is written. It is not a formality here: a
measured sample rejected 2% of Greek products, and the rejections were genuinely wrong
data rather than edge cases — a mayonnaise claiming 292 kcal against macros implying
712. Importing those would put confidently wrong numbers in front of people, which is
the fatal risk this phase is meant to guard against. Rejections are counted and logged
rather than silently dropped, because the rejection rate is the signal that tells us
whether the source is still trustworthy.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.core.config import Settings, get_settings
from coresync.core.logging import configure_logging, get_logger
from coresync.domain.nutrition.entities import FoodSource, Macros, TrustTier
from coresync.domain.nutrition.services import check_energy
from coresync.infrastructure.database.models.nutrition import (
    FoodBarcodeModel,
    FoodModel,
    FoodNutrientModel,
    FoodServingModel,
)
from coresync.infrastructure.database.session import Database
from coresync.infrastructure.external.openfoodfacts import OffProduct, OpenFoodFactsClient
from coresync.infrastructure.seed.nutrients import NUTRIENT_CODES, nutrient_id

logger = get_logger(__name__)

# Ids are a function of the barcode, so the same product always occupies the same row no
# matter how many times the import runs or which path first created it.
OFF_NAMESPACE = uuid5(NAMESPACE_URL, "https://openfoodfacts.org/product")

BATCH_SIZE = 500


def food_id_for(barcode: str) -> UUID:
    return uuid5(OFF_NAMESPACE, barcode.strip())


@dataclass(slots=True)
class ImportStats:
    seen: int = 0
    written: int = 0
    rejected_energy: int = 0
    rejected_examples: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def rejection_rate(self) -> float:
        return 0.0 if self.seen == 0 else self.rejected_energy / self.seen

    def as_dict(self) -> dict[str, object]:
        return {
            "seen": self.seen,
            "written": self.written,
            "rejected_energy": self.rejected_energy,
            "rejection_rate": round(self.rejection_rate, 4),
        }


def _macros_of(product: OffProduct) -> Macros:
    return Macros(
        calories=product.calories_per_100g,
        protein_g=product.protein_per_100g,
        carbs_g=product.carbs_per_100g,
        fat_g=product.fat_per_100g,
        alcohol_g=product.alcohol_per_100g,
    )


def accepts(product: OffProduct, stats: ImportStats) -> bool:
    """The same reconciliation the database enforces, run before the write.

    Done here as well as in the constraint so a rejected row is *counted* rather than
    blowing up a five-hundred-row batch and taking the good rows with it.
    """
    result = check_energy(_macros_of(product))
    if result.is_ok:
        return True
    stats.rejected_energy += 1
    if len(stats.rejected_examples) < 20:
        stats.rejected_examples.append((product.name, int(result.stated), int(result.implied)))
    return False


async def _write_batch(session: AsyncSession, products: list[OffProduct]) -> int:
    if not products:
        return 0

    food_rows = []
    barcode_rows = []
    serving_rows = []
    nutrient_rows = []

    for product in products:
        food_id = food_id_for(product.barcode)
        # The brand belongs in the name: OFF's brand field is a free-text list, and
        # "Γάλα" alone is useless in a search result next to nine other milks.
        display = f"{product.brand} {product.name}" if product.brand else product.name
        food_rows.append(
            {
                "id": food_id,
                "name": display[:200],
                "owner_user_id": None,
                "source": FoodSource.OFF.value,
                "trust_tier": int(TrustTier.COMMUNITY),
                "calories_per_100g": product.calories_per_100g,
                "protein_per_100g": product.protein_per_100g,
                "carbs_per_100g": product.carbs_per_100g,
                "fat_per_100g": product.fat_per_100g,
                "alcohol_per_100g": product.alcohol_per_100g,
                # Never verified: nobody checked these numbers by hand, and the badge
                # means a human did.
                "is_verified": False,
                "is_liquid": product.is_liquid,
            }
        )
        barcode_rows.append(
            {
                "id": uuid5(OFF_NAMESPACE, f"barcode:{product.barcode}"),
                "food_id": food_id,
                "barcode": product.barcode,
            }
        )
        if product.serving_grams:
            serving_rows.append(
                {
                    "id": uuid5(OFF_NAMESPACE, f"serving:{product.barcode}"),
                    "food_id": food_id,
                    "label": "1 serving",
                    "grams": product.serving_grams,
                    "is_default": True,
                }
            )
        for code, value in product.micronutrients.items():
            # Silently skipping an unknown code rather than failing the batch: OFF adds
            # fields over time, and one unrecognised nutrient must not cost 500 products.
            if code not in NUTRIENT_CODES:
                continue
            nutrient_rows.append(
                {
                    "food_id": food_id,
                    "nutrient_id": nutrient_id(code),
                    "amount_per_100g": Decimal(value),
                }
            )

    stmt = pg_insert(FoodModel).values(food_rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"],
            # `usage_count` stays out: it is earned by people logging the food, and a
            # re-import must not reset what the catalogue learned.
            set_={c: stmt.excluded[c] for c in food_rows[0] if c not in ("id", "owner_user_id")},
        )
    )
    await session.flush()

    barcode_stmt = pg_insert(FoodBarcodeModel).values(barcode_rows)
    await session.execute(barcode_stmt.on_conflict_do_nothing(index_elements=["barcode"]))

    if serving_rows:
        serving_stmt = pg_insert(FoodServingModel).values(serving_rows)
        await session.execute(
            serving_stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={"grams": serving_stmt.excluded.grams},
            )
        )

    if nutrient_rows:
        nutrient_stmt = pg_insert(FoodNutrientModel).values(nutrient_rows)
        await session.execute(
            nutrient_stmt.on_conflict_do_update(
                index_elements=["food_id", "nutrient_id"],
                set_={"amount_per_100g": nutrient_stmt.excluded.amount_per_100g},
            )
        )

    await session.flush()
    return len(food_rows)


async def import_country(
    session: AsyncSession,
    *,
    country: str = "greece",
    max_pages: int | None = None,
    client: OpenFoodFactsClient | None = None,
) -> ImportStats:
    stats = ImportStats()
    batch: list[OffProduct] = []

    async def flush() -> None:
        nonlocal batch
        if batch:
            stats.written += await _write_batch(session, batch)
            await session.commit()
            logger.info("off_import_progress", **stats.as_dict())
            batch = []

    owned = client is None
    off = client or OpenFoodFactsClient()
    if owned:
        await off.__aenter__()
    try:
        async for product in off.search_country(country, max_pages=max_pages):
            stats.seen += 1
            if not accepts(product, stats):
                continue
            batch.append(product)
            if len(batch) >= BATCH_SIZE:
                await flush()
        await flush()
    finally:
        if owned:
            await off.__aexit__()

    if stats.rejected_examples:
        logger.warning(
            "off_import_rejections",
            count=stats.rejected_energy,
            examples=stats.rejected_examples[:10],
        )
    return stats


async def _main(settings: Settings | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import Open Food Facts products.")
    parser.add_argument("--country", default="greece")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Stop after this many pages of 100. Omit to import everything.",
    )
    args = parser.parse_args()

    resolved = settings or get_settings()
    configure_logging()
    database = Database(resolved)
    async with database.session_factory() as session:
        stats = await import_country(session, country=args.country, max_pages=args.max_pages)
    await database.dispose()
    logger.info("off_import_finished", country=args.country, **stats.as_dict())


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
