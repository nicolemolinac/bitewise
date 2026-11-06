"""Export the local REWE database with fields needed for real shopping handoff.

Run from backend/: python export_rewe_catalog.py
The export preserves product URLs, external IDs, images, postcode and price timestamps.
"""
import csv
from pathlib import Path

from app.database import Product, SessionLocal

OUTPUT = Path(__file__).resolve().parent / "data" / "catalog" / "rewe_products.csv"
FIELDS = [
    "id", "supermarket", "external_id", "ingredient", "name_original",
    "name_normalized", "translated_name", "brand", "category", "package_size",
    "package_unit", "price", "price_per_unit", "currency", "product_url",
    "image_url", "availability", "postcode_context", "first_seen_at",
    "last_seen_at", "last_checked_at", "last_price",
]


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        rows = (
            db.query(Product)
            .filter(Product.supermarket == "REWE")
            .order_by(Product.category, Product.ingredient, Product.name_original)
            .all()
        )
        if not rows:
            raise RuntimeError("No REWE products found in the configured database.")
        with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    field: getattr(row, field, None)
                    for field in FIELDS
                })
        with_urls = sum(bool(row.product_url) for row in rows)
        with_prices = sum(row.price is not None and float(row.price) > 0 for row in rows)
        print(f"Exported {len(rows)} REWE products to {OUTPUT}")
        print(f"Priced products: {with_prices}/{len(rows)}")
        print(f"Products with direct REWE URL: {with_urls}/{len(rows)}")
        if not with_urls:
            print("WARNING: This database has no direct product URLs; refresh the REWE catalog before expecting one-click product handoff.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
