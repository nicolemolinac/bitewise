"""Full-row offline QA of every product in the committed REWE snapshot.

Run from backend/: python qa_catalog_full_audit.py
Imports the committed CSV into a disposable SQLite DB. No network, REWE scraper,
image scraper, product-detail scraper, Gemini call, or user DB is touched.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-full-catalog-audit-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "catalog-audit.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

from app.database import Product, SessionLocal
from app.catalog.intelligence import classify_product
from app.ingredient_aliases import canonical_ingredient_terms


MULTIPACK = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", re.I)
NON_CULINARY_MARKERS = (
    "waschmittel", "spülmittel", "spuelmittel", "reiniger", "wc-reiniger",
    "toilettenpapier", "shampoo", "zahnpasta", "windeln", "katzenstreu",
    "hundefutter", "katzenfutter", "vogelfutter", "waschpulver",
)
COMPONENTS_NEVER_COMPLETE_MEALS = (
    "pizzateig", "pizza teig", "pizzagewürz", "pizzagewuerz",
    "pizza gewürz", "pizza gewuerz", "pizzasauce", "pizza sauce",
    "pizza soße", "pizza sosse", "pizzakäse", "pizzakaese",
    "ramen nudeln", "ramen noodles", "ramen noodle",
    "lasagneplatten", "lasagne platten", "lasagne blätter", "lasagneblaetter",
    "bowl topping", "topping bowl",
)
UNIT_FACTORS = {"g": 1.0, "ml": 1.0, "kg": 1000.0, "l": 1000.0, "unit": 1.0, "stk": 1.0, "stück": 1.0, "pcs": 1.0}


def _row_name(row):
    return str(row.name_original or row.name_normalized or "").strip()


def _multipack_expected(name):
    match = MULTIPACK.search(name or "")
    if not match:
        return None
    count = int(match.group(1))
    amount = float(match.group(2).replace(",", "."))
    unit = match.group(3).lower()
    if unit in {"kg", "l"}:
        amount *= 1000
    return count * amount, "g" if unit in {"g", "kg"} else "ml"


def main():
    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.supermarket == "REWE").order_by(Product.id.asc()).all()
        total = len(products)
        assert total >= 10000, f"Expected the complete ~12k snapshot, got only {total} products"

        counters = Counter()
        categories = Counter()
        units = Counter()
        types = Counter()
        roles = Counter()
        availability = Counter()
        duplicate_names = defaultdict(list)
        duplicate_external_ids = defaultdict(list)
        issues = defaultdict(list)
        canonical_hits = 0

        for row in products:
            name = _row_name(row)
            lower = name.lower()
            categories[str(row.category or "uncategorized")] += 1
            units[str(row.package_unit or "missing").lower()] += 1
            availability[str(row.availability or "unknown").lower()] += 1
            duplicate_names[(row.name_normalized or name).strip().lower()].append(row.id)
            duplicate_external_ids[str(row.external_id or "").strip()].append(row.id)

            if not name:
                issues["empty_name"].append(row.id)
            if row.package_size is None or float(row.package_size or 0) <= 0:
                issues["invalid_package_size"].append((row.id, name, row.package_size, row.package_unit))
            unit = str(row.package_unit or "").strip().lower()
            if unit not in UNIT_FACTORS:
                issues["unrecognized_package_unit"].append((row.id, name, row.package_size, unit))
            if row.price is None or float(row.price or 0) <= 0:
                issues["missing_or_nonpositive_price"].append((row.id, name, row.price))
            if str(row.currency or "").upper() != "EUR":
                issues["non_eur_currency"].append((row.id, name, row.currency))

            # price_per_unit in this catalog is normalized to €/g, €/ml or €/item.
            if row.price is not None and row.price_per_unit is not None and row.package_size:
                factor = UNIT_FACTORS.get(unit)
                if factor:
                    expected = float(row.price) / (float(row.package_size) * factor)
                    actual = float(row.price_per_unit)
                    if expected > 0 and abs(actual - expected) / expected > 0.15:
                        issues["price_per_unit_mismatch"].append(
                            (row.id, name, round(float(row.price), 3), row.package_size, unit,
                             round(actual, 6), round(expected, 6))
                        )

            expected_pack = _multipack_expected(name)
            if expected_pack:
                expected_size, expected_unit = expected_pack
                if unit == expected_unit and row.package_size is not None:
                    actual_size = float(row.package_size)
                    if abs(actual_size - expected_size) > max(1.0, expected_size * 0.02):
                        issues["multipack_size_mismatch"].append(
                            (row.id, name, actual_size, unit, expected_size, expected_unit)
                        )

            profile = classify_product({
                "name_original": row.name_original,
                "name_normalized": row.name_normalized,
                "translated_name": row.translated_name,
                "brand": row.brand,
                "category": row.category,
            })
            types[profile.product_type] += 1
            roles[profile.culinary_role] += 1
            counters[f"confidence:{profile.confidence:.2f}"] += 1
            if canonical_ingredient_terms(name):
                canonical_hits += 1

            if profile.is_complete_meal and any(marker in lower for marker in COMPONENTS_NEVER_COMPLETE_MEALS):
                issues["component_misclassified_as_complete_meal"].append(
                    (row.id, name, row.category, profile.evidence)
                )
            if any(marker in lower for marker in NON_CULINARY_MARKERS):
                issues["non_culinary_catalog_candidates"].append((row.id, name, row.category, profile.product_type))

        for key, ids in duplicate_names.items():
            if key and len(ids) > 1:
                issues["duplicate_normalized_names"].append((key, ids[:8], len(ids)))
        for key, ids in duplicate_external_ids.items():
            if key and len(ids) > 1:
                issues["duplicate_external_ids"].append((key, ids[:8], len(ids)))

        print(f"FULL REWE CATALOG AUDIT: {total} / ~12,000 rows analyzed")
        print(f"Categories ({len(categories)}): {dict(categories)}")
        print(f"Package units: {dict(units)}")
        print(f"Availability values: {dict(availability)}")
        print(f"Product types: {dict(types)}")
        print(f"Culinary roles: {dict(roles)}")
        print(f"Products with canonical culinary terms in title: {canonical_hits}/{total}")
        print("\nISSUE COUNTS:")
        for key, values in sorted(issues.items()):
            print(f"  {key}: {len(values)}")
            for sample in values[:12]:
                print(f"    - {sample}")

        # These are data-integrity failures, not subjective classification gaps.
        blocking = (
            "empty_name", "invalid_package_size", "unrecognized_package_unit",
            "missing_or_nonpositive_price", "non_eur_currency",
            "price_per_unit_mismatch", "multipack_size_mismatch",
            "component_misclassified_as_complete_meal",
        )
        failures = {key: len(issues[key]) for key in blocking if issues[key]}
        assert not failures, f"Full-catalog data integrity/classification failures: {failures}"

        print("\nFull catalog audit PASS: every imported product row was inspected.")
        print("Duplicate names and non-culinary products are diagnostic review groups, not automatic deletions.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
