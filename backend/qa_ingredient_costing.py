"""Deterministic QA for REWE ingredient matching and checkout/consumption costing.

Run from backend/: python qa_ingredient_costing.py
"""
from app.shopping.optimizer import _convert_ingredient_quantity, _convert_quantity, build_basket, consolidate
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

    # Fractional count requirements must measure waste against the actual
    # amount needed; max(needed, 1) understated half-onion leftovers.
    half_onion_catalog = FakeCatalog({
        "onion": [{
            "id": 24, "name_original": "REWE Zwiebel 1 Stück", "package_size": 1,
            "package_unit": "piece", "price": 1.0, "availability": "available",
        }],
    })
    half_onion = build_basket(
        [{"ingredient": "onion", "quantity": 0.5, "unit": "piece", "source_meals": ["QA"]}],
        half_onion_catalog, mode="best-value",
    )[0]
    assert half_onion["waste"] == 0.5
    assert half_onion["waste_ratio"] == 1.0

    malformed_catalog = FakeCatalog({
        "negative price": [{
            "id": 20, "name_original": "Invalid negative price", "package_size": 100,
            "package_unit": "g", "price": -1.0, "availability": "available",
        }],
        "nan price": [{
            "id": 21, "name_original": "Invalid NaN price", "package_size": 100,
            "package_unit": "g", "price": float("nan"), "availability": "available",
        }],
        "zero price": [{
            "id": 24, "name_original": "Invalid zero price", "package_size": 100,
            "package_unit": "g", "price": 0.0, "availability": "available",
        }],
        "zero pack": [{
            "id": 22, "name_original": "Invalid zero pack", "package_size": 0,
            "package_unit": "g", "price": 1.0, "availability": "available",
        }],
        "nan pack": [{
            "id": 23, "name_original": "Invalid NaN pack", "package_size": float("nan"),
            "package_unit": "g", "price": 1.0, "availability": "available",
        }],
    })
    malformed_rows = build_basket([
        {"ingredient": name, "quantity": 10, "unit": "g", "source_meals": ["QA"]}
        for name in ("negative price", "nan price", "zero price", "zero pack", "nan pack")
    ], malformed_catalog)
    assert all(row["match_status"] == "unmatched" and row["packs"] == 0 for row in malformed_rows)

    substitute_basket = build_basket(
        [{"ingredient": "pine nuts", "quantity": 30, "unit": "g", "source_meals": ["Pesto pasta"]}],
        catalog,
    )
    assert substitute_basket[0]["match_status"] == "substituted"

    # An invalid explicit AI ratio must not degrade to a 1:1 substitution.
    malformed_ratio_catalog = FakeCatalog({
        "custom cooking fat": [{
            "id": 6, "name_original": "REWE Rapsöl 500ml", "package_size": 500,
            "package_unit": "ml", "price": 1.50, "price_per_unit": 0.003,
            "availability": "available", "ingredient_match_type": "substitute",
            "ingredient_substitute": "rapeseed oil",
        }],
    })
    malformed_ratio_basket = build_basket(
        [{
            "ingredient": "custom cooking fat", "quantity": 20, "unit": "ml",
            "source_meals": ["Test"],
            "ingredient_intelligence": {
                "canonical": "custom cooking fat",
                "substitution_options": [{
                    "name": "rapeseed oil", "quantity_ratio": 0,
                }],
            },
        }],
        malformed_ratio_catalog, mode="cheapest",
    )
    assert malformed_ratio_basket[0]["match_status"] == "unmatched"
    assert malformed_ratio_basket[0]["product"] is None
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

    # German spoon abbreviations and singular clove are valid recipe units.
    # Spoon measures must convert to ml for real REWE pack-size calculations;
    # cloves remain a distinct count unit and must not merge with whole pieces.
    spoon_units = consolidate([
        {"id": "spoons", "name": "Seasoning", "ingredients": [
            ["olive oil", 1, "EL"], ["curry powder", 1, "TL"],
            ["garlic", 1, "clove"], ["garlic", 2, "cloves"],
        ]},
    ], {"spoons": 2})
    oil_spoon = next(row for row in spoon_units if row["ingredient"] == "olive oil")
    curry_spoon = next(row for row in spoon_units if row["ingredient"] == "curry powder")
    garlic_cloves = next(row for row in spoon_units if row["ingredient"] == "garlic")
    assert oil_spoon["quantity"] == 15 and oil_spoon["unit"] == "ml"
    assert curry_spoon["quantity"] == 5 and curry_spoon["unit"] == "ml"
    assert garlic_cloves["quantity"] == 3 and garlic_cloves["unit"] == "cloves"

    herb_counts = consolidate([
        {"id": "herbs-a", "name": "Herb salad", "ingredients": [
            ["fresh cilantro", 1, "bunch"], ["fresh cilantro", 2, "piece"],
        ]},
        {"id": "herbs-b", "name": "Herb rice", "ingredients": [
            ["fresh cilantro", 1, "Bund"],
        ]},
    ], {"herbs-a": 2, "herbs-b": 2})
    cilantro_bunches = next(row for row in herb_counts if row["unit"] == "bunch")
    cilantro_pieces = next(row for row in herb_counts if row["unit"] == "piece")
    assert cilantro_bunches["quantity"] == 2
    assert cilantro_pieces["quantity"] == 2
    assert len(herb_counts) == 2, "Bunches and loose pieces must not be silently merged"

    assert _convert_quantity(1, "bunch", "piece") is None
    assert _convert_quantity(1, "piece", "bunch") is None

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
    punctuation_pantry_basket = build_basket(
        [{"ingredient": "Red-onion", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest",
        pantry={"red onion": {"quantity": 1, "unit": "piece"}},
    )
    assert punctuation_pantry_basket[0]["pantry_used"] == 1
    assert punctuation_pantry_basket[0]["needed_quantity"] == 1
    punctuation_owned_basket = build_basket(
        [{"ingredient": "Red-onion", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest", owned=["red onion"],
    )
    assert punctuation_owned_basket[0]["match_status"] == "covered"
    infinite_pantry_basket = build_basket(
        [{"ingredient": "onion", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest",
        pantry={"onion": {"quantity": float("inf"), "unit": "piece"}},
    )
    assert infinite_pantry_basket[0]["match_status"] == "matched"
    assert infinite_pantry_basket[0]["pantry_used"] == 0

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

    # Explicit mass/volume estimates for dressings and count/weight estimates for Romaine.
    mayo_ml, mayo_note = _convert_ingredient_quantity(30, "g", "ml", "mayonnaise")
    caesar_ml, caesar_note = _convert_ingredient_quantity(40, "g", "ml", "caesar dressing")
    romaine_pieces, romaine_note = _convert_ingredient_quantity(150, "g", "piece", "romaine lettuce")
    assert round(mayo_ml, 1) == 31.6 and "0.95 g/ml" in mayo_note
    assert caesar_ml == 40 and "1 g/ml" in caesar_note
    flour_grams, flour_note = _convert_ingredient_quantity(250, "ml", "g", "wheat flour")
    assert flour_grams == 120 and "0.48 g/ml" in flour_note
    cheese_grams, cheese_note = _convert_ingredient_quantity(2, "slice", "g", "cheese slices")
    assert cheese_grams == 40 and "20 g per slice" in cheese_note
    assert romaine_pieces == 1.5 and "100 g per piece" in romaine_note
    for invalid_amount in (-1, float("nan"), float("inf"), True):
        assert _convert_ingredient_quantity(invalid_amount, "g", "g", "onion") == (None, None)
    # Search aliases are broader than safe quantity aliases: bare pepper/paprika
    # can mean seasoning and must not inherit a whole bell-pepper weight.
    assert _convert_ingredient_quantity(1, "piece", "g", "pepper") == (None, None)
    assert _convert_ingredient_quantity(1, "piece", "g", "paprika") == (None, None)
    assert _convert_ingredient_quantity(1, "piece", "g", "salat") == (None, None)
    assert _convert_ingredient_quantity(1, "piece", "g", "salad") == (None, None)

    chicken_grams, chicken_note = _convert_ingredient_quantity(2, "piece", "g", "chicken breast")
    broccoli_grams, broccoli_note = _convert_ingredient_quantity(1, "piece", "g", "broccoli")
    cilantro_grams, cilantro_note = _convert_ingredient_quantity(1, "bunch", "g", "fresh cilantro")
    bacon_grams, bacon_note = _convert_ingredient_quantity(3, "slice", "g", "bacon")
    assert chicken_grams == 300 and "150 g per piece" in chicken_note
    assert _convert_ingredient_quantity(1, "piece", "g", "turkey bacon") == (None, None)
    assert broccoli_grams == 300 and "300 g per piece" in broccoli_note
    assert cilantro_grams == 30 and "30 g per bunch" in cilantro_note
    # Bunches must not inherit the per-piece estimate for unrelated produce,
    # and a single loose herb piece must not be treated as a whole bunch.
    assert _convert_ingredient_quantity(1, "bunch", "g", "potato") == (None, None)
    assert _convert_ingredient_quantity(1, "piece", "g", "fresh cilantro") == (None, None)
    assert _convert_ingredient_quantity(30, "g", "piece", "fresh cilantro") == (None, None)
    assert bacon_grams == 45 and "15 g per slice" in bacon_note

    honey_grams, honey_note = _convert_ingredient_quantity(15, "ml", "g", "honey")
    cornstarch_grams, starch_note = _convert_ingredient_quantity(15, "ml", "g", "cornstarch")
    tomato_paste_grams, paste_note = _convert_ingredient_quantity(15, "ml", "g", "tomato paste")
    pesto_grams, pesto_note = _convert_ingredient_quantity(15, "ml", "g", "fresh basil pesto")
    assert round(honey_grams, 1) == 21.3 and "1.42 g/ml" in honey_note
    assert round(cornstarch_grams, 2) == 8.25 and "0.55 g/ml" in starch_note
    assert round(tomato_paste_grams, 2) == 15.75 and "1.05 g/ml" in paste_note
    assert pesto_grams == 15 and "1 g/ml" in pesto_note

    # Recipe ingredient quantities are generated for 2 servings and scaled exactly once.
    one_serving = consolidate([
        {"id": "single", "name": "Single portion", "base_servings": 2,
         "ingredients": [["rice", 150, "g"]]},
    ], {"single": 1})
    assert one_serving[0]["quantity"] == 75

    duplicate_names = consolidate([
        {"id": "duplicates", "name": "Duplicate ingredient QA", "base_servings": 1,
         "ingredients": [["Red-onion", 50, "g"], ["red onion", 20, "g"], ["RED ONION", 10, "g"]]},
    ], {"duplicates": 1})
    assert len(duplicate_names) == 1
    assert duplicate_names[0]["ingredient"] == "Red-onion"
    assert duplicate_names[0]["quantity"] == 80

    # Identical ingredient names and units must remain separate when recipe
    # intent differs materially (whole vs ground spice form).
    form_split = consolidate([
        {"id": "whole-cumin", "name": "Whole cumin", "base_servings": 1,
         "ingredients": [["cumin", 5, "g"]],
         "ingredient_intelligence": {"cumin": {"form": "whole"}}},
        {"id": "ground-cumin", "name": "Ground cumin", "base_servings": 1,
         "ingredients": [["cumin", 5, "g"]],
         "ingredient_intelligence": {"cumin": {"form": "powder"}}},
    ], {"whole-cumin": 1, "ground-cumin": 1})
    assert len(form_split) == 2
    assert {row["ingredient_intelligence"]["form"] for row in form_split} == {"whole", "powder"}
    assert {row["ingredient_form"] for row in form_split} == {"whole", "powder"}
    assert sum(row["quantity"] for row in form_split) == 10
    preparation_split = consolidate([
        {"id": "chopped-garlic", "name": "Chopped garlic", "base_servings": 1,
         "ingredients": [["garlic", 1, "tbsp"]],
         "ingredient_intelligence": {"garlic": {"form": "fresh", "preparation": "chopped"}}},
        {"id": "whole-garlic", "name": "Whole garlic", "base_servings": 1,
         "ingredients": [["garlic", 1, "tbsp"]],
         "ingredient_intelligence": {"garlic": {"form": "fresh", "preparation": "whole"}}},
    ], {"chopped-garlic": 1, "whole-garlic": 1})
    assert len(preparation_split) == 2
    assert {row["unit_validation"]["valid"] for row in preparation_split} == {True, False}

    bunch_requirement = consolidate([
        {"id": "herbs", "name": "Herb recipe", "base_servings": 1,
         "ingredients": [["fresh cilantro", 1, "Bund"]]},
    ], {"herbs": 1})
    assert bunch_requirement[0]["unit"] == "bunch"
    assert bunch_requirement[0]["quantity"] == 1

    # Invalid generated quantities must never be mistaken for pantry-covered
    # ingredients or silently converted into a zero-quantity shopping row.
    for invalid_quantity in (-2, 0, float("nan"), float("inf"), "not-a-number", True):
        invalid_requirements = consolidate([
            {"id": "invalid", "name": "Invalid quantity", "base_servings": 1,
             "ingredients": [["onion", invalid_quantity, "piece"]]},
        ], {"invalid": 1})
        assert invalid_requirements[0]["quantity"] == 0
        assert invalid_requirements[0]["quantity_validation"]["valid"] is False
        invalid_basket = build_basket(
            invalid_requirements, FakeCatalog({"onion": []}), owned=["onion"]
        )
        assert invalid_basket[0]["match_status"] == "unmatched"
        assert invalid_basket[0]["quantity_validation"]["valid"] is False

    missing_unit_requirement = consolidate([
        {"id": "missing-unit", "name": "Missing unit", "base_servings": 1,
         "ingredients": [["onion", 100, None]]},
    ], {"missing-unit": 1})
    assert missing_unit_requirement[0]["unit"] == ""
    assert missing_unit_requirement[0]["unit_validation"]["valid"] is False
    missing_unit_basket = build_basket(
        missing_unit_requirement, FakeCatalog({"onion": []}), owned=["onion"]
    )
    assert missing_unit_basket[0]["match_status"] == "unmatched"

    four_servings = consolidate([
        {"id": "four", "name": "Four portions", "base_servings": 2,
         "ingredients": [["rice", 150, "g"]]},
    ], {"four": 4})
    assert four_servings[0]["quantity"] == 300

    print("PASS: strict title matching, culinary substitutions, portion scaling, unit conversions, pantry deductions, checkout vs consumed cost, and unmatched handling")


if __name__ == "__main__":
    run()
