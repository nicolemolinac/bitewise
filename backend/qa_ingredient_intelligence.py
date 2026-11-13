"""Focused QA for cached recipe-side ingredient intelligence.

Run from backend/: python qa_ingredient_intelligence.py
"""
import os
import tempfile
from pathlib import Path

_QA_DB_DIR = tempfile.TemporaryDirectory(prefix="bitewise-ingredient-intelligence-qa-")
os.environ["DATABASE_URL"] = ""
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_QA_DB_DIR.name) / "qa.sqlite")

from app.ingredient_intelligence import (
    ingredient_candidate_search_terms,
    ingredient_product_match_type,
    _category_compatible,
    _form_compatible,
    ingredient_search_terms,
    ingredient_substitution_name,
    ingredient_suggested_substitution_name,
    normalize_recipe_intelligence,
    normalize_text,
    validate_ingredient_unit,
)
from app.shopping.optimizer import _convert_ingredient_quantity, build_basket, consolidate
from app.server import _adapt_recipe_to_catalog


class IntelligenceCatalog:
    def __init__(self, products):
        self.products = products
        self.received_intelligence = None

    def search(self, ingredient, intelligence=None):
        self.received_intelligence = intelligence
        return self.products.get(ingredient, [])


def test_high_risk_false_positive_guards():
    assert validate_ingredient_unit("bell pepper", "piece")["valid"] is True
    assert ingredient_product_match_type(
        "butter", "BE-KIND Protein Crunchy Peanut Butter 50g",
        product_category="Käse & Eier & Molkerei",
    ) is None
    assert ingredient_product_match_type(
        "honey", "Honig-Senfsauce 60g",
        product_category="Öle, Soßen & Gewürze",
    ) is None
    assert ingredient_product_match_type(
        "salsa", "Alnatura Bio Mais Röllchen Milde Salsa 125g",
        product_category="Süßes & Salziges",
    ) is None
    assert ingredient_product_match_type(
        "white fish fillet", "Nadler Alaska Seelachs Mus 125g",
        product_category="Fleisch, Wurst & Fisch",
    ) is None
    assert ingredient_product_match_type(
        "pasta", "Ayuko Udon Nudeln 200g",
        product_category="Kochen & Backen",
    ) is None


def test_common_english_ingredients_have_german_catalog_terms():
    expected = {
        "tomato": "tomaten", "cherry tomato": "cocktailtomaten",
        "chicken breast": "hahnchenbrust", "ground beef": "rinderhackfleisch",
        "salmon": "lachs", "flour": "weizenmehl", "heavy cream": "schlagsahne",
        "greek yogurt": "griechischer joghurt", "potato": "kartoffeln",
        "mushroom": "champignons", "bell pepper": "paprika",
        "cucumber": "salatgurke", "lemon": "zitrone", "olive oil": "olivenol",
        "soy sauce": "sojasauce", "tomato paste": "tomatenmark",
        "chickpeas": "kichererbsen", "lentils": "linsen",
        "kidney beans": "kidneybohnen", "oats": "haferflocken",
        "banana": "bananen", "baking powder": "backpulver",
        "cornstarch": "speisestarke", "coconut milk": "kokosmilch",
        "rapeseed oil": "rapsol", "sunflower oil": "sonnenblumenol",
        "red onion": "zwiebel rot", "soft tortillas": "weizentortillas",
        "curry powder": "currypulver", "frozen peas": "tiefkuhlerbsen",
        "firm tofu": "naturtofu", "sesame oil": "sesamol",
        "vegetable stock": "gemusebruhe", "cooking cream": "kochsahne",
        "burger buns": "burgerbroetchen", "romaine lettuce": "romanasalat",
        "croutons": "brotwuerfel", "caesar dressing": "caesar dressing",
        "canned chopped tomatoes": "gehackte tomaten", "cumin": "kreuzkuemmel",
        "red cabbage": "rotkohl", "risotto rice": "risottoreis",
        "rolled oats": "haferflocken", "vegetable oil": "pflanzenol",
        "mayonnaise": "salatmayonnaise", "paprika powder": "paprikapulver",
    }
    for ingredient, german_term in expected.items():
        assert german_term in ingredient_search_terms(ingredient), (
            f"Missing German catalog term {german_term!r} for {ingredient!r}"
        )


def run():
    test_common_english_ingredients_have_german_catalog_terms()
    test_high_risk_false_positive_guards()
    raw = {
        "ingredients": [
            ["vegetable oil", 2, "cloves"],
            ["frozen french fries", 300, "g"],
            ["canned corn", 100, "g"],
        ],
        "ingredient_intelligence": {
            "vegetable oil": {
                "canonical": "vegetable oil", "name_en": "vegetable oil",
                "name_de": "Pflanzenöl", "name_es": "aceite vegetal",
                "aliases": ["neutral cooking oil", "Pflanzenöl"],
                "form": "liquid", "culinary_role": "cooking fat",
                "unit_dimension": "volume",
                "suggested_substitutions": ["sunflower oil", "rapeseed oil"],
            },
            "frozen french fries": {
                "canonical": "potato fries", "name_en": "frozen french fries",
                "name_de": "Tiefkühl-Pommes", "name_es": "patatas fritas congeladas",
                "aliases": ["Pommes Frites", "Tiefkühlpommes"],
                "form": "frozen", "culinary_role": "starchy side",
                "unit_dimension": "mass", "suggested_substitutions": ["fresh potatoes"],
            },
            "canned corn": {
                "canonical": "sweet corn", "name_en": "canned sweet corn",
                "name_de": "Mais aus der Dose", "name_es": "maíz en conserva",
                "aliases": ["Mais Konserve", "Dosenmais"],
                "form": "canned", "culinary_role": "vegetable",
                "unit_dimension": "mass", "allowed_substitutions": [],
            },
        },
    }
    intelligence = normalize_recipe_intelligence(raw)
    assert len(intelligence) == 3
    fallback = normalize_recipe_intelligence({
        "ingredients": [["frozen french fries", 300, "g"], ["pre-cooked shredded chicken", 200, "g"], ["vegetable oil", 15, "ml"]],
        "ingredient_intelligence": {},
    })
    assert set(fallback) == {"frozen french fries", "pre cooked shredded chicken", "vegetable oil"}
    assert fallback["frozen french fries"]["form"] == "frozen"
    assert "pommes frites" in fallback["frozen french fries"]["aliases"]
    assert fallback["pre cooked shredded chicken"]["form"] == "pre_cooked"
    assert fallback["vegetable oil"]["unit_dimension"] == "volume"
    # Hyphenated ingredient names must still receive normalized metadata in consolidate().
    hyphenated_recipe = {
        "id": "hyphenated-chicken", "name": "Chicken wrap", "base_servings": 2,
        "ingredients": [["pre-cooked shredded chicken", 200, "g"]],
        "ingredient_intelligence": fallback,
    }
    hyphenated_requirement = consolidate([hyphenated_recipe], {"hyphenated-chicken": 2})
    assert hyphenated_requirement[0]["ingredient_intelligence"]["form"] == "pre_cooked"
    shredded_fallback = normalize_recipe_intelligence({"ingredients": [["shredded lettuce", 100, "g"]]})
    assert shredded_fallback["shredded lettuce"]["form"] == "unspecified"
    assert ingredient_product_match_type("shredded lettuce", "REWE Eisbergsalat 1 Stück") == "exact"
    assert normalize_text("weiß") == "weiss"
    assert "dosenmais" in ingredient_search_terms("canned corn", intelligence)
    assert ingredient_product_match_type("frozen sweet corn", "REWE Zuckermais tiefgekühlt 450g", {"form": "frozen", "aliases": ["Zuckermais tiefgekühlt"]}, "Tiefkühlkost") == "exact"
    assert "rapsol" in ingredient_candidate_search_terms("vegetable oil", intelligence)
    assert "speisekartoffeln" in ingredient_candidate_search_terms("frozen french fries", intelligence)
    proposed_only = {"canonical": "custom cooking fat", "suggested_substitutions": ["rapeseed oil"]}
    proposed_oil_terms = ingredient_candidate_search_terms("custom cooking fat", proposed_only)
    assert "rapeseed oil" in proposed_oil_terms
    assert "rapsol" in proposed_oil_terms, "Proposed substitutions must expand into REWE's German product aliases"
    assert ingredient_product_match_type("custom cooking fat", "REWE Rapsöl 1L", proposed_only) == "suggested_substitution"
    assert ingredient_suggested_substitution_name("custom cooking fat", "REWE Rapeseed Oil 1L", proposed_only) == "rapeseed oil"
    assert ingredient_suggested_substitution_name("custom cooking fat", "REWE Rapsöl 1L", proposed_only) is None
    assert ingredient_product_match_type("canned corn", "REWE Mais aus der Dose 300g", intelligence) == "exact"
    assert ingredient_product_match_type(
        "canned corn", "REWE Bio Zuckermais Tiefkühl 450g", intelligence
    ) is None, "Canned corn must not match frozen corn"
    # Department/category guard: matching a word inside an unrelated prepared product is not a match.
    fresh_pepper = {"form": "fresh", "name_de": "Paprika", "aliases": ["Paprika"]}
    assert ingredient_product_match_type("bell pepper", "REWE Beste Wahl Lyoner Paprika vegan 100g", fresh_pepper, "fleisch-wurst-fisch") is None
    assert ingredient_product_match_type("red onion", "Kettle Chips Cheddar Cheese & Red Onion 130g", {"form": "fresh", "name_de": "rote Zwiebel"}, "suesses-salziges") is None
    assert ingredient_product_match_type("rice", "Freche Freunde Bio Quetschie Apfel, Birne mit Zimt, Reis & Dinkel 100g", {}, "baby-kind") is None
    assert ingredient_product_match_type("olive oil", "Oliva Nachtcreme mit Olivenöl 50ml", {"form": "liquid"}, "drogerie-gesundheit") is None
    assert ingredient_product_match_type("lime", "duschdas Duschgel Limette Minze 450ml", {"form": "fresh"}, "drogerie-gesundheit") is None
    assert ingredient_product_match_type("chicken breast", "Original Wagner Rustipani Helles Ofenbrot Hähnchenbrust 180g", {"form": "fresh"}, "tiefkuehlkost") is None
    assert ingredient_product_match_type("tomatoes", "Alnatura Bio Passierte Tomaten 500g", {"form": "fresh"}, "fertiggerichte-konserven") is None
    assert ingredient_product_match_type("feta cheese", "Maggi Querbeet Ofen-Gemüse mit Feta 27g", {}, "fertiggerichte-konserven") is None
    # Real REWE display labels must map to the matcher allowlists after umlaut transliteration.
    assert ingredient_product_match_type(
        "bell pepper", "REWE Rote Paprika 500g",
        {"form": "fresh", "aliases": ["Rote Paprika"]}, "Obst & Gemüse"
    ) == "exact"
    assert ingredient_product_match_type(
        "feta cheese", "REWE Feta 200g",
        {"aliases": ["Feta"]}, "Käse & Eier & Molkerei"
    ) == "exact"
    assert ingredient_product_match_type(
        "olive oil", "REWE Olivenöl 1L",
        {"form": "liquid", "name_de": "Olivenöl"}, "Öle, Soßen & Gewürze"
    ) == "exact"
    assert ingredient_product_match_type(
        "potatoes", "REWE Kartoffeln tiefgekühlt 750g",
        {"form": "frozen", "aliases": ["Kartoffeln"]}, "Tiefkühlkost"
    ) == "exact"
    assert ingredient_product_match_type(
        "frozen french fries", "REWE Pommes Frites 750g", intelligence
    ) == "exact"
    assert ingredient_product_match_type("frozen french fries", "Pommes Frites Chips", intelligence) is None
    assert ingredient_product_match_type(
        "frozen french fries", "REWE Speisekartoffeln 2kg", intelligence
    ) == "suggested_substitution"
    assert ingredient_product_match_type("frozen french fries", "REWE Speisekartoffeln 2kg", intelligence, "Obst & Gemüse") == "suggested_substitution"
    assert ingredient_product_match_type("vegetable oil", "REWE Rapsöl 1L", intelligence) == "substitute"
    assert ingredient_product_match_type("vegetable oil", "REWE Olivenöl 1L", intelligence) is None
    assert ingredient_substitution_name(
        "vegetable oil", "REWE Rapsöl 1L", intelligence
    ) == "rapeseed oil"
    assert validate_ingredient_unit("vegetable oil", "cloves")["valid"] is False
    assert validate_ingredient_unit("garlic powder", "ml", {"form": "powder"})["valid"] is True
    assert validate_ingredient_unit("garlic powder", "cloves", {"form": "powder"})["valid"] is False
    assert validate_ingredient_unit("chocolate", "g")["valid"] is True
    assert validate_ingredient_unit("hard boiled eggs", "piece")["family"] == "count"
    assert validate_ingredient_unit("hard boiled eggs", "piece")["valid"] is True
    assert validate_ingredient_unit("hard boiled eggs", "g")["valid"] is False
    assert validate_ingredient_unit("hot dog buns", "unit")["valid"] is True
    assert _convert_ingredient_quantity(2, "cloves", "g", "garlic")[0] == 6
    assert _convert_ingredient_quantity(1, "piece", "g", "soft tortillas")[0] == 45
    assert abs(_convert_ingredient_quantity(5, "ml", "g", "cumin")[0] - 2.1) < 0.001
    assert abs(_convert_ingredient_quantity(5, "ml", "g", "paprika powder")[0] - 2.3) < 0.001
    soft_form = {"tortillas": {"canonical": "soft wheat tortilla", "name_de": "Weizentortilla", "form": "soft", "aliases": ["weizentortillas"]}}
    hard_form = {"hard taco shells": {"canonical": "hard taco shell", "name_de": "Taco-Schalen", "form": "hard", "aliases": ["taco shells"]}}
    assert ingredient_product_match_type("tortillas", "Chio Tortillas Original Salted Snacks", soft_form) is None
    assert ingredient_product_match_type("tortillas", "Old El Paso Weizentortillas 320g", soft_form) == "exact"
    assert ingredient_product_match_type("hard taco shells", "Chio Tortillas Original Salted Snacks", hard_form) is None
    # Similar words must not turn prepared foods into raw ingredients.
    oil_profile = {"vegetable oil": {"canonical": "vegetable oil", "form": "liquid", "aliases": ["Sonnenblumenöl", "Rapsöl"]}}
    assert ingredient_product_match_type(
        "vegetable oil", "Thomy Delikatess-Mayonnaise mit reinem Sonnenblumenöl 100ml",
        oil_profile, "Öle, Soßen & Gewürze"
    ) is None
    assert ingredient_product_match_type(
        "vegetable oil", "REWE Rapsöl 1L", oil_profile, "Öle, Soßen & Gewürze"
    ) == "exact"

    chicken_profile = {"chicken breast": {"canonical": "chicken breast", "form": "fresh", "aliases": ["Hähnchenbrustfilet"]}}
    assert ingredient_product_match_type(
        "chicken breast", "ja! Delikatess-Hähnchenbrustfilet gepökelt, gebacken 100g",
        chicken_profile, "Fleisch-Wurst-Fisch"
    ) is None
    raw_chicken_match = ingredient_product_match_type(
        "chicken breast", "REWE Hähnchenbrustfilet 400g",
        chicken_profile, "Fleisch-Wurst-Fisch"
    )
    if raw_chicken_match != "exact":
        from app.ingredient_intelligence import ingredient_search_terms
        print("DEBUG raw chicken:", {
            "result": raw_chicken_match,
            "terms": ingredient_search_terms("chicken breast", chicken_profile),
            "form_ok": _form_compatible("fresh", "rewe hahnchenbrustfilet 400g fleisch wurst fisch", "chicken breast"),
            "category_ok": _category_compatible("chicken breast", "Fleisch-Wurst-Fisch", "rewe hahnchenbrustfilet 400g", "fresh"),
        })
    assert raw_chicken_match == "exact"

    fish_profile = {"white fish fillet": {"canonical": "white fish fillet", "form": "fresh", "aliases": ["Alaska Seelachs"]}}
    assert ingredient_product_match_type(
        "white fish fillet", "Nadler Alaska Seelachs Mus 125g",
        fish_profile, "Fleisch-Wurst-Fisch"
    ) is None
    assert ingredient_product_match_type(
        "white fish fillet", "Alaska Seelachs Filet 400g",
        fish_profile, "Fleisch-Wurst-Fisch"
    ) == "exact"

    assert ingredient_product_match_type(
        "butter", "BE-KIND Protein Crunchy Peanut Butter 50g", None, "Käse-Eier-Molkerei"
    ) is None
    assert ingredient_product_match_type(
        "salsa", "Alnatura Bio Mais Röllchen Milde Salsa 125g", None, "Süßes-Salziges"
    ) is None

    fresh_herb = {"fresh cilantro": {"canonical": "fresh cilantro", "name_de": "Frischer Koriander", "form": "fresh", "aliases": ["Koriander"]}}
    assert ingredient_product_match_type("fresh cilantro", "Koriander", fresh_herb, "Gewürze") is None
    fresh_cilantro_result = ingredient_product_match_type("fresh cilantro", "Koriander", fresh_herb, "Frische Kräuter")
    if fresh_cilantro_result != "exact":
        print("DEBUG fresh cilantro:", {
            "result": fresh_cilantro_result,
            "terms": ingredient_search_terms("fresh cilantro", fresh_herb),
            "form_ok": _form_compatible("fresh", "koriander frische krauter", "fresh cilantro"),
            "category_ok": _category_compatible("fresh cilantro", "Frische Kräuter", "koriander", "fresh"),
        })
    assert fresh_cilantro_result == "exact"
    garlic_profile = {"garlic": {"canonical": "garlic", "name_de": "Knoblauch", "form": "whole", "aliases": ["Knoblauch"]}}
    assert ingredient_product_match_type("garlic", "REWE Bio Hähnchen Brustfilet Joghurt Knoblauch 320g", garlic_profile, "Fleisch") is None
    assert ingredient_product_match_type("garlic", "Knoblauch 1 Stück", garlic_profile, "obst-gemuese") == "exact"
    cooked_chicken = {"pre-cooked shredded chicken": {"canonical": "cooked chicken", "form": "pre_cooked", "aliases": ["Hähnchenbrust"]}}
    assert ingredient_product_match_type("pre-cooked shredded chicken", "REWE Hähnchenbrust 400g", cooked_chicken, "Fleisch") is None
    assert ingredient_product_match_type("pre-cooked shredded chicken", "REWE Hähnchenbrust gegart 300g", cooked_chicken, "Fleisch") == "exact"

    recipe = {
        "id": "oil-test", "name": "Oil test", "base_servings": 2,
        "ingredients": [["vegetable oil", 2, "cloves"]],
        "ingredient_intelligence": intelligence,
    }
    requirement = consolidate([recipe], {"oil-test": 2})
    assert requirement[0]["unit_validation"]["valid"] is False

    catalog = IntelligenceCatalog({
        "vegetable oil": [{
            "id": 11, "name_original": "REWE Rapsöl 1L",
            "package_size": 1, "package_unit": "l", "price": 2.49,
            "availability": "available", "ingredient_match_type": "substitute",
            "ingredient_substitute": "rapeseed oil",
        }]
    })
    basket = build_basket(
        [{"ingredient": "vegetable oil", "quantity": 30, "unit": "ml",
          "source_meals": ["Oil test"], "ingredient_intelligence": intelligence["vegetable oil"],
          "unit_validation": {"valid": True}}],
        catalog,
    )
    assert basket[0]["match_status"] == "substituted"
    assert catalog.received_intelligence["name_de"] == "Pflanzenöl"

    invalid_basket = build_basket(requirement, catalog)
    assert invalid_basket[0]["match_status"] == "unmatched"
    assert invalid_basket[0]["product"] is None

    semantic_catalog = IntelligenceCatalog({"unknown": [{
        "id": 12, "name_original": "Possible semantic REWE product",
        "package_size": 500, "package_unit": "g", "price": 1.99,
        "availability": "available", "ingredient_match_type": "semantic_candidate",
        "semantic_similarity": 0.84,
    }, {
        "id": 13, "name_original": "AI-proposed possible substitute",
        "package_size": 500, "package_unit": "g", "price": 2.19,
        "availability": "available", "ingredient_match_type": "suggested_substitution",
    }]})
    semantic_requirement = [{"ingredient": "unknown", "quantity": 100, "unit": "g", "source_meals": ["Test"]}]
    review_basket = build_basket(semantic_requirement, semantic_catalog)
    assert review_basket[0]["match_status"] == "unmatched"
    assert review_basket[0]["product"] is None
    assert review_basket[0]["semantic_suggestions"][0]["semantic_similarity"] == 0.84
    assert len(review_basket[0]["semantic_suggestions"]) == 2
    confirmed_basket = build_basket(semantic_requirement, semantic_catalog, overrides={"unknown": 12})
    assert confirmed_basket[0]["match_status"] == "matched"
    assert confirmed_basket[0]["selected_by_user"] is True

    potato_catalog = IntelligenceCatalog({"frozen french fries": [{
        "id": 14, "name_original": "REWE Speisekartoffeln 2kg",
        "package_size": 2, "package_unit": "kg", "price": 3.49,
        "availability": "available", "ingredient_match_type": "semantic_candidate",
        "semantic_match_type": "suggested_substitution",
    }]})
    potato_requirement = [{
        "ingredient": "frozen french fries", "quantity": 300, "unit": "g",
        "source_meals": ["Fries"], "ingredient_intelligence": intelligence["frozen french fries"],
    }]
    potato_review = build_basket(potato_requirement, potato_catalog)
    assert potato_review[0]["match_status"] == "unmatched"
    assert potato_review[0]["semantic_suggestions"][0]["semantic_match_type"] == "suggested_substitution"
    potato_confirmed = build_basket(potato_requirement, potato_catalog, overrides={"frozen french fries": 14})
    assert potato_confirmed[0]["match_status"] == "substituted"
    assert potato_confirmed[0]["product"]["ingredient_substitute"] == "fresh potatoes"

    ai_substitute_catalog = IntelligenceCatalog({"custom cooking fat": [{
        "id": 15, "name_original": "REWE Rapeseed Oil 1L",
        "package_size": 1, "package_unit": "l", "price": 2.49,
        "availability": "available", "ingredient_match_type": "suggested_substitution",
        "ingredient_substitute": "rapeseed oil",
    }]})
    ai_substitute_requirement = [{
        "ingredient": "custom cooking fat", "quantity": 30, "unit": "ml",
        "source_meals": ["Test"],
        "ingredient_intelligence": {"canonical": "custom cooking fat", "suggested_substitutions": ["rapeseed oil"]},
    }]
    ai_confirmed = build_basket(ai_substitute_requirement, ai_substitute_catalog, overrides={"custom cooking fat": 15})
    assert ai_confirmed[0]["match_status"] == "substituted"
    assert ai_confirmed[0]["product"]["ingredient_substitute"] == "rapeseed oil"

    adapted_recipe = {"ingredients": [["frozen french fries", 300, "g"]], "steps": [{"text": "Add frozen french fries to the basket."}]}
    _adapt_recipe_to_catalog(adapted_recipe, potato_confirmed)
    assert adapted_recipe["ingredients"][0][0] == "fresh potatoes"
    assert "selected appliance" in adapted_recipe["steps"][0]["text"]

    print("INGREDIENT INTELLIGENCE QA PASS: cached multilingual intent, form-aware matching, safe substitutions, and unit validation")


if __name__ == "__main__":
    run()
