"""Deterministic QA for REWE ingredient matching and checkout/consumption costing.

Run from backend/: python qa_ingredient_costing.py
"""
import math

from app.shopping.optimizer import build_basket, consolidate, _convert_ingredient_quantity
from app.ingredient_aliases import ingredient_name_matches, ingredient_product_match_type, ingredient_substitution_name, ingredient_search_terms


class FakeCatalog:
    def __init__(self, products):
        self.products = products

    def search(self, ingredient):
        return self.products.get(ingredient, [])


def run():
    # The actual product title, not a broad catalog label, must confirm the ingredient.
    assert ingredient_name_matches("trofie pasta", "REWE Trofie") is True
    assert ingredient_name_matches("trofie pasta", "REWE Fusilli") is False
    assert ingredient_name_matches("trofie pasta", "REWE Udon Nudeln") is False
    assert ingredient_name_matches("rice", "REWE Beste Wahl Langkornreis 500g") is True
    assert ingredient_product_match_type("onions", "REWE Speisezwiebeln 1kg") == "exact"
    assert ingredient_product_match_type("frozen french fries", "REWE Beste Wahl Pommes Frites 750g") == "exact"
    assert ingredient_product_match_type("frozen french fries", "ja! Tiefkühlpommes 1kg") == "exact"
    assert "pommes frites" in ingredient_search_terms("frozen french fries")
    assert ingredient_name_matches("parmesan", "Parmigiano Reggiano") is True
    assert ingredient_name_matches("parmesan", "Käse-Wiener") is False
    assert ingredient_name_matches("fresh basil pesto", "Basilikum Pesto") is True
    assert ingredient_name_matches("fresh basil pesto", "Basilikum-Pesto 190g") is True
    assert ingredient_name_matches("cherry tomato", "REWE Cocktailtomaten 250g") is True
    assert ingredient_name_matches("greek yogurt", "Joghurt griechischer Art 500g") is True
    assert ingredient_product_match_type("greek yogurt", "Skyr Natur 500g") == "substitute"
    assert ingredient_name_matches("pine nuts", "Pinienkerne natur") is True
    assert ingredient_product_match_type("trofie pasta", "REWE Fusilli") == "substitute"
    assert ingredient_product_match_type("trofie pasta", "REWE Udon Nudeln") is None
    assert ingredient_product_match_type("parmesan", "Grana Padano") == "substitute"
    assert ingredient_product_match_type("pine nuts", "Sonnenblumenkerne 200g") == "substitute"
    assert ingredient_substitution_name("pine nuts", "REWE Bio Sonnenblumenkerne 200g") == "sunflower seeds"
    mayo_volume, mayo_note = _convert_ingredient_quantity(30, "g", "ml", "mayonnaise")
    assert abs(mayo_volume - (30 / 0.95)) < 0.001
    assert "Estimated density 0.95 g/ml" in mayo_note

    catalog = FakeCatalog({
        "rice": [{
            "id": 1, "name_original": "REWE Rice 500g", "package_size": 500,
            "package_unit": "g", "price": 1.50, "price_per_unit": 999.0,
            "availability": "available",
        }],
        "milk": [{
            "id": 2, "name_original": "Milk 1L", "package_size": 1,
            "package_unit": "l", "price": 1.19, "availability": "available",
        }],
        "unknown": [{
            "id": 3, "name_original": "Unknown unit product", "package_size": 1,
            "package_unit": "piece", "price": 2.0, "availability": "available",
        }],
        "unpriced": [{
            "id": 4, "name_original": "No price", "package_size": 100,
            "package_unit": "g", "price": None, "availability": "available",
        }],
        "zero-priced": [{
            "id": 8, "name_original": "Invalid zero-price product", "package_size": 100,
            "package_unit": "g", "price": 0, "availability": "available",
        }],
        "nan-priced": [{
            "id": 9, "name_original": "Invalid NaN-price product", "package_size": 100,
            "package_unit": "g", "price": float("nan"), "availability": "available",
        }],
        "infinite-priced": [{
            "id": 10, "name_original": "Invalid infinite-price product", "package_size": 100,
            "package_unit": "g", "price": float("inf"), "availability": "available",
        }],
        "invalid-pack": [{
            "id": 11, "name_original": "Invalid package-size product", "package_size": float("nan"),
            "package_unit": "g", "price": 1.99, "availability": "available",
        }],
        "pine nuts": [{
            "id": 5, "ingredient": "sunflower seeds", "ingredient_match_type": "substitute",
            "ingredient_substitute": "sunflower seeds",
            "name_original": "REWE Bio Sonnenblumenkerne 200g",
            "package_size": 200, "package_unit": "g", "price": 1.29,
            "availability": "available",
        }],
    })
    requirements = [
        {"ingredient": "rice", "quantity": 0.25, "unit": "kg", "source_meals": ["Rice bowl"]},
        {"ingredient": "milk", "quantity": 500, "unit": "ml", "source_meals": ["Pancakes"]},
        {"ingredient": "unknown", "quantity": 2, "unit": "tbsp", "source_meals": ["Sauce"]},
        {"ingredient": "unpriced", "quantity": 50, "unit": "g", "source_meals": ["Soup"]},
        {"ingredient": "zero-priced", "quantity": 50, "unit": "g", "source_meals": ["Soup"]},
        {"ingredient": "nan-priced", "quantity": 50, "unit": "g", "source_meals": ["Soup"]},
        {"ingredient": "infinite-priced", "quantity": 50, "unit": "g", "source_meals": ["Soup"]},
        {"ingredient": "invalid-pack", "quantity": 50, "unit": "g", "source_meals": ["Soup"]},
    ]
    basket = build_basket(requirements, catalog, mode="cheapest")
    rice, milk, unknown, unpriced, zero_priced, nan_priced, infinite_priced, invalid_pack = basket

    assert rice["match_status"] == "matched"
    assert rice["packs"] == 1 and rice["checkout_cost"] == 1.5
    assert rice["consumed_cost"] == 0.75
    assert rice["package_quantity"] == 500 and rice["package_unit"] == "g"
    assert rice["unit_cost"] == 0.003, "Basket unit price must be recomputed from checkout price and pack size"

    assert milk["match_status"] == "matched"
    assert milk["checkout_cost"] == 1.19 and milk["consumed_cost"] == 0.59

    assert unknown["match_status"] == "unmatched"
    assert unknown["checkout_cost"] == 0
    assert unpriced["match_status"] == "unmatched"
    assert unpriced["checkout_cost"] == 0
    assert zero_priced["match_status"] == "unmatched", "Zero-priced catalog rows are not valid purchasable products"
    assert zero_priced["checkout_cost"] == 0
    for invalid_row in (nan_priced, infinite_priced, invalid_pack):
        assert invalid_row["match_status"] == "unmatched", "Non-finite prices and invalid package sizes must never enter the basket"
        assert invalid_row["checkout_cost"] == 0

    # Exact catalog products remain preferred even if a substitute is much cheaper.
    preference_catalog = FakeCatalog({
        "rice": [
            {"id": 21, "name_original": "Exact rice pack", "package_size": 500,
             "package_unit": "g", "price": 2500.0, "availability": "available",
             "ingredient_match_type": "exact"},
            {"id": 22, "name_original": "Cheap rice substitute", "package_size": 500,
             "package_unit": "g", "price": 0.99, "availability": "available",
             "ingredient_match_type": "substitute", "ingredient_substitute": "alternative grain"},
        ],
    })
    preferred = build_basket(
        [{"ingredient": "rice", "quantity": 100, "unit": "g", "source_meals": ["Rice bowl"]}],
        preference_catalog, mode="cheapest",
    )
    assert preferred[0]["product"]["id"] == 21

    suggested_catalog = FakeCatalog({
        "rice": [
            {"id": 23, "name_original": "Exact rice pack", "package_size": 500,
             "package_unit": "g", "price": 2.50, "availability": "available",
             "ingredient_match_type": "exact"},
            {"id": 24, "name_original": "Cheap alternative grain", "package_size": 500,
             "package_unit": "g", "price": 0.50, "availability": "available",
             "ingredient_match_type": "suggested_substitution",
             "ingredient_substitute": "alternative grain"},
        ],
    })
    suggested = build_basket(
        [{"ingredient": "rice", "quantity": 100, "unit": "g", "source_meals": ["Rice bowl"]}],
        suggested_catalog, mode="cheapest",
    )
    assert suggested[0]["product"]["id"] == 23
    substitute_only = FakeCatalog({"rice": [{
        "id": 25, "name_original": "Alternative grain", "package_size": 500,
        "package_unit": "g", "price": 0.50, "availability": "available",
        "ingredient_match_type": "substitute",
        "ingredient_substitute": "alternative grain",
    }]})
    substitute_only_result = build_basket(
        [{"ingredient": "rice", "quantity": 100, "unit": "g", "source_meals": ["Rice bowl"]}],
        substitute_only, mode="cheapest",
    )
    assert substitute_only_result[0]["match_status"] == "substituted"

    confirmed_semantic_substitute = FakeCatalog({"rice": [{
        "id": 26, "name_original": "Alternative grain 500g",
        "name_normalized": "alternative grain 500g", "ingredient": "rice",
        "package_size": 500, "package_unit": "g", "price": 0.99,
        "availability": "available", "ingredient_match_type": "semantic_candidate",
        "semantic_match_type": "suggested_substitution",
    }]})
    confirmed = build_basket(
        [{"ingredient": "rice", "quantity": 100, "unit": "g", "source_meals": ["Rice bowl"]}],
        confirmed_semantic_substitute, overrides={"rice": 26},
    )
    assert confirmed[0]["match_status"] == "substituted"
    assert confirmed[0]["product"]["ingredient_substitute"] == "alternative grain 500g"

    invalid_consolidated = consolidate([{
        "id": "bad", "name": "Bad recipe",
        "ingredients": [["rice", "not-a-number", "g"], ["salt", float("inf"), "g"]],
    }], {"bad": 2})
    assert all(not math.isfinite(row["quantity"]) for row in invalid_consolidated)
    invalid_quantity = build_basket(
        [{"ingredient": "rice", "quantity": float("nan"), "unit": "g", "source_meals": ["Bad recipe"]}],
        catalog,
    )
    assert invalid_quantity[0]["match_status"] == "unmatched"
    assert "quantity is invalid" in invalid_quantity[0]["match_reason"].lower()
    invalid_pantry = build_basket(
        [{"ingredient": "rice", "quantity": 100, "unit": "g", "source_meals": ["Rice bowl"]}],
        catalog, pantry={"rice": {"quantity": float("nan"), "unit": "g"}},
    )
    assert invalid_pantry[0]["match_status"] == "matched"
    assert invalid_pantry[0]["pantry_used"] == 0

    substitute_basket = build_basket(
        [{"ingredient": "pine nuts", "quantity": 30, "unit": "g", "source_meals": ["Pesto pasta"]}],
        catalog,
    )
    assert substitute_basket[0]["match_status"] == "substituted"
    assert substitute_basket[0]["product"]["ingredient_substitute"] == "sunflower seeds"
    assert substitute_basket[0]["checkout_cost"] == 1.29

    pantry_basket = build_basket(
        [{"ingredient": "rice", "quantity": 1, "unit": "kg", "source_meals": ["Meal"]}],
        catalog, pantry={"rice": {"quantity": 250, "unit": "g"}},
    )
    pantry_rice = pantry_basket[0]
    assert pantry_rice["pantry_used"] == 0.25
    assert pantry_rice["needed_quantity"] == 0.75
    assert pantry_rice["checkout_cost"] == 3.0
    assert pantry_rice["consumed_cost"] == 2.25

    mixed_units = consolidate([
        {"id": "a", "name": "Chicken bowl", "ingredients": [["chicken breast", 200, "g"], ["milk", 100, "ml"], ["garlic", 2, "cloves"]]},
        {"id": "b", "name": "Chicken pasta", "ingredients": [["chicken breast", 0.3, "kg"], ["milk", 0.5, "l"], ["garlic", 1, "unit"]]},
    ], {"a": 2, "b": 2})
    chicken = next(row for row in mixed_units if row["ingredient"] == "chicken breast")
    milk_total = next(row for row in mixed_units if row["ingredient"] == "milk")
    garlic_rows = [row for row in mixed_units if row["ingredient"] == "garlic"]
    assert chicken["quantity"] == 500 and chicken["unit"] == "g"
    assert milk_total["quantity"] == 600 and milk_total["unit"] == "ml"
    assert len(garlic_rows) == 2, "Cloves and whole units must not be silently merged"
    from app.shopping.optimizer import _convert_ingredient_quantity
    assert _convert_ingredient_quantity(1, "clove", "g", "garlic")[0] == 3

    substitute_catalog = FakeCatalog({
        "trofie pasta": [{
            "id": 5, "name_original": "REWE Fusilli 500g", "package_size": 500,
            "package_unit": "g", "price": 1.50, "price_per_unit": 0.003,
            "availability": "available", "ingredient_match_type": "substitute",
        }],
    })
    substitute_basket = build_basket(
        [{"ingredient": "trofie pasta", "quantity": 200, "unit": "g", "source_meals": ["Pasta"]}],
        substitute_catalog, mode="cheapest",
    )
    assert substitute_basket[0]["match_status"] == "substituted"
    assert substitute_basket[0]["checkout_cost"] == 1.5


    # Whole onions are sold by weight in REWE; use an explicit average-weight estimate.
    onion_catalog = FakeCatalog({
        "onions": [{
            "id": 6, "name_original": "REWE Speisezwiebeln 1kg",
            "package_size": 1000, "package_unit": "g", "price": 1.49,
            "availability": "available", "ingredient_match_type": "exact",
        }],
    })
    onion_basket = build_basket(
        [{"ingredient": "onions", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest",
    )
    assert onion_basket[0]["match_status"] == "matched"
    assert onion_basket[0]["unit_conversion_note"] == "Estimated 150 g per piece of onion."
    assert onion_basket[0]["needed_quantity"] == 2
    assert onion_basket[0]["checkout_cost"] == 1.49

    fries_catalog = FakeCatalog({
        "frozen french fries": [{
            "id": 7, "name_original": "REWE Beste Wahl Pommes Frites 750g",
            "package_size": 750, "package_unit": "g", "price": 1.99,
            "availability": "available", "ingredient_match_type": "exact",
        }],
    })
    fries_basket = build_basket(
        [{"ingredient": "frozen french fries", "quantity": 300, "unit": "g", "source_meals": ["Chorrillana"]}],
        fries_catalog, mode="cheapest",
    )
    assert fries_basket[0]["match_status"] == "matched"
    assert fries_basket[0]["checkout_cost"] == 1.99

    # Recipe ingredient quantities are generated for 2 servings and scaled exactly once.
    one_serving = consolidate([
        {"id": "single", "name": "Single portion", "base_servings": 2,
         "ingredients": [["rice", 150, "g"]]},
    ], {"single": 1})
    assert one_serving[0]["quantity"] == 75

    four_servings = consolidate([
        {"id": "four", "name": "Four portions", "base_servings": 2,
         "ingredients": [["rice", 150, "g"]]},
    ], {"four": 4})
    assert four_servings[0]["quantity"] == 300

    print("PASS: strict title matching, culinary substitutions, portion scaling, unit conversions, pantry deductions, checkout vs consumed cost, and unmatched handling")


if __name__ == "__main__":
    run()
