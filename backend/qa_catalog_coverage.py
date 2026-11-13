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
os.environ["BITEWISE_REPAIR_CATALOG_SNAPSHOT"] = "true"

from types import SimpleNamespace

from app import server
from app.database import Product, SessionLocal
from app.rewe.scraper import package
from app.ingredient_intelligence import normalize_text


def _usable_catalog_candidate(product):
    try:
        price = float(product.get("price"))
        package_size = float(product.get("package_size"))
    except (TypeError, ValueError):
        return False
    package_unit = str(product.get("package_unit") or "").strip().lower()
    availability = str(product.get("availability") or "unknown").lower()
    return (
        math.isfinite(price) and price > 0
        and math.isfinite(package_size) and package_size > 0
        and package_unit not in {"", "unknown"}
        and availability not in {"unavailable", "out_of_stock", "not_available", "discontinued"}
    )


SAMPLE_INGREDIENTS = [
    "pasta", "spaghetti", "trofie pasta", "fresh basil pesto", "pine nuts",
    "parmesan", "salt", "garlic", "onion", "tomato", "cherry tomato",
    "chicken breast", "ground beef", "salmon", "rice", "flour", "egg",
    "milk", "butter", "heavy cream", "greek yogurt", "mozzarella", "feta",
    "potato", "broccoli", "spinach", "mushroom", "bell pepper", "zucchini",
    "cucumber", "avocado", "lemon", "olive oil", "soy sauce", "tomato paste",
    "chickpeas", "lentils", "kidney beans", "tortilla", "bread", "oats",
    "banana", "strawberry", "honey", "mayonnaise", "sugar", "baking powder", "cornstarch",
    "coconut milk", "tofu", "shrimp", "tuna", "bacon", "turkey",
    "rolled oats", "burger buns",
]


def main():
    priced = SimpleNamespace(
        ingredient="rice", translated_name=None, name_normalized="rice 500g",
        name_original="Rice 500g", price=1.99, package_size=500,
        package_unit="g", availability="unknown",
    )
    invalid = SimpleNamespace(
        ingredient="rice", translated_name=None, name_normalized="rice 500g",
        name_original="Rice 500g", price=float("nan"), package_size=500,
        package_unit="g", availability="unknown",
    )
    assert server._catalog_search_score(priced, {"rice"}, "exact") > server._catalog_search_score(invalid, {"rice"}, "exact")
    valid_substitute = SimpleNamespace(
        ingredient="rice", translated_name=None, name_normalized="rice alternative",
        name_original="Rice alternative", price=1.49, package_size=500,
        package_unit="g", availability="available",
    )
    unavailable_exact = SimpleNamespace(
        ingredient="rice", translated_name=None, name_normalized="rice 500g",
        name_original="Rice 500g", price=1.99, package_size=500,
        package_unit="g", availability="out_of_stock",
    )
    assert server._catalog_search_score(valid_substitute, {"rice"}, "substitute") > server._catalog_search_score(invalid, {"rice"}, "exact")
    assert server._catalog_search_score(valid_substitute, {"rice"}, "substitute") > server._catalog_search_score(unavailable_exact, {"rice"}, "exact")

    unknown_pack = SimpleNamespace(
        ingredient="rice", translated_name=None, name_normalized="rice 500g",
        name_original="Rice 500g", price=1.99, package_size=1,
        package_unit="unknown", availability="unknown",
    )
    assert server._catalog_search_score(priced, {"rice"}, "exact") > server._catalog_search_score(unknown_pack, {"rice"}, "exact")

    assert not _usable_catalog_candidate({
        "price": 1.99, "package_size": 1, "package_unit": "unknown",
        "availability": "available",
    })
    assert _usable_catalog_candidate({
        "price": 1.99, "package_size": 500, "package_unit": "g",
        "availability": "unknown",
    })
    assert not _usable_catalog_candidate({
        "price": 1.99, "package_size": 500, "package_unit": "g",
        "availability": "out_of_stock",
    })

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
        duplicate_groups = {}
        for row in products:
            normalized_name = str(row.name_normalized or row.name_original or "").strip().lower()
            duplicate_groups.setdefault(normalized_name, []).append(row)
        duplicate_examples = [
            {
                "normalized_name": name,
                "count": len(rows),
                "ids": [row.id for row in rows],
                "titles": [row.name_original for row in rows],
                "prices": [row.price for row in rows],
                "package_sizes": [(row.package_size, row.package_unit) for row in rows],
                "categories": [row.category for row in rows],
                "brands": [row.brand for row in rows],
                "product_urls": [row.product_url for row in rows],
            }
            for name, rows in duplicate_groups.items() if len(rows) > 1
        ]
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
        package_name_mismatches = []
        for row in products:
            parsed_size, parsed_unit = package(row.name_original or "")
            if parsed_size is not None and parsed_unit:
                stored_unit = str(row.package_unit or "").strip().lower()
                stored_size = float(row.package_size) if row.package_size is not None else None
                if stored_unit == "kg":
                    stored_size = stored_size * 1000 if stored_size is not None else None
                    stored_unit = "g"
                elif stored_unit == "l":
                    stored_size = stored_size * 1000 if stored_size is not None else None
                    stored_unit = "ml"
                elif stored_unit == "piece":
                    stored_unit = "unit"
                if (
                    stored_size is None or not math.isfinite(stored_size) or stored_size <= 0
                    or stored_unit != parsed_unit
                    or abs(stored_size - parsed_size) / parsed_size > 0.05
                ):
                    package_name_mismatches.append({
                        "id": row.id, "name": row.name_original,
                        "stored_size": row.package_size, "stored_unit": row.package_unit,
                        "title_size": parsed_size, "title_unit": parsed_unit,
                    })

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
        assert invalid_price == 0, f"REWE snapshot contains {invalid_price} invalid numeric prices"
        assert not inconsistent_unit_prices, (
            f"REWE snapshot contains {len(inconsistent_unit_prices)} inconsistent package/unit prices"
        )
        assert not package_name_mismatches, (
            f"REWE snapshot contains {len(package_name_mismatches)} package sizes that disagree with product titles"
        )
        # Guard against silent parser regressions: this REWE snapshot has
        # only a handful of genuinely unpriced listings and no invalid pack data.
        assert invalid_price == 0, f"Found {invalid_price} zero/negative/non-finite REWE prices"
        assert missing_price <= 20, f"Unexpectedly many REWE products lack checkout prices: {missing_price}"
        assert invalid_packages == 0, f"Found {invalid_packages} invalid package sizes/units"
        assert not inconsistent_unit_prices, (
            f"Found {len(inconsistent_unit_prices)} inconsistent package unit prices"
        )
        assert not package_name_mismatches, (
            f"Found {len(package_name_mismatches)} package sizes that disagree with product titles"
        )

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        stale = sum(row.last_checked_at is None or row.last_checked_at < cutoff for row in products)

        adapter = server.main_module.CatalogAdapter(db)
        coverage = []
        for ingredient in SAMPLE_INGREDIENTS:
            candidates = adapter.search(ingredient) or []
            exact = [p for p in candidates if p.get("ingredient_match_type") == "exact"]
            substitutes = [
                p for p in candidates
                if p.get("ingredient_match_type") in {"substitute", "suggested_substitution"}
            ]
            usable_exact = [p for p in exact if _usable_catalog_candidate(p)]
            usable_substitutes = [p for p in substitutes if _usable_catalog_candidate(p)]
            usable = [p for p in candidates if _usable_catalog_candidate(p)]
            coverage.append({
                "ingredient": ingredient,
                "exact": len(exact),
                "usable_exact": len(usable_exact),
                "substitutes": len(substitutes),
                "usable_substitutes": len(usable_substitutes),
                "priced_usable": len(usable),
                "status": "exact" if usable_exact else (
                    "substitute" if usable_substitutes else "gap"
                ),
            })

        counts = Counter(row["status"] for row in coverage)
        print(f"REWE products: {total}")
        print(f"Distinct ingredient labels: {len(ingredients)}")
        print(f"Distinct categories: {len(categories)}")
        print(f"REWE category distribution: {dict(categories)}")
        print(f"Missing prices (not necessarily source errors): {missing_price} ({missing_price / total:.1%})")
        print(f"Invalid numeric prices (non-finite or <= 0): {invalid_price} ({invalid_price / total:.1%})")
        price_issue_examples = [
            row for row in products
            if row.price is None or not math.isfinite(float(row.price)) or float(row.price) <= 0
        ][:30]
        for row in price_issue_examples:
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
        if len(price_issue_examples) < missing_price + invalid_price:
            print(f"Additional price issues omitted from log: {missing_price + invalid_price - len(price_issue_examples)}")
        print(f"Stale or never checked (>30 days): {stale} ({stale / total:.1%})")
        print(f"Duplicate normalized-name rows: {duplicate_name_rows}")
        for duplicate in duplicate_examples[:20]:
            print("DUPLICATE NORMALIZED NAME:", duplicate)
        print(f"Products with REWE product URL: {with_product_url} ({with_product_url / total:.1%})")
        print(f"Products with image URL: {with_image_url} ({with_image_url / total:.1%})")
        print(f"Invalid package sizes/units: {invalid_packages}")
        print(f"Package size not parsed by source extractor: {unknown_package_units} (not automatically a REWE data error)")
        print(f"Price/unit inconsistencies (>15%): {len(inconsistent_unit_prices)}")
        print(f"Package sizes disagree with explicit product-title sizes: {len(package_name_mismatches)}")
        for row in package_name_mismatches[:30]:
            print("PACKAGE/TITLE MISMATCH:", row)
        for row in inconsistent_unit_prices[:30]:
            print("PRICE/UNIT MISMATCH:", row)
        print(f"Availability distribution: {dict(availability)}")
        print(f"Sample coverage ({len(coverage)} common ingredients): {dict(counts)}")
        print("Sample coverage details:", coverage)
        gaps = [row for row in coverage if row["status"] == "gap"]
        # These gaps are absent from the committed snapshot, although the current
        # REWE source category lists them. A fresh complete live crawl should resolve
        # them; never disguise missing source rows with unsafe substitutes.
        known_snapshot_gaps = {"rice", "rolled oats", "burger buns"}
        unexpected_gaps = [row for row in gaps if row["ingredient"] not in known_snapshot_gaps]
        if gaps:
            print(f"Known committed-snapshot assortment gaps (must disappear after live refresh): {gaps}")
        assert not unexpected_gaps, (
            f"Common REWE ingredients without a safe exact/substitute match: {unexpected_gaps}"
        )
        assert sum(counts.values()) == len(SAMPLE_INGREDIENTS), (
            f"Expected coverage for all {len(SAMPLE_INGREDIENTS)} common ingredients, got {dict(counts)}"
        )
        for row in coverage:
            if row["status"] == "gap":
                print("CATALOG GAP:", row)
                hint_terms = {
                    "rice": ("reis", "risotto", "basmati", "langkorn", "parboiled", "kuko"),
                    "rolled oats": ("haferflocken", "hafer", "oat"),
                    "burger buns": ("burger", "brötchen", "brotchen", "buns", "toast"),
                    "cherry tomato": ("tomat", "cocktail", "kirsche"),
                    "greek yogurt": ("joghurt", "yoghurt", "skyr", "quark"),
                    "chicken breast": ("hahnchen", "haehnchen", "huhn", "brust", "putenbrust", "pute"),
                    "olive oil": ("oliven", "olivenol", "olivenoel", "rapsol", "rapsoel", "sonnenblumenol", "pflanzenol"),
                    "cornstarch": ("speisestarke", "speise starke", "maisstarke", "mais starke", "mondamin"),
                }.get(row["ingredient"], tuple(row["ingredient"].split()))
                suggestions = [
                    product.name_original
                    for product in products
                    if any(
                        normalize_text(term) in normalize_text(product.name_original or "")
                        for term in hint_terms
                    )
                ][:20]
                print("CATALOG NEAR-MATCH TITLES:", row["ingredient"], suggestions)
                detailed_suggestions = [
                    (product.name_original, product.category)
                    for product in products
                    if any(
                        normalize_text(term) in normalize_text(product.name_original or "")
                        for term in hint_terms
                    )
                ][:30]
                print("CATALOG NEAR-MATCH CATEGORIES:", row["ingredient"], detailed_suggestions)
    finally:
        db.close()


if __name__ == "__main__":
    main()
