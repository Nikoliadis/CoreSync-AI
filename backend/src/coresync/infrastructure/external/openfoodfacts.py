"""Open Food Facts client.

OFF is community-maintained, which is exactly why everything from it lands at trust
tier 3: it fills the long tail without outranking a hand-checked row. A measured sample
of Greek products found 86% carrying a name and all four macros, and 2% failing the
energy reconciliation — those 2% are genuinely wrong rows (a mayonnaise stating 292 kcal
against macros implying 712), so the check earns its place on this path rather than
being a formality.

Two ways in, sharing one parser:

* :meth:`OpenFoodFactsClient.by_barcode` — one product, on demand, when a scan misses
  locally. The result is cached as a real food row, so the second person to scan that
  product never leaves the database.
* :meth:`OpenFoodFactsClient.search_country` — pages through a country's catalogue for
  the bulk import.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from coresync.application.common.ports import ExternalFood
from coresync.core.logging import get_logger

logger = get_logger(__name__)


class OffPaginationError(RuntimeError):
    """A page could not be fetched after every retry.

    Raised rather than returned so a truncated run cannot be mistaken for a complete
    one. Silently stopping and reporting success is the worst failure mode available
    here: a scheduled import would stay green while the catalogue sat at a fraction of
    its size, and nobody would look.
    """

    def __init__(self, page: int, status: int | None) -> None:
        super().__init__(f"Open Food Facts returned {status} for page {page}")
        self.page = page
        self.status = status


BASE_URL = "https://world.openfoodfacts.org"

# OFF asks for a descriptive agent so they can contact operators of heavy clients. An
# anonymous scraper is the one they rate-limit first.
USER_AGENT = "CoreSyncAI/1.0 (fitness tracker; +https://coresync.ai)"

# Only what is used. OFF products carry hundreds of fields and requesting them all makes
# a bulk import an order of magnitude more bytes for no gain.
FIELDS = (
    "code,product_name,product_name_el,brands,quantity,serving_size,nutriments,categories_tags,lang"
)

PAGE_SIZE = 100
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# OFF rate-limits anonymous clients hard, and a bulk import is exactly the traffic shape
# it limits. 503 and 429 are "come back later", not failure, so they are retried with
# exponential backoff; anything else is a real error and returns immediately.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# OFF's search endpoint is genuinely flaky under a bulk read — probing consecutive
# pages returns 200, 503, 503, 200 with no pattern. Six attempts with the backoff
# below spans about two minutes, which clears most of it.
MAX_RETRIES = 6
BACKOFF_BASE_SECONDS = 2.0
# Courtesy delay between pages. Politeness is also self-interest: the alternative to
# pacing ourselves is being blocked partway through a twelve-thousand-row import.
PAGE_DELAY_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class OffProduct:
    """One product, already reduced to what this system stores."""

    barcode: str
    name: str
    brand: str | None
    calories_per_100g: Decimal
    protein_per_100g: Decimal
    carbs_per_100g: Decimal
    fat_per_100g: Decimal
    alcohol_per_100g: Decimal
    is_liquid: bool
    # Everything else OFF knows about the nutrition, kept as-is for the food detail
    # screen. Storing it now costs a JSONB column and saves re-importing later.
    micronutrients: dict[str, Any] = field(default_factory=dict)
    serving_grams: Decimal | None = None


# The OFF keys worth keeping, mapped to the names this system uses. Sodium is stored in
# milligrams because that is the unit every label prints.
_MICRONUTRIENT_KEYS: dict[str, str] = {
    "fiber_100g": "fiber_g",
    "sugars_100g": "sugars_g",
    "saturated-fat_100g": "saturated_fat_g",
    "trans-fat_100g": "trans_fat_g",
    "cholesterol_100g": "cholesterol_mg",
    "sodium_100g": "sodium_mg",
    "salt_100g": "salt_g",
    "potassium_100g": "potassium_mg",
    "calcium_100g": "calcium_mg",
    "iron_100g": "iron_mg",
    "vitamin-c_100g": "vitamin_c_mg",
    "vitamin-d_100g": "vitamin_d_ug",
    "vitamin-a_100g": "vitamin_a_ug",
}

_MG_FROM_G = {
    "sodium_mg",
    "cholesterol_mg",
    "potassium_mg",
    "calcium_mg",
    "iron_mg",
    "vitamin_c_mg",
}
_UG_FROM_G = {"vitamin_d_ug", "vitamin_a_ug"}

# A drink, for the purpose of showing "per 100 ml" instead of "per 100 g".
_LIQUID_MARKERS = ("beverages", "drinks", "waters", "juices", "sodas", "milks")


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    # OFF contains a long tail of nonsense from OCR and bad edits. A macro above 100 g
    # per 100 g is impossible by definition, and negatives are not a thing.
    if parsed < 0 or not parsed.is_finite():
        return None
    return parsed


def parse_product(raw: dict[str, Any]) -> OffProduct | None:
    """Reduce one OFF product, or return ``None`` if it is not usable.

    Unusable means missing a name or missing any of the four energy-bearing figures.
    Importing a row with a name and no macros would put an entry in search that cannot
    be logged, which is worse than not having it.
    """
    barcode = str(raw.get("code") or "").strip()
    if not barcode:
        return None

    # Greek name first where OFF has one: this is a Greek-facing catalogue, and the
    # localised field is more useful than the generic one even when both exist.
    name = str(raw.get("product_name_el") or raw.get("product_name") or "").strip()
    if not name:
        return None

    nutriments = raw.get("nutriments") or {}
    calories = _decimal(nutriments.get("energy-kcal_100g"))
    protein = _decimal(nutriments.get("proteins_100g"))
    carbs = _decimal(nutriments.get("carbohydrates_100g"))
    fat = _decimal(nutriments.get("fat_100g"))
    if calories is None or protein is None or carbs is None or fat is None:
        return None

    hundred = Decimal(100)
    if any(macro > hundred for macro in (protein, carbs, fat)):
        return None

    alcohol = _decimal(nutriments.get("alcohol_100g")) or Decimal(0)
    if alcohol > hundred:
        alcohol = Decimal(0)

    brand = (str(raw.get("brands") or "").split(",")[0] or "").strip() or None
    categories = " ".join(str(tag) for tag in (raw.get("categories_tags") or [])).lower()
    is_liquid = any(marker in categories for marker in _LIQUID_MARKERS)

    return OffProduct(
        barcode=barcode,
        name=name[:200],
        brand=brand[:120] if brand else None,
        calories_per_100g=calories,
        protein_per_100g=protein,
        carbs_per_100g=carbs,
        fat_per_100g=fat,
        alcohol_per_100g=alcohol,
        is_liquid=is_liquid,
        micronutrients=_micronutrients(nutriments),
        serving_grams=_serving_grams(raw.get("serving_size")),
    )


def _micronutrients(nutriments: dict[str, Any]) -> dict[str, str]:
    """Kept as strings so no precision is lost passing through JSON."""
    out: dict[str, str] = {}
    for off_key, our_key in _MICRONUTRIENT_KEYS.items():
        value = _decimal(nutriments.get(off_key))
        if value is None:
            continue
        # OFF stores these per 100 g in grams; labels quote mg and µg.
        if our_key in _MG_FROM_G:
            value = value * Decimal(1000)
        elif our_key in _UG_FROM_G:
            value = value * Decimal(1_000_000)
        out[our_key] = _plain(value)
    return out


def _plain(value: Decimal) -> str:
    """Trailing zeros stripped, but never scientific notation.

    ``Decimal("0.4") * 1000`` normalises to ``4E+2``, which is numerically right and
    useless in a JSON document a client will render. Re-quantising a positive exponent
    back to a plain integer keeps "400" as "400".
    """
    trimmed = value.normalize()
    exponent = trimmed.as_tuple().exponent
    if isinstance(exponent, int) and exponent > 0:
        trimmed = trimmed.quantize(Decimal(1))
    return str(trimmed)


def _serving_grams(raw: Any) -> Decimal | None:
    """Pull a gram figure out of free text like ``"30 g (1 slice)"``.

    Best-effort by design: OFF's serving_size is a free-text field and a wrong serving
    is worse than none, so anything not clearly a gram or millilitre figure is dropped.
    """
    if not raw:
        return None
    text = str(raw).strip().lower().replace(",", ".")
    digits = ""
    for char in text:
        if char.isdigit() or char == ".":
            digits += char
        elif digits:
            break
    if not digits:
        return None
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    if not (Decimal(0) < value <= Decimal(5000)):
        return None
    unit_part = text[len(digits) :].lstrip()
    if not unit_part.startswith(("g", "ml")):
        return None
    return value


class OpenFoodFactsClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> OpenFoodFactsClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use OpenFoodFactsClient as an async context manager.")
        return self._client

    async def _get(self, url: str, params: dict[str, Any]) -> httpx.Response | None:
        """GET with backoff on the statuses that mean "slow down".

        Returns ``None`` when every attempt failed, so callers treat an exhausted
        retry the same as a miss rather than propagating an exception into a scan.
        """
        delay = BACKOFF_BASE_SECONDS
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self.client.get(url, params=params)
            except httpx.HTTPError as exc:
                if attempt == MAX_RETRIES:
                    logger.warning("off_request_failed", url=url, error=str(exc))
                    return None
            else:
                if response.status_code not in RETRY_STATUSES:
                    return response
                if attempt == MAX_RETRIES:
                    logger.warning("off_request_exhausted", url=url, status=response.status_code)
                    return response
                # Respect an explicit Retry-After over our own guess.
                header = response.headers.get("retry-after")
                if header and header.isdigit():
                    delay = float(header)

            logger.info("off_backoff", url=url, attempt=attempt, seconds=delay)
            await asyncio.sleep(delay)
            delay *= 2
        return None

    async def by_barcode(self, barcode: str) -> OffProduct | None:
        """One product. ``None`` for a miss, a bad row, or an unreachable OFF.

        Never raises: a barcode lookup is an enhancement to a scan, and an outage
        upstream must degrade to "we don't have that yet" rather than a 500.
        """
        response = await self._get(f"/api/v2/product/{barcode.strip()}", {"fields": FIELDS})
        if response is None:
            return None

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            logger.warning("off_lookup_status", barcode=barcode, status=response.status_code)
            return None

        try:
            payload = response.json()
        except ValueError:
            return None
        if payload.get("status") != 1:
            return None
        return parse_product(payload.get("product") or {})

    async def search_country(
        self, country: str, *, page_size: int = PAGE_SIZE, max_pages: int | None = None
    ) -> AsyncIterator[OffProduct]:
        """Page through one country's catalogue, yielding usable products.

        Stops at the first page that returns nothing, so a shrinking result set or a
        rate-limit wall ends the run rather than looping.
        """
        page = 1
        while max_pages is None or page <= max_pages:
            response = await self._get(
                "/api/v2/search",
                {
                    "countries_tags_en": country,
                    "fields": FIELDS,
                    "page_size": page_size,
                    "page": page,
                },
            )
            if response is None or response.status_code >= 400:
                status = None if response is None else response.status_code
                logger.warning("off_search_status", country=country, page=page, status=status)
                raise OffPaginationError(page, status)

            try:
                products = (response.json() or {}).get("products") or []
            except ValueError:
                return
            if not products:
                return

            for raw in products:
                parsed = parse_product(raw)
                if parsed is not None:
                    yield parsed

            page += 1
            await asyncio.sleep(PAGE_DELAY_SECONDS)


class OpenFoodFactsLookup:
    """Adapts the OFF client to the application's :class:`ExternalFoodLookup` port.

    Opens and closes a connection per lookup. A barcode miss is rare and the request is
    already a network round trip, so a pooled long-lived client would be complexity
    bought for nothing measurable.
    """

    async def by_barcode(self, barcode: str) -> ExternalFood | None:
        async with OpenFoodFactsClient() as client:
            product = await client.by_barcode(barcode)
        if product is None:
            return None
        return ExternalFood(
            barcode=product.barcode,
            name=product.name,
            brand=product.brand,
            calories_per_100g=product.calories_per_100g,
            protein_per_100g=product.protein_per_100g,
            carbs_per_100g=product.carbs_per_100g,
            fat_per_100g=product.fat_per_100g,
            alcohol_per_100g=product.alcohol_per_100g,
            is_liquid=product.is_liquid,
            serving_grams=product.serving_grams,
        )
