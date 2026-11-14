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


def run():
    # Real REWE titles from the 22-recipe catalog benchmark must be recognized
    # as exact when the recipe's canonical identity, German name and form agree.
    # This protects common pantry/produce ingredients from being downgraded to
    # review-only merely because their German retail label is not an English alias.
    exact_catalog_identity_cases = [
        ("banana", "Bio Banane ca. 200g 1 Stück", {
            "canonical": "banana", "name_en": "banana", "name_de": "Banane",
            "aliases": ["Banane"], "form": "fresh",
        }, "obst-gemuese"),
        ("carrot", "Karotten 1kg", {
            "canonical": "carrot", "name_en": "carrot", "name_de": "Karotte",
            "aliases": ["Karotten"], "form": "fresh",
        }, "obst-gemuese"),
        ("spring onion", "Bio Lauchzwiebel im Bund", {
            "canonical": "spring onion", "name_en": "spring onion", "name_de": "Lauchzwiebel",
            "aliases": ["Lauchzwiebel"], "form": "fresh",
        }, "obst-gemuese"),
        ("lettuce", "Eisbergsalat 1 Stück", {
            "canonical": "lettuce", "name_en": "lettuce", "name_de": "Eisbergsalat",
            "aliases": ["Eisbergsalat"], "form": "fresh",
        }, "obst-gemuese"),
        ("rolled oats", "REWE Bio Haferflocken kernig 500g", {
            "canonical": "rolled oats", "name_en": "rolled oats", "name_de": "Haferflocken",
            "aliases": ["Haferflocken"], "form": "dry",
        }, "kochen-backen"),
        ("white fish fillet", "REWE Beste Wahl Alaska Seelachsfilets tiefgefroren 400g", {
            "canonical": "white fish fillet", "name_en": "white fish fillet",
            "name_de": "Alaska Seelachsfilet", "aliases": ["Seelachsfilet"],
            "form": "frozen",
        }, "tiefkuehlkost"),
    ]
    for ingredient, title, profile, category in exact_catalog_identity_cases:
        actual = ingredient_product_match_type(ingredient, title, profile, category)
        assert actual == "exact", (ingredient, title, actual)

    # The no-AI fallback ontology must cover ordinary REWE ingredients in
    # English and German. These are generic retail aliases, not SKU-specific rules.
    catalog_alias_cases = [
        ("pasta", "REWE Bio Spaghetti 500g", "kochen-backen", "exact"),
        ("pasta", "REWE Bio Penne 500g", "kochen-backen", "exact"),
        ("pizza dough", "Henglein Pizzateig XXL 550g", "fertiggerichte-konserven", "exact"),
        ("pasta", "REWE Bio Spaghetti 500g", "Nudeln & Reis", "exact"),
        ("trofie pasta", "REWE Pasta Penne 500g", "kochen-backen", "substitute"),
        ("fresh basil pesto", "REWE Pesto alla Genovese 190g", "oele-sossen-gewuerze", "exact"),
        ("pine nuts", "Seeberger Pinienkerne 50g", "kochen-backen", "exact"),
        ("tomato", "REWE Rispentomaten 500g", "obst-gemuese", "exact"),
        ("cherry tomato", "REWE Cocktailtomaten 250g", "obst-gemuese", "exact"),
        ("ground beef", "REWE Bio Rinder Hackfleisch 500g", "fleisch-wurst-fisch", "exact"),
        ("salmon", "REWE Bio Lachsfilet 250g", "fleisch-wurst-fisch", "exact"),
        ("flour", "REWE Weizenmehl Type 405 1kg", "kochen-backen", "exact"),
        ("heavy cream", "REWE Schlagsahne 30% 200g", "kaese-eier-molkerei", "exact"),
        ("potato", "REWE Speisekartoffeln 2kg", "obst-gemuese", "exact"),
        ("mushroom", "REWE Champignons 250g", "obst-gemuese", "exact"),
        ("cucumber", "REWE Salatgurke 1 Stück", "obst-gemuese", "exact"),
        ("lemon", "REWE Zitronen 500g", "obst-gemuese", "exact"),
        ("soy sauce", "Kikkoman Sojasauce 150ml", "oele-sossen-gewuerze", "exact"),
        ("tomato paste", "REWE Tomatenmark 200g", "fertiggerichte-konserven", "exact"),
        ("chickpeas", "REWE Bio Kichererbsen 400g", "fertiggerichte-konserven", "exact"),
        ("lentils", "Alnatura Bio Berglinsen 500g", "kochen-backen", "exact"),
        ("kidney beans", "REWE Beste Wahl Kidney-Bohnen 285g", "fertiggerichte-konserven", "exact"),
        ("oats", "REWE Bio Haferflocken kernig 500g", "kochen-backen", "exact"),
        ("banana", "Bio Banane 1 Stück", "obst-gemuese", "exact"),
        ("honey", "REWE Bio Blütenhonig 500g", "brot-cerealien-aufstriche", "exact"),
        ("baking powder", "REWE Backpulver 3x15g", "kochen-backen", "exact"),
        ("cornstarch", "REWE Speisestärke 400g", "kochen-backen", "exact"),
        ("coconut milk", "REWE Kokosmilch 400ml", "fertiggerichte-konserven", "exact"),
        ("parmesan", "REWE Bio Parmigiano Reggiano 150g", "kaese-eier-molkerei", "exact"),
        ("egg", "REWE Freilandeier 10 Stück", "kaese-eier-molkerei", "exact"),
        ("spinach", "REWE Babyspinat 100g", "obst-gemuese", "exact"),
        ("broccoli", "REWE Brokkoli 500g", "obst-gemuese", "exact"),
        ("strawberry", "REWE Erdbeeren 500g", "obst-gemuese", "exact"),
        ("shrimp", "REWE Garnelen 200g", "fleisch-wurst-fisch", "exact"),
        ("tuna", "REWE Thunfisch in eigenem Saft 195g", "fertiggerichte-konserven", "exact"),
        ("bacon", "REWE Frühstücksspeck 100g", "fleisch-wurst-fisch", "exact"),
        ("turkey", "REWE Putenbrust 400g", "fleisch-wurst-fisch", "exact"),
        ("bread", "REWE Vollkornbrot 500g", "brot-cerealien-aufstriche", "exact"),
        ("sugar", "REWE Haushaltszucker 1kg", "kochen-backen", "exact"),
        ("tofu", "REWE Bio Tofu Natur 200g", "fleisch-wurst-fisch", "exact"),
    ]
    for ingredient, title, category, expected in catalog_alias_cases:
        actual = ingredient_product_match_type(ingredient, title, None, category)
        assert actual == expected, (ingredient, title, expected, actual)

    assert ingredient_product_match_type(
        "oats", "REWE Bio Haferflocken kernig 500g", None,
        "brot-cerealien-aufstriche"
    ) == "exact"
    assert ingredient_product_match_type(
        "cornstarch", "Mondamin Feine Speisestärke 400g", None,
        "kochen-backen"
    ) == "exact"
    assert ingredient_product_match_type(
        "oats", "Alpro Haferdrink 1L", None, "kaffee-tee-kakao"
    ) is None

    # Form intent is a hard constraint: dried herbs cannot silently resolve
    # to fresh herbs, and whole spices cannot resolve to ground equivalents.
    assert ingredient_product_match_type(
        "oregano", "REWE Bio Oregano frisch 15g", {"form": "dried"}, "obst-gemuese"
    ) is None
    assert ingredient_product_match_type(
        "oregano", "REWE Bio Oregano gerebelt 8g", {"form": "dried"}, "oele-sossen-gewuerze"
    ) == "exact"
    assert ingredient_product_match_type(
        "cumin", "REWE Kreuzkümmel gemahlen 40g", {"form": "whole"}, "oele-sossen-gewuerze"
    ) is None
    assert ingredient_product_match_type(
        "cumin", "REWE Kreuzkümmel ganz 40g", {"form": "whole"}, "oele-sossen-gewuerze"
    ) == "exact"
    assert ingredient_product_match_type(
        "rice", "REWE Beste Wahl Langkornreis 500g",
        {"canonical": "rice", "name_en": "rice", "name_de": "Reis",
         "aliases": ["Langkornreis"], "form": "dry"}, "Rice"
    ) == "exact", "Generic dry pantry form must not be treated as dried produce/herbs"
    assert ingredient_product_match_type(
        "cumin", "REWE Kreuzkümmel 40g", {"form": "whole"}, "oele-sossen-gewuerze"
    ) is None, "Unspecified cumin form must not be assumed whole"
    milk_profile = {
        "canonical": "milk", "name_en": "milk", "name_de": "Milch",
        "aliases": ["Vollmilch"], "form": "liquid",
    }
    assert ingredient_product_match_type(
        "milk", "REWE Frische Vollmilch 3,8% 1L", milk_profile, "kaese-eier-molkerei"
    ) == "exact"
    assert ingredient_product_match_type(
        "milk", "REWE Schokomilch 500ml", milk_profile, "kaese-eier-molkerei"
    ) is None
    assert ingredient_product_match_type(
        "milk", "REWE Kondensmilch 7,5% 340g", milk_profile, "kaese-eier-molkerei"
    ) is None
    assert ingredient_product_match_type(
        "milk", "REWE Buttermilch 500ml", milk_profile, "kaese-eier-molkerei"
    ) is None
    assert ingredient_product_match_type(
        "milk", "REWE Milchpulver 500g", {"form": "unspecified"}, "kochen-backen"
    ) is None
    assert ingredient_product_match_type(
        "milk", "REWE Vollmilchpulver 500g", {"form": "unspecified"}, "kochen-backen"
    ) is None
    assert ingredient_product_match_type(
        "milk", "REWE Kokosmilch 400ml", {"form": "unspecified"}, "konserven"
    ) is None
    assert ingredient_product_match_type(
        "milk", "Alpro Haferdrink 1L", milk_profile, "kaffee-tee-kakao"
    ) == "suggested_substitution"
    canned_corn_profile = {
        "canonical": "canned corn", "name_en": "canned corn",
        "name_de": "Mais aus der Dose", "aliases": ["Dosenmais"],
        "form": "canned",
    }
    assert ingredient_product_match_type(
        "canned corn", "REWE Beste Wahl Zuckermais 340g",
        canned_corn_profile, "Fertiggerichte & Konserven"
    ) == "exact"
    assert ingredient_product_match_type(
        "canned corn", "REWE Zuckermais 2 Stück",
        canned_corn_profile, "obst-gemuese"
    ) is None
    assert ingredient_product_match_type(
        "canned corn", "REWE Zuckermais 2 Stück", None, "obst-gemuese"
    ) is None, "Ingredient-name fallback must preserve canned form intent"
    assert ingredient_product_match_type(
        "canned corn", "REWE Beste Wahl Zuckermais 340g", None,
        "Fertiggerichte & Konserven"
    ) == "exact"
    assert ingredient_product_match_type(
        "egg", "REWE Freilandeier 10 Stück", None, "kaese-eier-molkerei"
    ) == "exact"
    assert ingredient_product_match_type(
        "egg", "REWE gekochte Eier 2 Stück", None, "kaese-eier-molkerei"
    ) is None
    assert ingredient_product_match_type(
        "salmon", "REWE Bio Lachsfilet 250g", None, "fleisch-wurst-fisch"
    ) == "exact"
    assert ingredient_product_match_type(
        "salmon", "REWE geräuchertes Lachsfilet 100g", None, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "shrimp", "REWE Garnelen 200g", None, "fleisch-wurst-fisch"
    ) == "exact"
    assert ingredient_product_match_type(
        "shrimp", "REWE Garnelen gekochte 200g", None, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "tofu", "REWE Bio Tofu Natur 200g", None, "fleisch-wurst-fisch"
    ) == "exact"
    assert ingredient_product_match_type(
        "tofu", "REWE Bio Tofu-Würstchen 200g", None, "fleisch-wurst-fisch"
    ) is None

    assert ingredient_product_match_type(
        "pizza dough", "ja! Backfertiger Pizzateig mit Sauce 600g",
        None, "fertiggerichte-konserven"
    ) is None
    assert ingredient_product_match_type(
        "pizza dough", "Knack & Back Glutenfreier Pizzateig vegan 260g",
        None, "fertiggerichte-konserven"
    ) is None
    assert ingredient_product_match_type(
        "pizza dough", "Knack & Back Pizza-Kit 600g",
        None, "fertiggerichte-konserven"
    ) is None

    assert ingredient_product_match_type(
        "pizza dough", "REWE Bio Pizza-Teig Backmischung 350g",
        None, "kochen-backen"
    ) is None

    butter_profile = {
        "canonical": "butter", "name_en": "butter", "name_de": "Butter",
        "aliases": ["Butter"], "form": "solid",
    }
    assert ingredient_product_match_type(
        "butter", "REWE Deutsche Markenbutter 250g", butter_profile, "kaese-eier-molkerei"
    ) == "exact"
    assert ingredient_product_match_type(
        "butter", "REWE Kräuterbutter 125g", butter_profile, "kaese-eier-molkerei"
    ) is None
    assert ingredient_product_match_type(
        "butter", "REWE Butterkäse 200g", butter_profile, "kaese-eier-molkerei"
    ) is None
    olive_oil_profile = {
        "canonical": "olive oil", "name_en": "olive oil", "name_de": "Olivenöl",
        "aliases": ["Olivenöl"], "form": "liquid",
    }
    assert ingredient_product_match_type(
        "olive oil", "REWE Bio Natives Olivenöl Extra 500ml",
        olive_oil_profile, "oele-sossen-gewuerze"
    ) == "exact"
    assert ingredient_product_match_type(
        "olive oil", "REWE Olivenöl Spray 200ml",
        olive_oil_profile, "oele-sossen-gewuerze"
    ) is None

    # Compound spice names must be classified as spices before generic
    # produce substrings; bell pepper remains produce.
    for pepper_name in ("black pepper", "ground black pepper"):
        for pepper_unit in ("tsp", "tbsp", "pinch"):
            result = validate_ingredient_unit(pepper_name, pepper_unit)
            assert result["valid"] and result["family"] == "spice", (pepper_name, pepper_unit, result)
    assert validate_ingredient_unit("bell pepper", "piece")["family"] == "produce"
    assert validate_ingredient_unit("bell pepper", "tsp")["valid"] is False
    assert validate_ingredient_unit("pepper", "tsp")["family"] == "spice"
    assert validate_ingredient_unit("pepper", "tsp")["valid"] is True
    assert validate_ingredient_unit("salt", "Prise")["valid"] is True
    assert validate_ingredient_unit("salt", "Teelöffel")["valid"] is True
    assert validate_ingredient_unit("rice", "Gramm")["valid"] is True
    assert validate_ingredient_unit("garlic", "Zehe")["valid"] is True
    assert validate_ingredient_unit("onion", "Zehe")["valid"] is False
    assert validate_ingredient_unit("fresh cilantro", "Bund")["valid"] is True
    assert validate_ingredient_unit("rice", "g")["family"] == "grains"
    assert validate_ingredient_unit("rice", "tsp")["valid"] is False
    assert validate_ingredient_unit("wheat flour", "cup")["valid"] is True
    assert validate_ingredient_unit("wheat flour", "tsp")["valid"] is True
    assert validate_ingredient_unit("cheddar cheese", "g")["family"] == "dairy_solid"
    assert validate_ingredient_unit("cheddar cheese", "tsp")["valid"] is False
    assert validate_ingredient_unit("cheese slices", "slices")["valid"] is True
    assert validate_ingredient_unit("butter", "tbsp")["valid"] is True
    assert validate_ingredient_unit("butter beans", "g")["family"] == "legumes"
    assert validate_ingredient_unit("butter beans", "g")["valid"] is True
    assert validate_ingredient_unit("butter beans", "tsp")["valid"] is False
    assert validate_ingredient_unit("kidney beans", "cup")["valid"] is True
    assert validate_ingredient_unit("peanut butter", "tbsp")["valid"] is True
    assert validate_ingredient_unit("cheddar cheese", "tbsp")["valid"] is False
    assert validate_ingredient_unit("grated cheddar cheese", "cup")["valid"] is True
    assert validate_ingredient_unit("red pepper flakes", "tsp")["family"] == "spice"
    assert validate_ingredient_unit("red pepper", "piece")["family"] == "produce"
    assert validate_ingredient_unit("chopped onion", "cup", {"form": "chopped"})["valid"] is True
    assert validate_ingredient_unit("minced garlic", "tbsp")["valid"] is True
    assert validate_ingredient_unit("onion", "cup")["valid"] is False
    assert validate_ingredient_unit("garlic", "cloves")["valid"] is True
    assert validate_ingredient_unit("onion", "cloves")["valid"] is False
    assert validate_ingredient_unit("olive oil", "cup")["valid"] is True

    # Common ingredient families must reject nonsensical units even when
    # recipe-side AI metadata is absent.
    for produce_name in ("spinach", "broccoli", "mushroom", "cucumber", "lemon", "banana"):
        assert validate_ingredient_unit(produce_name, "g")["family"] == "produce"
        assert validate_ingredient_unit(produce_name, "tsp")["valid"] is False
    for protein_name in ("ground beef", "salmon", "shrimp", "turkey", "bacon", "tofu"):
        assert validate_ingredient_unit(protein_name, "g")["family"] == "protein"
        assert validate_ingredient_unit(protein_name, "tsp")["valid"] is False
    assert validate_ingredient_unit("honey", "tbsp")["family"] == "sweetener"
    assert validate_ingredient_unit("sugar snap peas", "g")["family"] == "produce"
    assert validate_ingredient_unit("sugar snap peas", "tsp")["valid"] is False
    assert validate_ingredient_unit("sugar", "tsp")["valid"] is True
    assert validate_ingredient_unit("baking powder", "tsp")["family"] == "leavening"
    assert validate_ingredient_unit("baking powder", "ml")["valid"] is True
    assert validate_ingredient_unit("cornstarch", "tbsp")["family"] == "starch"
    assert validate_ingredient_unit("pine nuts", "cup")["family"] == "nuts"
    assert validate_ingredient_unit("tomato paste", "tbsp")["family"] == "condiment"
    assert validate_ingredient_unit("fresh basil pesto", "tbsp")["valid"] is True

    assert validate_ingredient_unit("dried basil", "tsp")["family"] == "spice"
    assert validate_ingredient_unit("dry oregano", "tsp")["valid"] is True
    assert validate_ingredient_unit("oregano", "tsp")["valid"] is True
    assert validate_ingredient_unit("fresh basil", "bunch")["family"] == "produce"
    assert validate_ingredient_unit("fresh basil", "tsp")["valid"] is False

    # A cross-form frozen product for a fresh fish request is a reviewable
    # substitution, not an exact identity.
    assert ingredient_product_match_type(
        "white fish fillet",
        "REWE Beste Wahl Alaska Seelachsfilets tiefgefroren 400g",
        {"canonical": "white fish fillet", "form": "fresh",
         "aliases": ["Seelachsfilet", "Alaska Seelachs"]},
        "tiefkuehlkost",
    ) == "suggested_substitution"
    # Composition/form modifiers must not be hidden behind broad aliases.
    assert ingredient_product_match_type(
        "pizza dough",
        "Bauck Mühle Bio PizzaTeig glutenfrei 350g",
        {"canonical": "pizza dough", "form": "fresh", "aliases": ["Pizzateig"]},
        "kochen-backen",
    ) == "suggested_substitution"
    assert ingredient_product_match_type(
        "soft tortillas",
        "REWE Beste Wahl High Protein Wraps 320g",
        {"canonical": "soft tortillas", "form": "soft", "aliases": ["Wraps"]},
        "fertiggerichte-konserven",
    ) == "substitute"
    assert ingredient_substitution_name(
        "soft tortillas", "REWE Beste Wahl High Protein Wraps 320g"
    ) == "high protein wraps"
    assert ingredient_product_match_type(
        "burger buns", "Actipan Das Vollkornbrötchen 570g, 6 Stück",
        {"form": "unspecified"}, "brot-cerealien-aufstriche"
    ) == "substitute"
    assert ingredient_substitution_name(
        "burger buns", "Actipan Das Vollkornbrötchen 570g, 6 Stück"
    ) == "bread rolls"
    assert ingredient_product_match_type(
        "greek yogurt", "Andechser Natur Bio Joghurt Griechischer Art 400g",
        {"form": "unspecified"}, "kaese-eier-molkerei"
    ) == "substitute"
    assert ingredient_substitution_name(
        "greek yogurt", "Andechser Natur Bio Joghurt Griechischer Art 400g"
    ) == "Greek-style yogurt"
    assert ingredient_product_match_type(
        "greek yogurt", "Elinas Joghurt Griechischer Art Blutorange 4x150g",
        {"form": "unspecified"}, "kaese-eier-molkerei"
    ) is None

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
                "substitution_options": [{
                    "name": "fresh potatoes", "reason": "Closest whole-food equivalent.",
                    "role_preserved": True, "safe_to_auto_apply": True,
                    "quantity_ratio": 1,
                    "preparation_adjustment": "Fresh potatoes need longer than frozen fries; cut evenly and cook until tender.",
                }],
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
    assert normalize_recipe_intelligence({
        "ingredients": [["dry rice", 150, "g"]]
    })["dry rice"]["form"] == "unspecified"
    assert normalize_recipe_intelligence({
        "ingredients": [["dry oregano", 1, "tsp"]]
    })["dry oregano"]["form"] == "dried"
    assert ingredient_product_match_type(
        "oregano", "REWE Oregano frisch 15g", {"form": "dry"}, "obst-gemuese"
    ) is None
    # "Ground" is context-sensitive: minced meat must not be treated as spice powder.
    assert normalize_recipe_intelligence({
        "ingredients": [["ground beef", 500, "g"]]
    })["ground beef"]["form"] == "minced"
    assert normalize_recipe_intelligence({
        "ingredients": [["ground cumin", 2, "tsp"]]
    })["ground cumin"]["form"] == "powder"
    assert ingredient_product_match_type(
        "ground beef", "REWE Bio Rinder Hackfleisch 500g",
        {"canonical": "ground beef", "name_en": "ground beef",
         "name_de": "Rinder Hackfleisch", "aliases": ["Rinder Hackfleisch"],
         "form": "ground"}, "fleisch-wurst-fisch"
    ) == "exact"
    assert ingredient_product_match_type(
        "ground beef", "REWE Bio Rinder Hackfleisch 500g",
        {"canonical": "ground beef", "name_en": "ground beef",
         "name_de": "Rinder Hackfleisch", "aliases": ["Rinder Hackfleisch"],
         "form": "minced"}, "fleisch-wurst-fisch"
    ) == "exact"
    assert ingredient_product_match_type(
        "ground beef", "REWE Rindersteak 500g",
        {"canonical": "ground beef", "form": "minced"}, "fleisch-wurst"
    ) is None
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

    # AI metadata expands retrieval, but cannot manufacture exact identity.
    # A hallucinated canonical name/alias must remain a review-only candidate.
    untrusted_alias_profile = {
        "canonical": "curry paste",
        "name_en": "curry paste",
        "name_de": "Currypaste",
        "aliases": ["curry paste", "currypaste"],
        "form": "unspecified",
    }
    assert ingredient_product_match_type(
        "curry powder", "REWE Thai Curry Paste 100g",
        untrusted_alias_profile, "oele-sossen-gewuerze"
    ) == "suggested_substitution"
    assert ingredient_product_match_type(
        "curry powder", "REWE Currypulver mild 50g",
        untrusted_alias_profile, "oele-sossen-gewuerze"
    ) == "exact"
    oil_alias_profile = {
        "canonical": "vegetable oil", "form": "liquid",
        "aliases": ["Rapsöl", "rapeseed oil"],
    }
    assert ingredient_product_match_type(
        "vegetable oil", "REWE Rapsöl 1L",
        oil_alias_profile, "oele-sossen-gewuerze"
    ) == "substitute", "An AI alias must not downgrade a curated substitute into an untyped review candidate"
    custom_alias_profile = {
        "canonical": "fresh cilantro",
        "name_en": "fresh cilantro",
        "name_de": "frischer Koriander",
        "aliases": ["Koriandergrün", "coriander leaves"],
        "form": "fresh",
    }
    assert ingredient_product_match_type(
        "custom herb", "REWE Bio Koriandergrün 20g",
        custom_alias_profile, "frische-krauter"
    ) == "suggested_substitution"

    # Canonically grounded, form-specific retail aliases can establish exact
    # matches; aliases from a mismatched AI canonical identity stay review-only.
    assert ingredient_product_match_type(
        "carrot", "Karotten 1kg",
        {"canonical": "carrot", "name_en": "carrot", "name_de": "Möhre",
         "aliases": ["Karotten"], "form": "fresh"},
        "obst-gemuese"
    ) == "exact"
    assert ingredient_product_match_type(
        "banana", "Bio Banane ca. 200g",
        {"canonical": "banana", "name_en": "banana", "name_de": "Bananen",
         "aliases": ["Banane"], "form": "fresh"},
        "obst-gemuese"
    ) == "exact"
    assert ingredient_product_match_type(
        "lettuce", "REWE Beste Wahl Romana Salatherzen 3 Stück",
        {"canonical": "lettuce", "name_en": "lettuce", "name_de": "Eisbergsalat",
         "aliases": ["Salatherzen", "Salat"], "form": "fresh"},
        "obst-gemuese"
    ) == "exact"
    assert ingredient_product_match_type(
        "spring onion", "Bio Lauchzwiebel im Bund",
        {"canonical": "spring onion", "name_en": "spring onion",
         "name_de": "Frühlingszwiebel", "aliases": ["Lauchzwiebel"], "form": "fresh"},
        "obst-gemuese"
    ) == "exact"
    assert ingredient_product_match_type(
        "white fish fillet", "REWE Atlantisches Kabeljaufilet 475g",
        {"canonical": "white fish fillet", "name_en": "white fish fillet",
         "name_de": "Seelachsfilet", "aliases": ["Kabeljaufilet"], "form": "fresh"},
        "fleisch-wurst-fisch"
    ) == "exact"
    assert "olivenöl" in ingredient_candidate_search_terms("olive oil", {"form": "liquid"})
    assert "rapsöl" in ingredient_candidate_search_terms("vegetable oil", {"form": "liquid"})
    assert "hähnchenbrustfilet" in ingredient_candidate_search_terms("chicken breast", {"form": "fresh"})
    assert "croûtons" in ingredient_candidate_search_terms("croutons", {})
    assert "paprika edelsüß" in ingredient_candidate_search_terms("paprika powder", {})
    assert ingredient_product_match_type(
        "olive oil", "REWE Bio Olivenöl Nativ Extra 500ml", {"form": "liquid"}, "oele-sossen-gewuerze"
    ) == "exact"
    assert ingredient_product_match_type(
        "vegetable oil", "REWE Rapsöl 1L", {"form": "liquid"}, "oele-sossen-gewuerze"
    ) == "substitute"
    assert ingredient_product_match_type(
        "vegetable stock", "Knorr Hühner Brühe Würfel 6x", {"form": "liquid"}, "oele-sossen-gewuerze"
    ) is None, "Generic stock-cube wording must not turn chicken stock into vegetable stock"
    assert ingredient_product_match_type(
        "vegetable stock", "REWE Bio Gemüse Brühe Würfel 6x", {"form": "liquid"}, "oele-sossen-gewuerze"
    ) == "suggested_substitution", "Vegetable stock cubes require dilution and must not be treated as ready-to-use liquid stock"
    assert ingredient_product_match_type(
        "vegetable oil", "REWE Bio Sonnenblumenöl nativ 500ml", {"form": "liquid"}, "oele-sossen-gewuerze"
    ) == "suggested_substitution", "Native sunflower oil must be reviewed rather than auto-selected as neutral cooking oil"
    assert ingredient_product_match_type(
        "vegetable oil", "REWE Bio Rapsöl kaltgepresst 500ml", {"form": "liquid"}, "oele-sossen-gewuerze"
    ) == "suggested_substitution", "Cold-pressed rapeseed oil must also remain review-only for neutral cooking oil"
    assert ingredient_product_match_type(
        "vegetable oil", "REWE Sonnenblumenöl raffiniert 1L", {"form": "liquid"}, "oele-sossen-gewuerze"
    ) == "substitute", "Refined neutral sunflower oil remains a safe cooking-oil substitute"
    assert ingredient_product_match_type(
        "red onion", "Zwiebel rot 500g im Netz", {"form": "fresh"}, "obst-gemuese"
    ) == "exact"
    assert ingredient_product_match_type(
        "rice", "REWE Beste Wahl Express Basmati Reis 250g", {"form": "unspecified"}, "kochen-backen"
    ) is None, "Ready-to-heat express rice must not match a dry-rice recipe ingredient"
    assert ingredient_product_match_type(
        "spaghetti", "Biozentrale Bio Dinkel Spaghetti 250g", {"form": "unspecified"}, "kochen-backen"
    ) == "suggested_substitution", "Spelt pasta must be shown for review, not silently treated as ordinary spaghetti"
    assert ingredient_product_match_type(
        "pasta", "REWE Bio Fusilli aus Vollkornreis glutenfrei 250g", {"form": "unspecified"}, "kochen-backen"
    ) == "suggested_substitution", "Gluten-free rice pasta must be offered for review rather than silently treated as ordinary pasta"
    assert ingredient_product_match_type(
        "rice", "REWE Bio Basmati Reis 500g", {"form": "unspecified"}, "kochen-backen"
    ) == "exact", "Plain dry rice remains an exact match"
    for rice_derived in (
        "REWE Bio Rice Flour 500g",
        "REWE Reismehl 500g",
        "REWE Rice Pudding 400g",
        "REWE Reiswaffeln 100g",
        "REWE Rice Noodles 250g",
    ):
        assert ingredient_product_match_type(
            "rice", rice_derived, {"form": "unspecified"}, "kochen-backen"
        ) is None, f"Rice-derived product must not match dry rice: {rice_derived}"
    assert ingredient_product_match_type(
        "chicken breast", "REWE Bio Hähnchenbrustfilet 400g", {"form": "fresh"}, "fleisch-wurst-fisch"
    ) == "exact"
    assert ingredient_product_match_type(
        "white fish fillet", "REWE Alaska Seelachsfilet 300g", {"form": "fresh"}, "fleisch-wurst-fisch"
    ) == "exact"
    high_protein_wrap_match = ingredient_product_match_type(
        "soft tortillas", "REWE Beste Wahl High Protein Wraps 320g",
        {"form": "soft"}, "fertiggerichte-konserven"
    )
    assert high_protein_wrap_match == "substitute", (
        "Protein-enriched wraps are safe culinary substitutions, not exact identities; "
        f"got {high_protein_wrap_match!r}"
    )
    assert ingredient_product_match_type(
        "croutons", "Leimer Croûtons Kräuter 100g", {"form": "unspecified"}, "oele-sossen-gewuerze"
    ) == "exact"
    assert ingredient_product_match_type(
        "croutons", "ja! Kartoffelpüree mit Röstzwiebeln und Croûtons 59g",
        {"form": "unspecified"}, "fertiggerichte-konserven"
    ) is None, "Croutons mentioned inside a complete prepared meal are not a standalone ingredient match"
    assert ingredient_product_match_type(
        "croutons", "REWE Kartoffelauflauf mit Röstzwiebeln und Croûtons 400g",
        {"form": "unspecified"}, "fertiggerichte-konserven"
    ) is None, "Croutons inside a prepared casserole are not a standalone ingredient match"
    assert ingredient_product_match_type(
        "croutons", "REWE Mikrowellen-Fertigmahlzeit mit Croûtons 350g",
        {"form": "unspecified"}, "fertiggerichte-konserven"
    ) is None, "Croutons inside a microwave meal are not a standalone ingredient match"
    assert ingredient_product_match_type(
        "lettuce", "REWE Beste Wahl Eisbergsalat mit Kräutern 175g",
        {"form": "fresh"}, "obst-gemuese"
    ) is None, "Seasoned convenience salad must not be silently selected as plain lettuce"
    assert ingredient_product_match_type(
        "burger buns", "REWE Hamburgerbrötchen mit Sesam 300g", {"form": "unspecified"}, "brot-cerealien-aufstriche"
    ) == "exact"
    kaiser_match = ingredient_product_match_type(
        "burger buns", "REWE Kaiserbrötchen 4 Stück", {"form": "unspecified"}, "brot-cerealien-aufstriche"
    )
    assert kaiser_match == "substitute"
    assert ingredient_product_match_type(
        "grated cheddar cheese", "REWE Gouda gerieben 200g", {"form": "grated"}, "kaese-eier-molkerei"
    ) == "substitute"
    assert ingredient_product_match_type(
        "romaine lettuce", "REWE Beste Wahl Romana Salatherzen 3 Stück", {"form": "fresh"}, "obst-gemuese"
    ) == "exact"
    assert ingredient_product_match_type(
        "red cabbage", "REWE Weißkohl frisch 1 Stück", {"form": "fresh"}, "obst-gemuese"
    ) == "substitute"
    assert ingredient_product_match_type(
        "curry powder", "REWE Bio Thai Curry Paste 100g", {"form": "powder"}, "oele-sossen-gewuerze"
    ) == "suggested_substitution"
    fish_test_title = "REWE Beste Wahl Alaska Seelachsfilets tiefgefroren 400g"
    fish_test_match = ingredient_product_match_type(
        "white fish fillet", fish_test_title, {"form": "fresh"}, "tiefkuehlkost"
    )
    assert fish_test_match == "suggested_substitution", f"Fresh fish must keep frozen candidates review-only; got {fish_test_match!r}"
    assert ingredient_product_match_type(
        "white fish fillet", "REWE Beste Wahl Alaska Seelachsfilets tiefgefroren 400g",
        {"form": "fresh"}, "Tiefkühlkost"
    ) == "suggested_substitution"
    high_protein_wrap_type = ingredient_product_match_type(
        "soft tortillas", "REWE Beste Wahl High Protein Wraps 320g",
        {"form": "soft tortillas"}, "fertiggerichte-konserven"
    )
    assert high_protein_wrap_type == "substitute", (
        f"High-protein wraps should be a role-preserving substitute; got {high_protein_wrap_type!r}"
    )
    assert ingredient_product_match_type(
        "croutons", "Leimer Croûtons Kräuter 100g",
        {"form": "prepared bread cubes"}, "oele-sossen-gewuerze"
    ) == "exact"
    assert ingredient_product_match_type(
        "burger buns", "REWE Hamburgerbrötchen mit Sesam 300g",
        {"form": "bread"}, "brot-cerealien-aufstriche"
    ) == "exact"
    assert ingredient_product_match_type(
        "grated cheddar cheese", "REWE Gouda gerieben 200g",
        {"form": "grated cheese"}, "kaese-eier-molkerei"
    ) == "substitute"
    assert ingredient_product_match_type(
        "red cabbage", "REWE Weißkohl frisch 1 Stück",
        {"form": "fresh"}, "obst-gemuese"
    ) == "substitute"
    assert ingredient_product_match_type(
        "burger buns", "REWE Weizenbrötchen 6 Stück",
        {"form": "bread"}, "brot-cerealien-aufstriche"
    ) == "substitute"
    assert ingredient_product_match_type(
        "burger buns", "Coppenrath & Wiese 9 Weizen-Brötchen 450g",
        {"form": "bread"}, "tiefkuehlkost"
    ) == "suggested_substitution"
    assert ingredient_product_match_type(
        "burger buns", "Mälzer & Fu Waffeleis Franzbrötchen 4x120ml",
        {"form": "bread"}, "tiefkuehlkost"
    ) is None
    assert ingredient_product_match_type(
        "burger buns", "Mühlenkraft Proteinmehl Brot & Brötchen 800g",
        {"form": "bread"}, "kochen-backen"
    ) is None
    assert ingredient_product_match_type(
        "curry powder", "Bamboo Garden Thai Curry Paste 100g",
        {"form": "powder"}, "oele-sossen-gewuerze"
    ) == "suggested_substitution"
    assert ingredient_product_match_type(
        "curry powder", "Bamboo Garden Thai Curry Paste 100g",
        {}, "oele-sossen-gewuerze"
    ) == "suggested_substitution", "A paste must never become an exact powder match when recipe form metadata is missing"
    assert "curry paste" in ingredient_candidate_search_terms("curry powder", {"form": "powder"})
    assert ingredient_suggested_substitution_name(
        "curry powder", "Bamboo Garden Thai Curry Paste 100g", {"form": "powder"}
    ) == "curry paste"
    assert ingredient_product_match_type(
        "curry powder", "REWE Bio Garam Masala gemahlen 30g",
        {"form": "powder"}, "oele-sossen-gewuerze"
    ) == "suggested_substitution"
    assert ingredient_product_match_type(
        "white fish fillet", "REWE Alaska Seelachsfilet paniert 800g",
        {"form": "fresh"}, "tiefkuehlkost"
    ) is None
    prepared_match = ingredient_product_match_type(
        "red cabbage", "Rotkohl ca. 1,8kg 1 Stück ca. 1800 g",
        {"form": "fresh"}, "fertiggerichte-konserven"
    )
    assert prepared_match is None, "Prepared red cabbage must not match a fresh raw cabbage ingredient"
    assert ingredient_product_match_type(
        "rolled oats", "Kellogs Special Crunchy Oat Granola Mixed Berries 320g",
        {"form": "unspecified"}, "brot-cerealien-aufstriche"
    ) is None, "Sweetened granola is not a safe ingredient substitute for plain rolled oats"
    assert ingredient_product_match_type(
        "bratwurst", "ja! Schweine-Bratwurst grob 4x100g", {}, "fleisch-wurst-fisch"
    ) == "exact"
    assert ingredient_product_match_type(
        "firm tofu", "REWE Bio Tofu Natur 200g", {"form": "firm"}, "fertiggerichte-konserven"
    ) == "exact"
    assert ingredient_product_match_type(
        "lettuce", "REWE Feine Welt Erlesener Blüten Salat 100g", {"form": "fresh"}, "obst-gemuese"
    ) is None
    assert ingredient_product_match_type(
        "lettuce", "Wildkräuter Salat 125g", {"form": "fresh"}, "obst-gemuese"
    ) is None
    assert ingredient_product_match_type(
        "chicken breast", "ja! Delikatess-Hähnchenbrustfilet gepökelt, gebacken 100g",
        {"form": "fresh"}, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "vegetable oil", "Thomy Delikatess-Mayonnaise mit reinem Sonnenblumenöl 100ml",
        {"form": "liquid"}, "oele-sossen-gewuerze"
    ) is None
    assert ingredient_product_match_type(
        "honey", "REWE Beste Wahl Honey Peppers mit Frischkäsecreme 150g",
        {"form": "liquid"}, "fertiggerichte-konserven"
    ) is None
    assert ingredient_product_match_type(
        "pasta", "Birkel Buchstaben-Nudeln 250g", {"form": "dry"}, "kochen-backen"
    ) is None
    assert ingredient_product_match_type(
        "chicken breast", "ja! Hähnchenbrustfilet Paprika 150g",
        {"form": "fresh"}, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "chicken breast", "Wilhelm Brandenburg Hähnchenbrustfilet 100g",
        {"form": "fresh"}, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "chicken breast", "Bernard Matthews Hähnchenbrust-Filetstücke Klassik 150g",
        {"form": "fresh"}, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "chicken breast", "Gutfried Hähnchenbrust Natur 100g",
        {"form": "fresh"}, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "chicken breast", "Herta Finesse Hähnchenbrust mit Curry 100g",
        {"form": "fresh"}, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "chicken breast", "REWE Bio Hähnchen Brustfilet Joghurt Knoblauch 320g",
        {"form": "fresh"}, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "chicken breast", "Wiltmann Bio Hähnchenbrustfilet 50g",
        {"form": "fresh"}, "fleisch-wurst-fisch"
    ) is None
    assert ingredient_product_match_type(
        "vegetable oil", "REWE Beste Wahl Air Fryer Spray Sonnenblumen- & Rapsöl 200ml",
        {"form": "liquid"}, "oele-sossen-gewuerze"
    ) is None
    assert ingredient_product_match_type(
        "lettuce", "Florette Essentials Der Feine Salat 150g",
        {"form": "fresh"}, "obst-gemuese"
    ) is None
    assert ingredient_product_match_type(
        "honey", "Kölln Müsli Knusper Honig-Nuss 500g",
        {"form": "liquid"}, "brot-cerealien-aufstriche"
    ) is None
    assert ingredient_product_match_type(
        "frozen peas", "REWE Erbsen fein 450g", {"form": "frozen"}, "obst-gemuese"
    ) is None, "A frozen ingredient must not match an unmarked fresh product title/category"
    assert ingredient_product_match_type(
        "frozen peas", "REWE Erbsen fein tiefgefroren 450g", {"form": "frozen"}, "tiefkuehlkost"
    ) == "exact"
    assert "speisekartoffeln" in ingredient_candidate_search_terms("frozen french fries", intelligence)
    proposed_only = {"canonical": "custom cooking fat", "suggested_substitutions": ["rapeseed oil"]}
    partial_proposed_profile = {"suggested_substitutions": ["rapeseed oil"]}
    assert "rapeseed oil" in ingredient_candidate_search_terms("custom cooking fat", partial_proposed_profile)
    assert ingredient_product_match_type(
        "custom cooking fat", "REWE Rapsöl 1L", partial_proposed_profile
    ) == "suggested_substitution"

    # Canonical German translations can establish exact identity only when
    # the requested form and supermarket aisle independently agree.
    ground_beef_translation = {
        "name_en": "ground beef", "name_de": "Rinderhackfleisch", "form": "fresh",
    }
    assert ingredient_product_match_type(
        "ground beef", "REWE Bio Rinderhackfleisch 400g",
        ground_beef_translation, "Fleisch"
    ) == "exact"
    curry_powder_translation = {
        "name_en": "curry powder", "name_de": "Currypulver",
        "form": "powder", "aliases": ["curry paste"],
    }
    assert ingredient_product_match_type(
        "curry powder", "REWE Madras Curry Paste 100g",
        curry_powder_translation, "oele-sossen-gewuerze"
    ) == "suggested_substitution"
    assert "rapeseed oil" in ingredient_candidate_search_terms("custom cooking fat", proposed_only)
    assert ingredient_product_match_type("custom cooking fat", "REWE Rapsöl 1L", proposed_only) == "suggested_substitution"
    assert ingredient_suggested_substitution_name("custom cooking fat", "REWE Rapeseed Oil 1L", proposed_only) == "rapeseed oil"
    assert ingredient_suggested_substitution_name("custom cooking fat", "REWE Rapsöl 1L", proposed_only) == "rapeseed oil"

    # General recipe-aware substitutions are data-driven, not hard-coded by
    # ingredient name. Only high-confidence, role-preserving options auto-apply.
    generic_recipe = {
        "id": "generic-oil-test", "name": "Roasted vegetables", "base_servings": 2,
        "ingredients": [["neutral cooking fat", 20, "ml"]],
        "steps": [{"text": "Coat the vegetables with neutral cooking fat and roast."}],
        "ingredient_intelligence": {
            "neutral cooking fat": {
                "canonical": "neutral cooking fat", "name_en": "neutral cooking fat",
                "name_de": "neutrales Speiseöl", "form": "liquid",
                "culinary_role": "high-heat cooking fat",
                "substitution_options": [{
                    "name": "rapeseed oil", "confidence": 0.96,
                    "role_preserved": True, "safe_to_auto_apply": True,
                    "quantity_ratio": 1.0, "reason": "Same neutral high-heat cooking function.",
                    "preparation_adjustment": "",
                }],
            }
        },
    }
    generic_intelligence = normalize_recipe_intelligence(generic_recipe)
    generic_profile = generic_intelligence["neutral cooking fat"]
    assert generic_profile["substitution_options"][0]["safe_to_auto_apply"] is True
    assert ingredient_product_match_type(
        "neutral cooking fat", "REWE Rapsöl 1L", generic_profile, "oele-sossen-gewuerze"
    ) == "substitute"
    assert ingredient_suggested_substitution_name(
        "neutral cooking fat", "REWE Rapsöl 1L", generic_profile
    ) == "rapeseed oil"
    generic_recipe["ingredient_intelligence"] = generic_intelligence
    generic_adaptations = _adapt_recipe_to_catalog(generic_recipe, [{
        "ingredient": "neutral cooking fat", "match_status": "substituted",
        "needed_quantity": 20, "pantry_used": 0,
        "product": {"ingredient_substitute": "rapeseed oil", "name_original": "REWE Rapsöl 1L"},
    }])
    assert generic_recipe["ingredients"] == [["rapeseed oil", 20.0, "ml"]]
    assert generic_recipe["adaptations"][0]["replacement"] == "rapeseed oil"

    # Basket package counts must use the replacement ratio, not the original
    # ingredient quantity; otherwise the adapted recipe can require more than
    # the shopping basket actually buys.
    # Malformed model confidence is untrusted metadata: it must downgrade
    # the option to review-only rather than crash the shopping request.
    for malformed_confidence in ("not-a-number", "NaN", "Infinity", -1, 2, True):
        malformed_profile = {
            "canonical": "custom cooking fat", "form": "liquid",
            "substitution_options": [{
                "name": "Rapsöl", "confidence": malformed_confidence,
                "role_preserved": True, "safe_to_auto_apply": True,
            }],
        }
        assert ingredient_product_match_type(
            "custom cooking fat", "REWE Rapsöl 1L", malformed_profile
        ) == "suggested_substitution", (
            f"Malformed confidence {malformed_confidence!r} must remain review-only"
        )

    # The normalizer must not turn NaN/Infinity into confidence=1.0
    # through min/max clamping. Test the complete untrusted-metadata path.
    for malformed_confidence in ("not-a-number", "NaN", "Infinity", float("nan"), float("inf"), -1, 2, True):
        normalized_profile = normalize_recipe_intelligence({
            "ingredients": [["custom cooking fat", 20, "ml"]],
            "ingredient_intelligence": {
                "custom cooking fat": {
                    "canonical": "custom cooking fat", "form": "liquid",
                    "substitution_options": [{
                        "name": "Rapsöl", "confidence": malformed_confidence,
                        "role_preserved": True, "safe_to_auto_apply": True,
                    }],
                },
            },
        })["custom cooking fat"]
        assert normalized_profile["substitution_options"][0]["confidence"] == 0.0
        assert ingredient_product_match_type(
            "custom cooking fat", "REWE Rapsöl 1L", normalized_profile
        ) == "suggested_substitution", (
            f"Normalized malformed confidence {malformed_confidence!r} must remain review-only"
        )

    # Explicit malformed quantity ratios must be discarded, not silently
    # converted to a 1:1 substitution by truthiness/default handling.
    for malformed_ratio in ("", "not-a-number", "NaN", "Infinity", float("nan"), float("inf"), 0, -1, 6, True, False):
        normalized_profile = normalize_recipe_intelligence({
            "ingredients": [["custom cooking fat", 20, "ml"]],
            "ingredient_intelligence": {
                "custom cooking fat": {
                    "canonical": "custom cooking fat", "form": "liquid",
                    "substitution_options": [{
                        "name": "rapeseed oil", "quantity_ratio": malformed_ratio,
                        "confidence": 0.99, "role_preserved": True,
                        "safe_to_auto_apply": True,
                    }],
                },
            },
        })["custom cooking fat"]
        assert normalized_profile["substitution_options"] == [], (
            f"Malformed quantity ratio {malformed_ratio!r} must be discarded"
        )

    ratio_profile = {
        "canonical": "custom cooking fat", "form": "liquid",
        "substitution_options": [{
            "name": "rapeseed oil", "confidence": 0.96,
            "role_preserved": True, "safe_to_auto_apply": True,
            "quantity_ratio": 1.5,
        }],
    }
    ratio_catalog = IntelligenceCatalog({"custom cooking fat": [{
        "id": 21, "name_original": "REWE Rapsöl 10ml",
        "package_size": 10, "package_unit": "ml", "price": 1.0,
        "availability": "available", "ingredient_match_type": "substitute",
        "ingredient_substitute": "rapeseed oil",
    }]})
    ratio_basket = build_basket([{
        "ingredient": "custom cooking fat", "quantity": 20, "unit": "ml",
        "source_meals": ["Ratio test"], "ingredient_intelligence": ratio_profile,
        "unit_validation": {"valid": True},
    }], ratio_catalog)
    assert ratio_basket[0]["quantity_ratio"] == 1.5
    assert ratio_basket[0]["product_needed_quantity"] == 30
    assert ratio_basket[0]["packs"] == 3

    ratio_recipe = {
        "base_servings": 2,
        "ingredients": [["custom cooking fat", 20, "ml"]],
        "ingredient_intelligence": {"custom cooking fat": ratio_profile},
        "steps": [{"text": "Add custom cooking fat."}],
    }
    _adapt_recipe_to_catalog(ratio_recipe, ratio_basket)
    assert ratio_recipe["ingredients"] == [["rapeseed oil", 30.0, "ml"]]

    # Recipe metadata may be keyed with punctuation and the selected product
    # may carry a German alias. Adaptation must still apply the declared ratio
    # and persist the canonical replacement name.
    german_alias_recipe = {
        "base_servings": 2,
        "ingredients": [["custom cooking fat", 20, "ml"]],
        "ingredient_intelligence": {
            "custom-cooking-fat": {
                "substitution_options": [{
                    "name": "rapeseed oil", "name_de": "Rapsöl",
                    "aliases": ["Rapsöl kaltgepresst"],
                    "quantity_ratio": 1.5,
                }],
            },
        },
        "steps": [{"text": "Add custom cooking fat."}],
    }
    _adapt_recipe_to_catalog(german_alias_recipe, [{
        "ingredient": "custom cooking fat", "match_status": "substituted",
        "needed_quantity": 20, "pantry_used": 0,
        "product": {"ingredient_substitute": "Rapsöl", "name_original": "REWE Rapsöl 10ml"},
    }])
    assert german_alias_recipe["ingredients"] == [["rapeseed oil", 30.0, "ml"]]

    # The same end-to-end ratio must be applied only to the amount not already
    # covered by pantry stock, while preserving the original pantry ingredient.
    pantry_ratio_basket = build_basket([{
        "ingredient": "custom cooking fat", "quantity": 20, "unit": "ml",
        "source_meals": ["Pantry ratio test"], "ingredient_intelligence": ratio_profile,
        "unit_validation": {"valid": True},
    }], ratio_catalog, pantry={"custom cooking fat": {"quantity": 5, "unit": "ml"}})
    assert pantry_ratio_basket[0]["needed_quantity"] == 15
    assert pantry_ratio_basket[0]["product_needed_quantity"] == 22.5
    pantry_ratio_recipe = {
        "base_servings": 2,
        "ingredients": [["custom cooking fat", 20, "ml"]],
        "ingredient_intelligence": {"custom cooking fat": ratio_profile},
        "steps": [{"text": "Add custom cooking fat."}],
    }
    _adapt_recipe_to_catalog(pantry_ratio_recipe, pantry_ratio_basket)
    assert pantry_ratio_recipe["ingredients"] == [
        ["custom cooking fat", 5.0, "ml"], ["rapeseed oil", 22.5, "ml"]
    ]

    # A structured cross-form transformation may replace a frozen component
    # with a raw ingredient only when it supplies the missing preparation step.
    fries_recipe = {
        "id": "generic-fries-transform", "name": "Fries", "base_servings": 2,
        "ingredients": [["frozen fries", 500, "g"]],
        "steps": [{"text": "Cook the frozen fries until crisp."}],
        "ingredient_intelligence": {
            "frozen fries": {
                "canonical": "frozen fries", "form": "frozen",
                "culinary_role": "crispy potato side",
                "substitution_options": [{
                    "name": "fresh potatoes", "name_de": "Speisekartoffeln",
                    "aliases": ["Kartoffeln frisch"], "confidence": 0.97,
                    "role_preserved": True, "safe_to_auto_apply": True,
                    "quantity_ratio": 1.0,
                    "preparation_adjustment": "Cut fresh potatoes into fries, rinse and dry thoroughly, coat lightly with oil, then cook until crisp.",
                    "reason": "Fresh potatoes can be transformed into fries.",
                }],
            }
        },
    }
    fries_profile = normalize_recipe_intelligence(fries_recipe)["frozen fries"]
    assert "speisekartoffeln" in ingredient_candidate_search_terms("frozen fries", fries_profile)
    assert ingredient_product_match_type(
        "frozen fries", "REWE Speisekartoffeln 2kg", fries_profile, "obst-gemuese"
    ) == "substitute"
    fries_recipe["ingredient_intelligence"] = {"frozen fries": fries_profile}
    _adapt_recipe_to_catalog(fries_recipe, [{
        "ingredient": "frozen fries", "match_status": "substituted",
        "needed_quantity": 500, "pantry_used": 0,
        "product": {"ingredient_substitute": "fresh potatoes", "name_original": "REWE Speisekartoffeln 2kg"},
    }])
    assert fries_recipe["ingredients"] == [["fresh potatoes", 500.0, "g"]]
    assert "Cut fresh potatoes into fries" in fries_recipe["steps"][0]["text"]

    unsafe_profile = {
        "form": "liquid",
        "substitution_options": [{
            "name": "peanut butter", "confidence": 0.99,
            "role_preserved": False, "safe_to_auto_apply": False,
        }],
    }
    assert ingredient_product_match_type(
        "neutral cooking fat", "Peanut butter creamy", unsafe_profile
    ) == "suggested_substitution"
    assert ingredient_product_match_type("canned corn", "REWE Mais aus der Dose 300g", intelligence) == "exact"
    assert ingredient_product_match_type(
        "canned corn", "REWE Bio Zuckermais Tiefkühl 450g", intelligence
    ) is None, "Canned corn must not match frozen corn"
    # Department/category guard: matching a word inside an unrelated prepared product is not a match.
    fresh_pepper = {"form": "fresh", "name_de": "Paprika", "aliases": ["Paprika"]}
    assert ingredient_product_match_type("bell pepper", "REWE Beste Wahl Lyoner Paprika vegan 100g", fresh_pepper, "fleisch-wurst-fisch") is None
    assert ingredient_product_match_type("red onion", "Kettle Chips Cheddar Cheese & Red Onion 130g", {"form": "fresh", "name_de": "rote Zwiebel"}, "suesses-salziges") is None
    assert ingredient_product_match_type("rice", "Freche Freunde Bio Quetschie Apfel, Birne mit Zimt, Reis & Dinkel 100g", {}, "baby-kind") is None
    assert ingredient_product_match_type("rice", "REWE Beste Wahl Langkornreis 500g", {"name_de": "Reis", "aliases": ["Langkornreis"], "form": "dry"}, "Rice") == "exact"
    assert ingredient_product_match_type("olive oil", "Oliva Nachtcreme mit Olivenöl 50ml", {"form": "liquid"}, "drogerie-gesundheit") is None
    assert ingredient_product_match_type("lime", "duschdas Duschgel Limette Minze 450ml", {"form": "fresh"}, "drogerie-gesundheit") is None
    assert ingredient_product_match_type("chicken breast", "Original Wagner Rustipani Helles Ofenbrot Hähnchenbrust 180g", {"form": "fresh"}, "tiefkuehlkost") is None
    assert ingredient_product_match_type("tomatoes", "Alnatura Bio Passierte Tomaten 500g", {"form": "fresh"}, "fertiggerichte-konserven") is None
    assert ingredient_product_match_type("feta cheese", "Maggi Querbeet Ofen-Gemüse mit Feta 27g", {}, "fertiggerichte-konserven") is None
    assert ingredient_product_match_type(
        "frozen french fries", "REWE Pommes Frites 750g", intelligence, "tiefkuehlkost"
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
    # Direct unit validation accepts the same natural-language aliases
    # that the basket consolidator already normalizes.
    assert validate_ingredient_unit("curry powder", "tablespoon")["valid"] is True
    assert validate_ingredient_unit("curry powder", "teaspoons")["valid"] is True
    assert validate_ingredient_unit("garlic", "clove")["valid"] is True
    assert validate_ingredient_unit("eggs", "pcs")["valid"] is True
    assert validate_ingredient_unit("vegetable oil", "tablespoons")["valid"] is True
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
    fresh_herb = {"fresh cilantro": {"canonical": "fresh cilantro", "name_de": "Frischer Koriander", "form": "fresh", "aliases": ["Koriander"]}}
    assert ingredient_product_match_type("fresh cilantro", "Koriander", fresh_herb, "Gewürze") is None
    assert ingredient_product_match_type("fresh cilantro", "Koriander", fresh_herb, "Frische Kräuter") == "exact"
    garlic_profile = {"garlic": {"canonical": "garlic", "name_de": "Knoblauch", "form": "whole", "aliases": ["Knoblauch"]}}
    assert ingredient_product_match_type("garlic", "REWE Bio Hähnchen Brustfilet Joghurt Knoblauch 320g", garlic_profile, "Fleisch") is None
    assert ingredient_product_match_type("garlic", "Knoblauch 1 Stück", garlic_profile, "obst-gemuese") == "exact"
    cooked_chicken = {"pre-cooked shredded chicken": {"canonical": "cooked chicken", "form": "pre_cooked", "aliases": ["Hähnchenbrust"]}}
    assert ingredient_product_match_type("pre-cooked shredded chicken", "REWE Hähnchenbrust 400g", cooked_chicken, "Fleisch") is None
    assert ingredient_product_match_type("pre-cooked shredded chicken", "REWE Hähnchenbrust gegart 300g", cooked_chicken, "Fleisch") == "exact"

    # Regression guards for known false positives from the real REWE benchmark.
    assert ingredient_product_match_type(
        "butter", "BE-KIND Protein Crunchy Peanut Butter 50g", {}, "kaese-eier-molkerei"
    ) is None
    assert ingredient_product_match_type(
        "honey", "REWE Honig-Senfsauce 60g", {}, "oele-sossen-gewuerze"
    ) is None
    assert ingredient_product_match_type(
        "pasta", "REWE Beste Wahl Udon-Nudeln vorgekocht 200g", {}, "kochen-backen"
    ) is None
    assert ingredient_product_match_type(
        "white fish fillet", "Nadler Alaska Seelachs Mus 125g", {}, "fleisch-wurst-fisch"
    ) is None

    assert ingredient_product_match_type(
        "burger buns", "Coppenrath & Wiese 20 Weizen-Brötchen 1kg",
        {"form": "unspecified"}, "brot-cerealien-aufstriche"
    ) == "substitute"
    assert ingredient_substitution_name(
        "burger buns", "Coppenrath & Wiese 20 Weizen-Brötchen 1kg"
    ) == "bread rolls"

    # Real-catalog audit: flavored milk, herb-seasoned sour cream, gnocchi,
    # branded ready rice and walnut croutons are not exact ingredient matches.
    assert ingredient_product_match_type(
        "milk", "Ehrmann Milk Twist Choco 400ml", {"form": "liquid"}, "kaese-eier-molkerei"
    ) is None
    assert ingredient_product_match_type(
        "sour cream", "Milram Sour Cream mit Frühlingskräutern 185g",
        {"form": "unspecified"}, "kaese-eier-molkerei"
    ) is None
    assert ingredient_product_match_type(
        "pasta", "Delverde Gnocchi Pasta 500g", {"form": "dried"}, "kochen-backen"
    ) is None
    assert ingredient_product_match_type(
        "rice", "reis-fit Griechischer Reis 250g", {"form": "unspecified"}, "kochen-backen"
    ) is None
    assert ingredient_product_match_type(
        "croutons", "Knorr Salatkrönung Croutinos mit Walnuss Croutons 25g",
        {}, "oele-sossen-gewuerze"
    ) is None
    assert ingredient_product_match_type(
        "bell pepper", "REWE Paprika rot 1 Stück", {"form": "fresh", "name_de": "Paprika"}, "obst-gemuese"
    ) == "exact"
    assert validate_ingredient_unit("bell pepper", "piece")["valid"] is True
    assert validate_ingredient_unit("bell pepper", "piece")["family"] == "produce"
    assert ingredient_product_match_type(
        "vegetable oil", "REWE Rapsöl 1L",
        {"name_de": "Pflanzenöl", "aliases": ["Rapsöl", "Sonnenblumenöl"], "form": "liquid"},
        "oele-sossen-gewuerze",
    ) == "substitute", "Curated oil equivalents must never be silently upgraded to exact matches"

    assert ingredient_product_match_type(
        "lettuce", "REWE Bio Salat Crispy Mix 100g", {}, "obst-gemuese"
    ) is None
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

    adapted_recipe = {
        "ingredients": [["frozen french fries", 300, "g"]],
        "ingredient_intelligence": intelligence,
        "steps": [{"text": "Add frozen french fries to the basket."}],
    }
    _adapt_recipe_to_catalog(adapted_recipe, potato_confirmed)
    assert adapted_recipe["ingredients"][0][0] == "fresh potatoes"
    assert any("Fresh potatoes need longer than frozen fries" in step["text"] for step in adapted_recipe["steps"])

    # A 100g lettuce portion must be purchasable from a REWE pack sold by count.
    lettuce_conversion, lettuce_note = _convert_ingredient_quantity(100, "g", "piece", "lettuce")
    assert lettuce_conversion == 0.4
    assert "250 g per piece" in lettuce_note
    lettuce_catalog = IntelligenceCatalog({"lettuce": [{
        "id": 16, "name_original": "REWE Beste Wahl Romana Salatherzen 3 Stück",
        "package_size": 3, "package_unit": "piece", "price": 1.99,
        "availability": "unknown", "ingredient_match_type": "exact",
    }]})
    lettuce_basket = build_basket([{
        "ingredient": "lettuce", "quantity": 100, "unit": "g",
        "source_meals": ["Lettuce conversion"], "unit_validation": {"valid": True},
    }], lettuce_catalog)
    assert lettuce_basket[0]["match_status"] == "matched"
    assert lettuce_basket[0]["packs"] == 1

    print("INGREDIENT INTELLIGENCE QA PASS: cached multilingual intent, form-aware matching, safe substitutions, and unit validation")


if __name__ == "__main__":
    run()
