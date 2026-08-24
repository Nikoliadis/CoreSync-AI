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
    OffPaginationError,
    OffProduct,
    _serving_grams,
    parse_product,
)
from coresync.infrastructure.seed.off_import import ImportStats, accepts


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


class TestTruncationIsVisible:
    """A partial import must never look like a complete one.

    Open Food Facts answers a bulk read with intermittent 503s — consecutive pages come
    back 200, 503, 503, 200 with no pattern. The first version of this importer stopped
    at the first exhausted page and logged `off_import_finished`, so a scheduled run
    would have reported success over a catalogue a fraction of its intended size and
    nobody would have looked.
    """

    def test_stats_start_complete(self) -> None:
        stats = ImportStats()
        assert stats.is_complete is True
        assert stats.as_dict()["truncated"] is False

    def test_a_truncated_run_says_so(self) -> None:
        stats = ImportStats(seen=528, written=518, truncated=True, stopped_at_page=6)
        assert stats.is_complete is False
        assert stats.as_dict()["truncated"] is True
        assert stats.as_dict()["stopped_at_page"] == 6

    def test_the_rejection_rate_survives_truncation(self) -> None:
        """What was fetched is still good data, and its quality is still measurable."""
        stats = ImportStats(seen=100, written=98, rejected_energy=2, truncated=True)
        assert stats.rejection_rate == pytest.approx(0.02)

    def test_the_pagination_error_carries_the_page_and_status(self) -> None:
        error = OffPaginationError(6, 503)
        assert error.page == 6
        assert error.status == 503
        assert "503" in str(error)
        assert "6" in str(error)


class TestEnergyRejection:
    def test_a_row_whose_macros_contradict_its_calories_is_counted(self) -> None:
        """Real Open Food Facts data. Hellmann's states 292 kcal; its macros imply 712."""
        stats = ImportStats()
        mayonnaise = OffProduct(
            barcode="1",
            name="Hellmann's",
            brand=None,
            calories_per_100g=Decimal("292"),
            protein_per_100g=Decimal("1"),
            carbs_per_100g=Decimal("2"),
            fat_per_100g=Decimal("78"),
            alcohol_per_100g=Decimal(0),
            is_liquid=False,
        )
        assert accepts(mayonnaise, stats) is False
        assert stats.rejected_energy == 1
        assert stats.rejected_examples[0][0] == "Hellmann's"

    def test_a_sound_row_is_accepted(self) -> None:
        stats = ImportStats()
        yoghurt = OffProduct(
            barcode="2",
            name="Γιαούρτι",
            brand=None,
            calories_per_100g=Decimal("59"),
            protein_per_100g=Decimal("10"),
            carbs_per_100g=Decimal("3.6"),
            fat_per_100g=Decimal("2"),
            alcohol_per_100g=Decimal(0),
            is_liquid=False,
        )
        assert accepts(yoghurt, stats) is True
        assert stats.rejected_energy == 0

    def test_a_spirit_is_accepted_because_alcohol_is_a_term(self) -> None:
        """The reason migration 0009 exists, checked on the import path too."""
        stats = ImportStats()
        tsipouro = OffProduct(
            barcode="3",
            name="Τσίπουρο",
            brand=None,
            calories_per_100g=Decimal("225"),
            protein_per_100g=Decimal(0),
            carbs_per_100g=Decimal(0),
            fat_per_100g=Decimal(0),
            alcohol_per_100g=Decimal("32"),
            is_liquid=True,
        )
        assert accepts(tsipouro, stats) is True

    def test_only_the_first_twenty_rejections_are_kept_as_examples(self) -> None:
        """A log line is a sample, not a dump. The count is the number that matters."""
        stats = ImportStats()
        bad = OffProduct(
            barcode="x",
            name="Wrong",
            brand=None,
            calories_per_100g=Decimal("40"),
            protein_per_100g=Decimal("80"),
            carbs_per_100g=Decimal("8"),
            fat_per_100g=Decimal("6"),
            alcohol_per_100g=Decimal(0),
            is_liquid=False,
        )
        for _ in range(30):
            accepts(bad, stats)
        assert stats.rejected_energy == 30
        assert len(stats.rejected_examples) == 20
