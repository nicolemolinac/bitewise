"""Deterministic QA for REWE ingredient matching and checkout/consumption costing.

Run from backend/: python qa_ingredient_costing.py
"""
from app.shopping.optimizer import _convert_quantity, build_basket, consolidate


class FakeCatalog:
    def __init__(self, products):
        self.products = products

    def search(self, ingredient):
        return self.products.get(ingredient, [])


def run():
    catalog = FakeCatalog({
        "rice": [{
            "id": 1, "name_original": "REWE Rice 500g", "package_size": 500,
            "package_unit": "g", "price": 1.50, "price_per_unit": 0.003,
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
        "tiny-pack": [{
            "id": 5, "name_original": "Implausibly tiny package", "package_size": 0.001,
            "package_unit": "g", "price": 0.50, "availability": "available",
        }],
    })
    requirements = [
        {"ingredient": "rice", "quantity": 0.25, "unit": "kg", "source_meals": ["Rice bowl"]},
        {"ingredient": "milk", "quantity": 500, "unit": "ml", "source_meals": ["Pancakes"]},
        {"ingredient": "unknown", "quantity": 2, "unit": "tbsp", "source_meals": ["Sauce"]},
        {"ingredient": "unpriced", "quantity": 50, "unit": "g", "source_meals": ["Soup"]},
        {"ingredient": "tiny-pack", "quantity": 1, "unit": "g", "source_meals": ["Spice"]},
    ]
    basket = build_basket(requirements, catalog, mode="cheapest")
    rice, milk, unknown, unpriced, tiny_pack = basket

    assert rice["match_status"] == "matched"
    assert rice["packs"] == 1 and rice["checkout_cost"] == 1.5
    assert rice["consumed_cost"] == 0.75
    assert rice["package_quantity"] == 500 and rice["package_unit"] == "g"

    assert milk["match_status"] == "matched"
    assert milk["checkout_cost"] == 1.19 and milk["consumed_cost"] == 0.59

    assert unknown["match_status"] == "unmatched"
    assert unknown["checkout_cost"] == 0
    assert unpriced["match_status"] == "unmatched"
    assert unpriced["checkout_cost"] == 0
    assert tiny_pack["match_status"] == "unmatched", "Do not recommend more than 99 packs"
    assert tiny_pack["checkout_cost"] == 0

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
        {"id": "c", "name": "Garlic toast", "ingredients": [["garlic", 1, "clove"]]},
    ], {"a": 2, "b": 2, "c": 2})
    chicken = next(row for row in mixed_units if row["ingredient"] == "chicken breast")
    milk_total = next(row for row in mixed_units if row["ingredient"] == "milk")
    garlic_rows = [row for row in mixed_units if row["ingredient"] == "garlic"]
    assert chicken["quantity"] == 500 and chicken["unit"] == "g"
    assert milk_total["quantity"] == 600 and milk_total["unit"] == "ml"
    assert len(garlic_rows) == 2, "Cloves and whole units must not be silently merged"
    garlic_cloves = next(row for row in garlic_rows if row["unit"] == "clove")
    garlic_pieces = next(row for row in garlic_rows if row["unit"] == "piece")
    assert garlic_cloves["quantity"] == 3, "Clove and cloves must consolidate"
    assert garlic_pieces["quantity"] == 1, "Whole garlic units must remain separate"

    assert _convert_quantity(float("nan"), "g", "g") is None
    assert _convert_quantity(float("inf"), "g", "kg") is None
    assert _convert_quantity(100, "g", "ml") is None

    canonical_rows = consolidate([
        {"id": "x", "name": "Tomato salad", "ingredients": [["tomato", 1, "piece"], ["tomatoes", 2, "piece"], ["cherry tomatoes", 3, "piece"]]},
    ], {"x": 2})
    regular_tomato = next(row for row in canonical_rows if row["ingredient"] == "tomato")
    cherry_tomato = next(row for row in canonical_rows if row["ingredient"] == "cherry tomato")
    assert regular_tomato["quantity"] == 3
    assert cherry_tomato["quantity"] == 3, "Specific tomato types must remain separate"

    synonym_pantry = build_basket(
        [{"ingredient": "tomato", "quantity": 3, "unit": "piece", "source_meals": ["Salad"]}],
        FakeCatalog({"tomato": []}),
        pantry={
            "tomatoes": {"quantity": 2, "unit": "piece"},
            "Tomate": {"quantity": 1, "unit": "piece"},
        },
    )[0]
    assert synonym_pantry["match_status"] == "covered"
    assert synonym_pantry["pantry_used"] == 3

    print("PASS: conversions, canonical ingredient merging, synonym pantry deductions, finite-value guards, checkout and consumption costing, pack limits, and unmatched handling")


if __name__ == "__main__":
    run()
