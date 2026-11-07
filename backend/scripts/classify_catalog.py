"""Classify existing catalog rows without contacting REWE.

Dry-run is the default. Pass --apply to persist derived metadata in bounded batches.
This script never reads or writes image URLs and never launches a browser.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.catalog.intelligence import classify_product, persist_product_profile
from app.database import Product, SessionLocal

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist classifications (otherwise dry-run)")
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of products")
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 1000:
        parser.error("--batch-size must be between 1 and 1000")

    db = SessionLocal()
    try:
        query = db.query(Product).filter(Product.supermarket == "REWE").order_by(Product.id.asc())
        if args.limit:
            query = query.limit(max(1, args.limit))
        products = query.all()
        counts = Counter()
        complete_meals = []
        for start in range(0, len(products), args.batch_size):
            batch = products[start:start + args.batch_size]
            for product in batch:
                profile = classify_product({
                    "name_original": product.name_original,
                    "name_normalized": product.name_normalized,
                    "translated_name": product.translated_name,
                    "brand": product.brand,
                    "category": product.category,
                })
                counts[f"type:{profile.product_type}"] += 1
                counts[f"role:{profile.culinary_role}"] += 1
                if profile.is_complete_meal:
                    complete_meals.append((product.name_original, profile.confidence, profile.dish_families))
                if args.apply:
                    persist_product_profile(db, product, profile)
            if args.apply:
                db.commit()
        print(f"Products analyzed: {len(products)}")
        print(f"Mode: {'APPLY' if args.apply else 'DRY RUN (no database writes)'}")
        for key, value in sorted(counts.items()):
            print(f"{key}: {value}")
        print(f"Complete meal candidates: {len(complete_meals)}")
        for name, confidence, families in complete_meals[:30]:
            print(f"  {confidence:.2f} | {name} | {', '.join(families) or 'unclassified family'}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
