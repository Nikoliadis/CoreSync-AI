"""The nutrient reference list.

Kept as data rather than an enum so adding vitamin K is one row and no migration. The
codes are the contract: importers map their own field names onto these, and the food
detail screen groups by `category` and formats by `unit`.

Units follow what a label prints, not what a database would prefer — sodium in
milligrams, vitamin D in micrograms — because the number a user sees should match the
packet in their hand without them doing arithmetic.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

NUTRIENT_NAMESPACE = uuid5(NAMESPACE_URL, "https://coresync.ai/nutrients")


def nutrient_id(code: str) -> UUID:
    return uuid5(NUTRIENT_NAMESPACE, code)


# (code, display name, unit, category)
NUTRIENTS: tuple[tuple[str, str, str, str], ...] = (
    # --- macro detail ---------------------------------------------------------
    ("fiber_g", "Fibre", "g", "macro"),
    ("sugars_g", "Sugars", "g", "macro"),
    ("saturated_fat_g", "Saturated fat", "g", "macro"),
    ("trans_fat_g", "Trans fat", "g", "macro"),
    ("mono_fat_g", "Monounsaturated fat", "g", "macro"),
    ("poly_fat_g", "Polyunsaturated fat", "g", "macro"),
    ("cholesterol_mg", "Cholesterol", "mg", "other"),
    ("salt_g", "Salt", "g", "other"),
    ("caffeine_mg", "Caffeine", "mg", "other"),
    # --- minerals -------------------------------------------------------------
    ("sodium_mg", "Sodium", "mg", "mineral"),
    ("potassium_mg", "Potassium", "mg", "mineral"),
    ("calcium_mg", "Calcium", "mg", "mineral"),
    ("iron_mg", "Iron", "mg", "mineral"),
    ("magnesium_mg", "Magnesium", "mg", "mineral"),
    ("zinc_mg", "Zinc", "mg", "mineral"),
    ("phosphorus_mg", "Phosphorus", "mg", "mineral"),
    ("selenium_mcg", "Selenium", "mcg", "mineral"),
    ("iodine_mcg", "Iodine", "mcg", "mineral"),
    # --- vitamins -------------------------------------------------------------
    ("vitamin_a_ug", "Vitamin A", "mcg", "vitamin"),
    ("vitamin_c_mg", "Vitamin C", "mg", "vitamin"),
    ("vitamin_d_ug", "Vitamin D", "mcg", "vitamin"),
    ("vitamin_e_mg", "Vitamin E", "mg", "vitamin"),
    ("vitamin_k_ug", "Vitamin K", "mcg", "vitamin"),
    ("vitamin_b6_mg", "Vitamin B6", "mg", "vitamin"),
    ("vitamin_b12_ug", "Vitamin B12", "mcg", "vitamin"),
    ("folate_ug", "Folate", "mcg", "vitamin"),
    ("thiamin_mg", "Thiamin (B1)", "mg", "vitamin"),
    ("riboflavin_mg", "Riboflavin (B2)", "mg", "vitamin"),
    ("niacin_mg", "Niacin (B3)", "mg", "vitamin"),
)

NUTRIENT_CODES = frozenset(code for code, _, _, _ in NUTRIENTS)

# The order the food detail screen groups them in. Macro detail first because it is what
# people actually look for; vitamins last because almost nothing has complete data.
CATEGORY_ORDER = ("macro", "other", "mineral", "vitamin")
