"""Measure real REWE snapshot coverage, missing prices and stale product data.

Run from backend/: python qa_catalog_coverage.py
This is a diagnostic report: it deliberately reports gaps instead of pretending that
an ingredient is purchasable when the catalog has no priced, usable product.
"""
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-catalog-coverage-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "coverage.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

from app import server
from app.database import Product, SessionLocal
from app.ai.gemini_efficient import _catalog_context


SAMPLE_INGREDIENTS = [
    "pasta", "spaghetti", "trofie pasta", "fresh basil pesto", "pine nuts",
    "parmesan", "salt", "garlic", "onion", "tomato", "cherry tomato",
    "chicken breast", "ground beef", "salmon", "rice", "flour", "egg",
    "milk", "butter", "heavy cream", "greek yogurt", "mozzarella", "feta",
    "potato", "broccoli", "spinach", "mushroom", "bell pepper", "zucchini",
    "cucumber", "avocado", "lemon", "olive oil", "soy sauce", "tomato paste",
    "chickpeas", "lentils", "kidney beans", "tortilla", "bread", "oats",
    "banana", "strawberry", "honey", "sugar", "baking powder", "cornstarch",
    "coconut milk", "tofu", "shrimp", "tuna", "bacon", "turkey",
]


def main():
    db = SessionLocal()
    try:
        query = db.query(Product).filter(Product.supermarket == "REWE")
        products = query.all()
        total = len(products)
        assert total >= 1000, f"REWE snapshot unexpectedly small: {total}"

        missing_price = sum(row.price is None or float(row.price) <= 0 for row in products)
        availability = Counter(str(row.availability or "unknown").lower() for row in products)
        categories = Counter(str(row.category or "uncategorized") for row in products)
        ingredients = Counter(str(row.ingredient or "unclassified") for row in products)
        names = Counter(str(row.name_normalized or row.name_original or "").strip().lower() for row in products)
        duplicate_name_rows = sum(count - 1 for count in names.values() if count > 1)
        with_product_url = sum(bool(str(row.product_url or "").strip()) for row in products)
        with_image_url = sum(bool(str(row.image_url or "").strip()) for row in products)
        invalid_packages = sum(
            row.package_size is None or float(row.package_size) <= 0 or not row.package_unit
            for row in products
        )
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        stale = sum(row.last_checked_at is None or row.last_checked_at < cutoff for row in products)

        # The generation prompt must see only a compact set of ingredient keys
        # backed by real, title-validated products from this committed REWE snapshot.
        generation_context = _catalog_context("salmon rice bowl", limit=90)
        context_ingredients = [x.strip() for x in generation_context.split(",") if x.strip()]
        assert len(context_ingredients) <= 90, "Generation context exceeded its ingredient cap"
        assert len(generation_context) < 3000, "Generation context is not compact enough"
        print(f"Catalog-aware Gemini context: {len(context_ingredients)} canonical ingredients / {len(generation_context)} chars")
        print("Catalog-aware ingredient keys:", generation_context)

        adapter = server.main_module.CatalogAdapter(db)
        coverage = []
        for ingredient in SAMPLE_INGREDIENTS:
            candidates = adapter.search(ingredient) or []
            exact = [p for p in candidates if p.get("ingredient_match_type") == "exact"]
            substitutes = [p for p in candidates if p.get("ingredient_match_type") == "substitute"]
            usable = [
                p for p in candidates
                if p.get("price") is not None
                and float(p.get("price") or 0) > 0
                and str(p.get("availability") or "").lower()
                    not in {"unavailable", "out_of_stock", "not_available", "discontinued"}
            ]
            coverage.append({
                "ingredient": ingredient,
                "exact": len(exact),
                "substitutes": len(substitutes),
                "priced_usable": len(usable),
                "status": "exact" if exact and usable else (
                    "substitute" if substitutes and usable else "gap"
                ),
            })

        counts = Counter(row["status"] for row in coverage)
        print(f"REWE products: {total}")
        print(f"Distinct ingredient labels: {len(ingredients)}")
        print(f"Distinct categories: {len(categories)}")
        print(f"Missing/zero prices: {missing_price} ({missing_price / total:.1%})")
        for row in products:
            if row.price is None or float(row.price) <= 0:
                print("PRODUCT WITHOUT PRICE:", {
                    "id": row.id,
                    "name": row.name_original,
                    "ingredient": row.ingredient,
                    "package_size": row.package_size,
                    "package_unit": row.package_unit,
                })
        print(f"Stale or never checked (>30 days): {stale} ({stale / total:.1%})")
        print(f"Duplicate normalized-name rows: {duplicate_name_rows}")
        print(f"Products with REWE product URL: {with_product_url} ({with_product_url / total:.1%})")
        print(f"Products with image URL: {with_image_url} ({with_image_url / total:.1%})")
        print(f"Invalid package sizes/units: {invalid_packages}")
        print(f"Availability distribution: {dict(availability)}")
        print(f"Sample coverage ({len(coverage)} common ingredients): {dict(counts)}")
        for row in coverage:
            if row["status"] == "gap":
                print("CATALOG GAP:", row)
                hint_terms = {
                    "cherry tomato": ("tomat", "cocktail", "kirsche"),
                    "greek yogurt": ("joghurt", "yoghurt", "skyr", "quark"),
                }.get(row["ingredient"], tuple(row["ingredient"].split()))
                suggestions = [
                    product.name_original
                    for product in products
                    if any(term in str(product.name_original or "").lower() for term in hint_terms)
                ][:20]
                print("CATALOG NEAR-MATCH TITLES:", row["ingredient"], suggestions)
    finally:
        db.close()


if __name__ == "__main__":
    main()
