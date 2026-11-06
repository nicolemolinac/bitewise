"""QA for catalog-aware recipe expansion using an isolated REWE database.

Run from backend/: python qa_catalog_aware_generation.py
No live catalog, scraper, image process, or user database is touched.
"""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-catalog-aware-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "catalog.sqlite")
os.environ["BITEWISE_AI_MEALS_PATH"] = str(Path(_TEMP.name) / "ai_meals.json")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "false"

from app.database import Product, SessionLocal
from app.ai.gemini_efficient import GeminiService, _catalog_context
from app.ingredient_aliases import canonical_ingredient_terms, ingredient_product_match_type


def seed_catalog():
    db = SessionLocal()
    try:
        db.add_all([
            Product(
                supermarket="REWE", external_id="qa-salmon-1", ingredient="salmon",
                name_original="REWE Norwegisches Lachsfilet", name_normalized="norwegisches lachsfilet",
                package_size=300, package_unit="g", price=6.99, availability="available",
            ),
            Product(
                supermarket="REWE", external_id="qa-salmon-2", ingredient="salmon",
                name_original="REWE Bio Lachs", name_normalized="rewe bio lachs",
                package_size=200, package_unit="g", price=5.49, availability="unknown",
            ),
            Product(
                supermarket="REWE", external_id="qa-rice-1", ingredient="rice",
                name_original="REWE Langkorn Reis", name_normalized="langkorn reis",
                package_size=1000, package_unit="g", price=1.79, availability="available",
            ),
            Product(
                supermarket="REWE", external_id="qa-tofu-1", ingredient="tofu",
                name_original="REWE Tofu", name_normalized="tofu",
                package_size=200, package_unit="g", price=1.49, availability="unavailable",
            ),
            Product(
                supermarket="REWE", external_id="qa-chicken-1", ingredient="chicken breast",
                name_original="REWE Hähnchenbrust", name_normalized="haehnchenbrust",
                package_size=400, package_unit="g", price=None, availability="available",
            ),
            Product(
                supermarket="REWE", external_id="qa-false-positive-1", ingredient="chicken",
                name_original="Vegetable Stock", name_normalized="vegetable stock",
                package_size=1, package_unit="unit", price=1.29, availability="available",
            ),
            Product(
                supermarket="REWE", external_id="qa-passata-1", ingredient="passata",
                name_original="REWE Bio Passata 700 g", name_normalized="rewe bio passata",
                category="fertiggerichte-konserven", package_size=700, package_unit="g",
                price=1.59, availability="available",
            ),
            Product(
                supermarket="REWE", external_id="qa-ready-meal-1", ingredient="shrimp",
                name_original="REWE Garnelen Curry Fertiggericht 400 g",
                name_normalized="rewe garnelen curry fertiggericht",
                category="fertiggerichte-konserven", package_size=400, package_unit="g",
                price=3.99, availability="available",
            ),
        ])
        db.commit()
    finally:
        db.close()


def main():
    seed_catalog()

    # Imported Product.ingredient values may be full SKU names, so AI context
    # must derive short canonical terms from the actual title instead.
    assert canonical_ingredient_terms("REWE Bio Passata 700 g") == ["tomato passata"]
    assert canonical_ingredient_terms("00 Null Null WC Aktivgel 750 ml") == []
    assert "pasta" in canonical_ingredient_terms("3 Glocken Die Mag Ich Fadennudeln 250 g")

    # German REWE titles frequently combine ingredient words into one compound.
    assert ingredient_product_match_type("salmon", "REWE Norwegisches Lachsfilet") == "exact"
    assert ingredient_product_match_type("chicken breast", "Hähnchenbrustfilet") == "exact"
    assert ingredient_product_match_type("tomato", "Rispentomaten") == "exact"

    # The helper reads the complete local catalog but returns only distinct,
    # title-validated, positively priced canonical ingredient names.
    context = _catalog_context("salmon rice bowl", limit=10)
    assert "salmon" in context
    assert "rice" in context
    assert "tofu" not in context, "Explicitly unavailable products must not qualify"
    assert "chicken breast" not in context, "Products without a positive price must not qualify"
    assert "chicken" not in context, "A broad/misclassified label must pass title validation"
    assert "Norwegisches" not in context and "6.99" not in context, (
        "Gemini receives compact ingredient labels, not SKU titles or product prices"
    )
    assert "passata" in context
    assert "shrimp" not in context, "A complete ready meal must not be exposed as a recipe ingredient"
    assert len(context.split(", ")) == 3, "Duplicate product rows must collapse to canonical ingredients"

    ingredient_context, convenience_context = _catalog_context(
        "salmon rice bowl", limit=10, include_intelligence=True
    )
    assert ingredient_context == context
    assert "prepared components: passata" in convenience_context
    assert "complete ready meals: shrimp" in convenience_context

    service = object.__new__(GeminiService)
    service.key = "qa-key"
    service.client = object()
    generated = [{
        "id": "qa-catalog-salmon",
        "name": "Salmon rice bowl",
        "description": "Salmon with rice and cucumber",
        "time": 20,
        "difficulty": "Easy",
        "cost": 4.0,
        "calories": 520,
        "meal_type": "lunch",
        "cuisine": "Asian",
        "tags": ["Quick"],
        "ingredients": [["salmon", 150, "g"], ["rice", 75, "g"]],
        "steps": [{"text": "Cook rice and salmon.", "minutes": 15}],
        "image": "",
    }]
    with patch("app.ai.gemini_efficient._pantry_context", return_value=["rice (500 g)"]), patch(
        "app.ai.gemini_efficient._catalog_context", return_value=("salmon, rice, cucumber", "prepared components: pesto")
    ), patch.object(
        service, "_generate_once",
        return_value=(SimpleNamespace(text=json.dumps(generated)), "qa-model"),
    ) as generate:
        recipe = service.expand_concept(
            {"id": "concept-qa", "name": "Salmon rice bowl", "description": "Simple salmon lunch"},
            "lunch with salmon",
            ["air fryer", "microwave"],
        )

    instruction = generate.call_args.args[0]
    assert generate.call_count == 1, "Catalog awareness must not add a second Gemini call"
    assert "REWE CATALOG INGREDIENTS: salmon, rice, cucumber" in instruction
    assert "REWE PRODUCT INTELLIGENCE CONVENIENCE SIGNALS: prepared components: pesto" in instruction
    assert "complete ready meals as optional no-cook alternatives" in instruction
    assert "Prefer suitable core ingredients from the REWE catalog list" in instruction
    assert "Pantry ingredients may be used even when they are not in the REWE list" in instruction
    assert "Do not force a bad substitution" in instruction
    assert "rice (500 g)" in instruction
    assert recipe["name"] == "Salmon rice bowl"

    print(
        "Catalog-aware generation QA PASS: real-title validation, price/availability "
        "filtering, canonical deduplication, compact prompt context, pantry allowance, "
        "and exactly one Gemini call"
    )


if __name__ == "__main__":
    main()
