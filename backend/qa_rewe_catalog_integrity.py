"""Read-only diagnostic of the user's local REWE catalog.

Run from backend/: python qa_rewe_catalog_integrity.py
This script never modifies catalog rows or contacts REWE.
"""
import math
from collections import Counter

from app.database import Product, SessionLocal
from app.rewe.scraper import package
from app.server import main_module


def _finite(value):
    try:
        number = float(value)
        return math.isfinite(number), number
    except (TypeError, ValueError):
        return False, None


def main():
    db = SessionLocal()
    try:
        rows = db.query(Product).filter(Product.supermarket == "REWE").all()
        print(f"REWE catalog products: {len(rows)}")
        if not rows:
            print("No REWE products found. Run a local REWE catalog refresh first.")
            return

        missing_package = []
        legacy_default = []
        invalid_price = []
        unit_price_drift = []
        availability = Counter()
        duplicate_names = Counter()

        for row in rows:
            valid_size, size = _finite(row.package_size)
            unit = str(row.package_unit or "").strip().lower()
            if not valid_size or size <= 0 or unit in {"", "unknown", "none"}:
                missing_package.append(row)
            if valid_size and size == 1 and unit in {"unit", "piece"} and package(row.name_original) == (None, None):
                legacy_default.append(row)
            if row.price is not None:
                valid_price, numeric_price = _finite(row.price)
                if not valid_price or numeric_price < 0:
                    invalid_price.append(row)
                elif valid_size and size > 0 and row.price_per_unit is not None:
                    valid_unit_price, numeric_unit_price = _finite(row.price_per_unit)
                    expected = numeric_price / size
                    if not valid_unit_price or not math.isclose(
                        numeric_unit_price, expected, rel_tol=0.02, abs_tol=0.000001
                    ):
                        unit_price_drift.append(row)
            availability[str(row.availability or "unknown").lower()] += 1
            duplicate_names[str(row.name_normalized or "").strip()] += 1

        duplicate_groups = {
            name: count for name, count in duplicate_names.items() if name and count > 1
        }
        print(f"Missing/unknown package metadata: {len(missing_package)}")
        print(f"Possible legacy fake '1 unit' defaults: {len(legacy_default)}")
        print(f"Invalid prices: {len(invalid_price)}")
        print(f"Price-per-unit drift vs price/package: {len(unit_price_drift)}")
        print(f"Availability: {dict(availability)}")
        print(f"Duplicate normalized product names: {len(duplicate_groups)}")

        for label, sample in (
            ("LEGACY DEFAULTS", legacy_default),
            ("MISSING PACKAGE", missing_package),
            ("PRICE-PER-UNIT DRIFT", unit_price_drift),
        ):
            if sample:
                print(f"\n{label} (up to 10):")
                for row in sample[:10]:
                    print(
                        f"- id={row.id} | {row.name_original} | "
                        f"{row.package_size} {row.package_unit} | "
                        f"price={row.price} | price_per_unit={row.price_per_unit}"
                    )

        adapter = main_module.CatalogAdapter(db)
        probes = [
            "milk", "olive oil", "chicken breast", "rice", "tomato",
            "onion", "eggs", "butter", "flour", "saffron", "leek",
        ]
        print("\nIngredient catalog matching:")
        for ingredient in probes:
            matches = adapter.search(ingredient)
            usable = [
                item for item in matches
                if item.get("price") is not None
                and _finite(item.get("package_size"))[0]
                and float(item.get("package_size") or 0) > 0
                and str(item.get("package_unit") or "").lower() not in {"", "unknown"}
            ]
            examples = ", ".join(
                str(item.get("name_original") or "")[:48] for item in usable[:2]
            )
            print(f"- {ingredient}: {len(matches)} matches, {len(usable)} usable [{examples}]")
    finally:
        db.close()


if __name__ == "__main__":
    main()
