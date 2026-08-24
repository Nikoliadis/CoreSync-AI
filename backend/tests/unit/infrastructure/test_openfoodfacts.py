"""Parsing Open Food Facts products.

The payloads here are shaped like real OFF responses, including the parts that make it
awkward: free-text serving sizes, nutriments in grams that labels quote in milligrams,
missing macros, and the occasional row whose numbers are simply wrong.

Everything is offline. OFF's search endpoint was returning 503 while this was written,
which is exactly why the parser must be testable without it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from coresync.infrastructure.external.openfoodfacts import (
    _serving_grams,
    parse_product,
)


def product(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "code": "5201627019900",
        "product_name": "Greek Yoghurt",
        "brands": "ΔΕΛΤΑ",
        "categories_tags": ["en:dairies", "en:yogurts"],
        "nutriments": {
            "energy-kcal_100g": 59,
            "proteins_100g": 10,
            "carbohydrates_100g": 3.6,
            "fat_100g": 2,
        },
    }
    base.update(overrides)
    return base


class TestUsableProducts:
    def test_a_complete_product_parses(self) -> None:
        parsed = parse_product(product())
        assert parsed is not None
        assert parsed.name == "Greek Yoghurt"
        assert parsed.brand == "ΔΕΛΤΑ"
        assert parsed.calories_per_100g == Decimal("59")
        assert parsed.protein_per_100g == Decimal("10")

    def test_the_greek_name_wins_when_there_is_one(self) -> None:
        """A Greek-facing catalogue should show the Greek name, not the generic one."""
        parsed = parse_product(product(product_name_el="Γιαούρτι στραγγιστό"))
        assert parsed is not None
        assert parsed.name == "Γιαούρτι στραγγιστό"

    def test_only_the_first_brand_is_kept(self) -> None:
        """OFF's brand field is a free-text comma-separated list."""
        parsed = parse_product(product(brands="ΔΕΛΤΑ, Delta Foods, delta"))
        assert parsed is not None
        assert parsed.brand == "ΔΕΛΤΑ"

    def test_a_drink_is_detected_from_its_categories(self) -> None:
        parsed = parse_product(product(categories_tags=["en:beverages", "en:waters"]))
        assert parsed is not None
        assert parsed.is_liquid is True

    def test_a_solid_is_not_a_drink(self) -> None:
        parsed = parse_product(product())
        assert parsed is not None
        assert parsed.is_liquid is False

    def test_alcohol_is_carried_through(self) -> None:
        """Without it, every wine and beer fails the energy check downstream."""
        parsed = parse_product(
            product(
                nutriments={
                    "energy-kcal_100g": 85,
                    "proteins_100g": 0.1,
                    "carbohydrates_100g": 2.6,
                    "fat_100g": 0,
                    "alcohol_100g": 10.6,
                }
            )
        )
        assert parsed is not None
        assert parsed.alcohol_per_100g == Decimal("10.6")

    def test_a_zero_calorie_product_is_kept(self) -> None:
        """Water is a real product, and all-zero macros are correct for it."""
        parsed = parse_product(
            product(
                nutriments={
                    "energy-kcal_100g": 0,
                    "proteins_100g": 0,
                    "carbohydrates_100g": 0,
                    "fat_100g": 0,
                }
            )
        )
        assert parsed is not None
        assert parsed.calories_per_100g == Decimal(0)


class TestRejectedProducts:
    def test_no_barcode_is_rejected(self) -> None:
        assert parse_product(product(code="")) is None

    def test_no_name_is_rejected(self) -> None:
        assert parse_product(product(product_name="", product_name_el="")) is None

    def test_missing_macros_are_rejected(self) -> None:
        """A row that cannot be logged is worse in search than one that is absent."""
        assert (
            parse_product(product(nutriments={"energy-kcal_100g": 100, "proteins_100g": 5})) is None
        )

    def test_no_nutriments_at_all_is_rejected(self) -> None:
        assert parse_product(product(nutriments={})) is None

    def test_a_macro_over_100g_per_100g_is_rejected(self) -> None:
        """Physically impossible, so the row is corrupt rather than unusual."""
        assert (
            parse_product(
                product(
                    nutriments={
                        "energy-kcal_100g": 400,
                        "proteins_100g": 310,
                        "carbohydrates_100g": 5,
                        "fat_100g": 5,
                    }
                )
            )
            is None
        )

    def test_negative_values_are_rejected(self) -> None:
        assert (
            parse_product(
                product(
                    nutriments={
                        "energy-kcal_100g": 100,
                        "proteins_100g": -5,
                        "carbohydrates_100g": 5,
                        "fat_100g": 5,
                    }
                )
            )
            is None
        )

    def test_a_non_numeric_macro_is_rejected(self) -> None:
        assert (
            parse_product(
                product(
                    nutriments={
                        "energy-kcal_100g": "unknown",
                        "proteins_100g": 5,
                        "carbohydrates_100g": 5,
                        "fat_100g": 5,
                    }
                )
            )
            is None
        )


class TestMicronutrients:
    def test_grams_are_converted_to_the_units_a_label_prints(self) -> None:
        """OFF stores sodium per 100 g in grams; every packet quotes milligrams."""
        parsed = parse_product(
            product(
                nutriments={
                    "energy-kcal_100g": 59,
                    "proteins_100g": 10,
                    "carbohydrates_100g": 3.6,
                    "fat_100g": 2,
                    "sodium_100g": 0.4,
                }
            )
        )
        assert parsed is not None
        assert parsed.micronutrients["sodium_mg"] == "400"

    def test_gram_units_pass_through_unchanged(self) -> None:
        parsed = parse_product(
            product(
                nutriments={
                    "energy-kcal_100g": 59,
                    "proteins_100g": 10,
                    "carbohydrates_100g": 3.6,
                    "fat_100g": 2,
                    "fiber_100g": 2.5,
                }
            )
        )
        assert parsed is not None
        assert parsed.micronutrients["fiber_g"] == "2.5"

    def test_unknown_nutriments_are_ignored(self) -> None:
        parsed = parse_product(
            product(
                nutriments={
                    "energy-kcal_100g": 59,
                    "proteins_100g": 10,
                    "carbohydrates_100g": 3.6,
                    "fat_100g": 2,
                    "some-future-field_100g": 1,
                }
            )
        )
        assert parsed is not None
        assert "some-future-field_100g" not in parsed.micronutrients


class TestServingSize:
    """OFF's serving_size is free text, so a wrong guess is worse than no serving."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("30 g", Decimal("30")),
            ("30g", Decimal("30")),
            ("250 ml", Decimal("250")),
            ("30 g (1 slice)", Decimal("30")),
            ("1,5 g", Decimal("1.5")),
        ],
    )
    def test_recognised_forms(self, raw: str, expected: Decimal) -> None:
        assert _serving_grams(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "1 slice",
            "a handful",
            "30 oz",
            "0 g",
            "99999 g",
        ],
    )
    def test_unrecognised_forms_are_dropped(self, raw: str | None) -> None:
        assert _serving_grams(raw) is None
