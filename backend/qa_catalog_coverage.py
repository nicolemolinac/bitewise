"""Measure real REWE snapshot coverage, missing prices and stale product data.

Run from backend/: python qa_catalog_coverage.py
This is a diagnostic report: it deliberately reports gaps instead of pretending that
an ingredient is purchasable when the catalog has no priced, usable product.
"""
import math
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

from types import SimpleNamespace

from app import server
from app.database import Product, SessionLocal


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
    priced = SimpleNamespace(
        ingredient="rice", translated_name=None, name_normalized="rice 500g",
        name_original="Rice 500g", price=1.99, availability="unknown",
    )
    invalid = SimpleNamespace(
        ingredient="rice", translated_name=None, name_normalized="rice 500g",
        name_original="Rice 500g", price=float("nan"), availability="unknown",
    )
    assert server._catalog_search_score(priced, {"rice"}, "exact") > server._catalog_search_score(invalid, {"rice"}, "exact")

    db = SessionLocal()
    try:
        query = db.query(Product).filter(Product.supermarket == "REWE")
        products = query.all()
        total = len(products)
        assert total >= 11000, (
            f"REWE catalog is incomplete: expected the full ~12k snapshot, got {total} products"
        )

        missing_price = sum(row.price is None for row in products)
        invalid_price = sum(
            row.price is not None and (
                not math.isfinite(float(row.price)) or float(row.price) <= 0
            )
            for row in products
        )
        availability = Counter(str(row.availability or "unknown").lower() for row in products)
        categories = Counter(str(row.category or "uncategorized") for row in products)
        ingredients = Counter(str(row.ingredient or "unclassified") for row in products)
        names = Counter(str(row.name_normalized or row.name_original or "").strip().lower() for row in products)
        duplicate_name_rows = sum(count - 1 for count in names.values() if count > 1)
        with_product_url = sum(bool(str(row.product_url or "").strip()) for row in products)
        with_image_url = sum(bool(str(row.image_url or "").strip()) for row in products)
        invalid_packages = sum(
            row.package_size is None
            or not math.isfinite(float(row.package_size))
            or float(row.package_size) <= 0
            or not str(row.package_unit or "").strip()
            for row in products
        )
        unknown_package_units = sum(
            str(row.package_unit or "").strip().lower() == "unknown"
            for row in products
        )
        inconsistent_unit_prices = []
        for row in products:
            try:
                pack_price = float(row.price) if row.price is not None else None
                pack_size = float(row.package_size) if row.package_size is not None else None
                observed_unit_price = float(row.price_per_unit) if row.price_per_unit is not None else None
            except (TypeError, ValueError):
                continue
            if (
                pack_price is None or pack_size is None or observed_unit_price is None
                or not all(math.isfinite(value) for value in (pack_price, pack_size, observed_unit_price))
                or pack_price <= 0 or pack_size <= 0 or observed_unit_price <= 0
            ):
                continue
            expected_unit_price = pack_price / pack_size
            relative_error = abs(observed_unit_price - expected_unit_price) / expected_unit_price
            if relative_error > 0.15:
                inconsistent_unit_prices.append({
                    "id": row.id, "name": row.name_original, "package_size": row.package_size,
                    "package_unit": row.package_unit, "price": row.price,
                    "stored_price_per_unit": row.price_per_unit,
                    "expected_price_per_unit": round(expected_unit_price, 8),
                    "relative_error": round(relative_error, 3),
                })
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        stale = sum(row.last_checked_at is None or row.last_checked_at < cutoff for row in products)

        adapter = server.main_module.CatalogAdapter(db)
        coverage = []
        for ingredient in SAMPLE_INGREDIENTS:
            candidates = adapter.search(ingredient) or []
            exact = [p for p in candidates if p.get("ingredient_match_type") == "exact"]
            substitutes = [p for p in candidates if p.get("ingredient_match_type") == "substitute"]
            usable = [
                p for p in candidates
                if p.get("price") is not None
                and math.isfinite(float(p.get("price")))
                and float(p.get("price")) > 0
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
        print(f"Missing prices (not necessarily source errors): {missing_price} ({missing_price / total:.1%})")
        print(f"Invalid numeric prices (non-finite or <= 0): {invalid_price} ({invalid_price / total:.1%})")
        for row in products:
            if row.price is None or not math.isfinite(float(row.price)) or float(row.price) <= 0:
                print("PRODUCT WITHOUT PRICE:", {
                    "id": row.id,
                    "name": row.name_original,
                    "ingredient": row.ingredient,
                    "package_size": row.package_size,
                    "package_unit": row.package_unit,
                    "price": row.price,
                    "last_price": row.last_price,
                    "product_url": row.product_url,
                })
        print(f"Stale or never checked (>30 days): {stale} ({stale / total:.1%})")
        print(f"Duplicate normalized-name rows: {duplicate_name_rows}")
        print(f"Products with REWE product URL: {with_product_url} ({with_product_url / total:.1%})")
        print(f"Products with image URL: {with_image_url} ({with_image_url / total:.1%})")
        print(f"Invalid package sizes/units: {invalid_packages}")
        print(f"Package size not parsed by source extractor: {unknown_package_units} (not automatically a REWE data error)")
        print(f"Price/unit inconsistencies (>15%): {len(inconsistent_unit_prices)}")
        for row in inconsistent_unit_prices[:30]:
            print("PRICE/UNIT MISMATCH:", row)
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
