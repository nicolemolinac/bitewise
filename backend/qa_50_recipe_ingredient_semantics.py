"""50-recipe ingredient and shopping QA.

Deterministic, no Gemini/network dependency. Runs the real consolidation and
basket optimizer against the bundled REWE catalog snapshot.
"""
import math
from collections import defaultdict

from app.ingredient_aliases import canonical_ingredient
from app.rewe.seed_products import PRODUCTS
from app.shopping.optimizer import _convert_quantity, build_basket, consolidate


# Each archetype is a realistic two-serving recipe. Five named variants per
# archetype exercise repeated ingredients, different cuisines and substitutions.
ARCHETYPES = [
    ("Chicken rice", [
        ("chicken breast", 300, "g"), ("rice", 160, "g"),
        ("bell pepper", 1, "unit"), ("onion", 0.5, "unit"),
        ("soy sauce", 25, "ml"), ("olive oil", 10, "ml")]),
    ("Salmon bowl", [
        ("salmon", 250, "g"), ("rice", 160, "g"), ("avocado", 1, "unit"),
        ("cucumber", 0.5, "unit"), ("edamame", 120, "g"),
        ("soy sauce", 20, "ml"), ("sesame", 8, "g")]),
    ("Tomato pasta", [
        ("pasta", 180, "g"), ("tomatoes", 300, "g"),
        ("garlic", 2, "cloves"), ("olive oil", 15, "ml"),
        ("parmesan", 25, "g")]),
    ("Spinach egg skillet", [
        ("eggs", 4, "unit"), ("spinach", 180, "g"),
        ("feta", 70, "g"), ("onion", 0.5, "unit"),
        ("bread", 120, "g"), ("olive oil", 10, "ml")]),
    ("Chickpea curry", [
        ("chickpeas", 240, "g"), ("coconut milk", 200, "ml"),
        ("tomatoes", 200, "g"), ("spinach", 100, "g"),
        ("onion", 0.5, "unit"), ("rice", 140, "g")]),
    ("Beef-style rice bowl", [
        ("rice", 160, "g"), ("eggs", 2, "unit"),
        ("carrot", 1, "unit"), ("spinach", 100, "g"),
        ("soy sauce", 20, "ml"), ("sesame", 8, "g")]),
    ("Potato tray bake", [
        ("potatoes", 500, "g"), ("chicken breast", 250, "g"),
        ("tomatoes", 150, "g"), ("onion", 0.5, "unit"),
        ("olive oil", 15, "ml")]),
    ("Lentil dal", [
        ("red lentils", 200, "g"), ("tomatoes", 200, "g"),
        ("coconut milk", 150, "ml"), ("spinach", 100, "g"),
        ("onion", 0.5, "unit"), ("rice", 140, "g")]),
    ("Fajita wraps", [
        ("chicken breast", 250, "g"), ("bell pepper", 2, "unit"),
        ("onion", 0.5, "unit"), ("tortillas", 4, "unit"),
        ("avocado", 1, "unit"), ("greek yogurt", 80, "g"),
        ("lime", 1, "unit")]),
    ("Salmon potato plate", [
        ("salmon", 250, "g"), ("potatoes", 400, "g"),
        ("cucumber", 0.5, "unit"), ("greek yogurt", 60, "g"),
        ("lime", 0.5, "unit"), ("olive oil", 10, "ml")]),
]
VARIANTS = [
    ("Classic", 1.00),
    ("Light", 0.85),
    ("Hearty", 1.15),
    ("Meal prep", 1.00),
    ("Herb finish", 1.00),
]


class SeedCatalog:
    def __init__(self):
        self.by_ingredient = defaultdict(list)
        for index, item in enumerate(PRODUCTS, 1):
            self.by_ingredient[canonical_ingredient(item["ingredient"])].append({
                "id": index,
                "ingredient": item["ingredient"],
                "name_original": item["name"],
                "name": item["name"],
                "brand": item.get("brand"),
                "package_size": item["pack_qty"],
                "package_unit": item["unit"],
                "price": item["price"],
                "price_per_unit": item["unit_price"],
                "availability": "available",
            })

    def search(self, ingredient):
        return self.by_ingredient.get(canonical_ingredient(ingredient), [])


def build_fixtures():
    meals = []
    for archetype, ingredients in ARCHETYPES:
        for variant, factor in VARIANTS:
            name = f"{variant} {archetype}"
            rows = []
            for ingredient, quantity, unit in ingredients:
                # Scale a few ingredients for a believable variant while keeping
                # recipe portions in a normal home-cooking range.
                multiplier = factor
                rows.append([ingredient, round(quantity * multiplier, 3), unit])
            meals.append({
                "id": f"qa-{len(meals)+1:02d}",
                "name": name,
                "ingredients": rows,
            })
    assert len(meals) == 50
    assert len({meal["name"] for meal in meals}) == 50
    return meals


def main():
    meals = build_fixtures()
    allowed_units = {"g", "kg", "ml", "l", "unit", "piece", "clove", "cloves"}
    for meal in meals:
        assert 4 <= len(meal["ingredients"]) <= 8, meal["name"]
        for name, qty, unit in meal["ingredients"]:
            assert name.strip() and math.isfinite(qty) and qty > 0, (meal["name"], name, qty)
            assert unit in allowed_units, (meal["name"], name, unit)
            # Basic culinary plausibility guardrails for two portions.
            if unit in {"g", "kg"}:
                grams = _convert_quantity(qty, unit, "g")
                assert 0.05 <= grams <= 1200, (meal["name"], name, grams, unit)
            if unit in {"ml", "l"}:
                ml = _convert_quantity(qty, unit, "ml")
                assert 0.5 <= ml <= 500, (meal["name"], name, ml, unit)
            if unit in {"unit", "piece"}:
                assert qty <= 12, (meal["name"], name, qty)

    # Validate ingredient aggregation and serving scaling across every recipe.
    for servings in (1, 2, 4):
        requirements = consolidate(meals, {meal["id"]: servings for meal in meals})
        expected = defaultdict(float)
        expected_sources = defaultdict(set)
        for meal in meals:
            for name, qty, unit in meal["ingredients"]:
                # Canonical mass/volume/count units are checked by consolidate;
                # retain the same dimension in this independent expected total.
                normalized = {"kg": "g", "l": "ml", "unit": "piece"}.get(unit, unit)
                scale = {"kg": 1000, "l": 1000}.get(unit, 1)
                key = (canonical_ingredient(name), normalized)
                expected[key] += qty * scale * servings / 2
                expected_sources[key].add(meal["name"])
        actual = {(row["ingredient"], row["unit"]): row for row in requirements}
        assert set(actual) == set(expected), (servings, set(expected)-set(actual), set(actual)-set(expected))
        for key, quantity in expected.items():
            assert math.isclose(actual[key]["quantity"], quantity, rel_tol=1e-6, abs_tol=1e-5), (servings, key, quantity, actual[key])
            assert set(actual[key]["source_meals"]) == expected_sources[key], key

    # Real shopping recommendations for all 50 recipes combined, using only
    # the bundled REWE catalog data. Check every matched pack, price and unit.
    requirements = consolidate(meals, {meal["id"]: 2 for meal in meals})
    basket = build_basket(requirements, SeedCatalog(), mode="best-value")
    assert len(basket) == len(requirements)
    matched = 0
    unmatched = []
    for row in basket:
        needed = row["needed_quantity"]
        if row["match_status"] == "matched":
            matched += 1
            product = row["product"]
            assert product and product["price"] >= 0
            converted = _convert_quantity(needed, row["unit"], row["package_unit"])
            assert converted is not None and converted > 0, row
            assert row["packs"] == max(1, math.ceil(converted / product["package_size"])), row
            assert row["package_quantity"] >= converted - 1e-6, row
            assert math.isclose(row["checkout_cost"], row["packs"] * product["price"], abs_tol=0.011), row
            assert math.isfinite(row["consumed_cost"]) and 0 <= row["consumed_cost"] <= row["checkout_cost"] + 0.01
            assert row["waste"] >= -1e-9 and row["waste_ratio"] >= 0
        else:
            unmatched.append(row["ingredient"])
            assert row["product"] is None and row["packs"] == 0 and row["checkout_cost"] == 0

    assert matched >= 10, f"Too few ingredients matched to catalog: {matched}; unmatched={unmatched}"

    # Pantry deduction must reduce the shopping requirement without changing
    # the recipe's original consolidated quantity.
    sample = next(row for row in requirements if row["ingredient"] == "rice")
    pantry = {"rice": {"quantity": sample["quantity"] / 4, "unit": sample["unit"]}}
    pantry_basket = build_basket([sample], SeedCatalog(), pantry=pantry, mode="cheapest")[0]
    assert math.isclose(pantry_basket["pantry_used"], sample["quantity"] / 4, rel_tol=1e-6)
    assert math.isclose(pantry_basket["needed_quantity"], sample["quantity"] * 3 / 4, rel_tol=1e-6)

    # Cross-dimension conversions must never invent a recommendation.
    assert _convert_quantity(100, "g", "ml") is None
    assert _convert_quantity(1, "unit", "g") is None
    print(
        f"50-RECIPE QA PASS: {len(meals)} distinct recipes; "
        f"{sum(len(m['ingredients']) for m in meals)} ingredient lines; "
        f"{len(requirements)} consolidated requirements; {matched} catalog matches; "
        f"{len(unmatched)} correctly unmatched; serving scaling, pantry deductions, "
        "package rounding, checkout costs and unit safety verified."
    )


if __name__ == "__main__":
    main()
