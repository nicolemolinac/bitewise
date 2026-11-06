"""Deterministic QA for REWE ingredient matching and checkout/consumption costing.

Run from backend/: python qa_ingredient_costing.py
"""
from app.shopping.optimizer import build_basket, consolidate
from app.ingredient_aliases import ingredient_name_matches


class FakeCatalog:
    def __init__(self, products):
        self.products = products

    def search(self, ingredient):
        return self.products.get(ingredient, [])


def run():
    # Product titles, not broad catalog labels, must confirm culinary compatibility.
    assert ingredient_name_matches("trofie pasta", "REWE Fusilli 500g")
    assert not ingredient_name_matches("trofie pasta", "REWE Beste Wahl Udon-Nudeln vorgekocht 200g")
    assert ingredient_name_matches("parmesan cheese", "Parmigiano Reggiano gerieben")
    assert ingredient_name_matches("parmesan cheese", "Grana Padano")
    assert not ingredient_name_matches("parmesan cheese", "Delikat Käse-Wiener 4x50g")
    assert ingredient_name_matches("fresh basil pesto", "REWE Bio Basilikum Pesto 130g")
    assert ingredient_name_matches("pine nuts", "REWE Pinienkerne 50g")
    assert ingredient_name_matches("salt", "REWE Jodsalz")

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
    })
    requirements = [
        {"ingredient": "rice", "quantity": 0.25, "unit": "kg", "source_meals": ["Rice bowl"]},
        {"ingredient": "milk", "quantity": 500, "unit": "ml", "source_meals": ["Pancakes"]},
        {"ingredient": "unknown", "quantity": 2, "unit": "tbsp", "source_meals": ["Sauce"]},
        {"ingredient": "unpriced", "quantity": 50, "unit": "g", "source_meals": ["Soup"]},
    ]
    basket = build_basket(requirements, catalog, mode="cheapest")
    rice, milk, unknown, unpriced = basket

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

    one_portion = consolidate(
        [{"id": "single", "name": "Pesto pasta", "ingredients": [["trofie pasta", 200, "g"]]}],
        {"single": 1},
    )
    two_portions = consolidate(
        [{"id": "double", "name": "Pesto pasta", "ingredients": [["trofie pasta", 200, "g"]]}],
        {"double": 2},
    )
    four_portions = consolidate(
        [{"id": "family", "name": "Pesto pasta", "ingredients": [["trofie pasta", 200, "g"]]}],
        {"family": 4},
    )
    assert one_portion[0]["quantity"] == 100
    assert two_portions[0]["quantity"] == 200
    assert four_portions[0]["quantity"] == 400
    chicken = next(row for row in mixed_units if row["ingredient"] == "chicken breast")
    milk_total = next(row for row in mixed_units if row["ingredient"] == "milk")
    garlic_rows = [row for row in mixed_units if row["ingredient"] == "garlic"]
    assert chicken["quantity"] == 500 and chicken["unit"] == "g"
    assert milk_total["quantity"] == 600 and milk_total["unit"] == "ml"
    assert len(garlic_rows) == 2, "Cloves and whole units must not be silently merged"

    print("PASS: strict REWE title compatibility, portion scaling, unit conversions, pantry deductions, checkout/consumed cost, and unmatched handling")


if __name__ == "__main__":
    run()
