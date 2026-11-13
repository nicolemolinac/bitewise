"""Focused QA for cached recipe-side ingredient intelligence.

Run from backend/: python qa_ingredient_intelligence.py
"""
from app.ingredient_intelligence import (
    ingredient_candidate_search_terms,
    ingredient_product_match_type,
    ingredient_search_terms,
    ingredient_substitution_name,
    normalize_recipe_intelligence,
    normalize_text,
    validate_ingredient_unit,
)
from app.shopping.optimizer import build_basket, consolidate
from app.server import _adapt_recipe_to_catalog


class IntelligenceCatalog:
    def __init__(self, products):
        self.products = products
        self.received_intelligence = None

    def search(self, ingredient, intelligence=None):
        self.received_intelligence = intelligence
        return self.products.get(ingredient, [])


def run():
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
    assert normalize_text("weiß") == "weiss"
    assert "dosenmais" in ingredient_search_terms("canned corn", intelligence)
    assert ingredient_product_match_type("frozen sweet corn", "REWE Zuckermais tiefgekühlt 450g", {"form": "frozen", "aliases": ["Zuckermais tiefgekühlt"]}, "Tiefkühlkost") == "exact"
    assert "rapsol" in ingredient_candidate_search_terms("vegetable oil", intelligence)
    assert "speisekartoffeln" in ingredient_candidate_search_terms("frozen french fries", intelligence)
    proposed_only = {"canonical": "custom cooking fat", "suggested_substitutions": ["rapeseed oil"]}
    assert "rapeseed oil" in ingredient_candidate_search_terms("custom cooking fat", proposed_only)
    assert ingredient_product_match_type("custom cooking fat", "REWE Rapsöl 1L", proposed_only) == "suggested_substitution"
    assert ingredient_product_match_type("canned corn", "REWE Mais aus der Dose 300g", intelligence) == "exact"
    assert ingredient_product_match_type(
        "canned corn", "REWE Bio Zuckermais Tiefkühl 450g", intelligence
    ) is None, "Canned corn must not match frozen corn"
    assert ingredient_product_match_type(
        "frozen french fries", "REWE Pommes Frites 750g", intelligence
    ) == "exact"
    assert ingredient_product_match_type("frozen french fries", "Pommes Frites Chips", intelligence) is None
    assert ingredient_product_match_type(
        "frozen french fries", "REWE Speisekartoffeln 2kg", intelligence
    ) == "substitute"
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
    soft_form = {"tortillas": {"canonical": "soft wheat tortilla", "name_de": "Weizentortilla", "form": "soft", "aliases": ["weizentortillas"]}}
    hard_form = {"hard taco shells": {"canonical": "hard taco shell", "name_de": "Taco-Schalen", "form": "hard", "aliases": ["taco shells"]}}
    assert ingredient_product_match_type("tortillas", "Chio Tortillas Original Salted Snacks", soft_form) is None
    assert ingredient_product_match_type("tortillas", "Old El Paso Weizentortillas 320g", soft_form) == "exact"
    assert ingredient_product_match_type("hard taco shells", "Chio Tortillas Original Salted Snacks", hard_form) is None
    fresh_herb = {"fresh cilantro": {"canonical": "fresh cilantro", "name_de": "Frischer Koriander", "form": "fresh", "aliases": ["Koriander"]}}
    assert ingredient_product_match_type("fresh cilantro", "Koriander", fresh_herb, "Gewürze") is None
    assert ingredient_product_match_type("fresh cilantro", "Koriander", fresh_herb, "Frische Kräuter") == "exact"
    garlic_profile = {"garlic": {"canonical": "garlic", "name_de": "Knoblauch", "form": "whole", "aliases": ["Knoblauch"]}}
    assert ingredient_product_match_type("garlic", "REWE Bio Hähnchen Brustfilet Joghurt Knoblauch 320g", garlic_profile, "Fleisch") is None
    assert ingredient_product_match_type("garlic", "Knoblauch 1 Stück", garlic_profile, "Obst & Gemüse") == "exact"
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
    potato_confirmed = build_basket(potato_requirement, potato_catalog, overrides={"frozen french fries": 14})
    assert potato_confirmed[0]["match_status"] == "substituted"
    assert potato_confirmed[0]["product"]["ingredient_substitute"] == "fresh potatoes"

    adapted_recipe = {"ingredients": [["frozen french fries", 300, "g"]], "steps": [{"text": "Add frozen french fries to the basket."}]}
    _adapt_recipe_to_catalog(adapted_recipe, potato_confirmed)
    assert adapted_recipe["ingredients"][0][0] == "fresh potatoes"
    assert "selected appliance" in adapted_recipe["steps"][0]["text"]

    print("INGREDIENT INTELLIGENCE QA PASS: cached multilingual intent, form-aware matching, safe substitutions, and unit validation")


if __name__ == "__main__":
    run()
