"""One-time migration of the local REWE snapshot into the persistent cloud database.

Run this after DATABASE_URL points at Supabase/Postgres. It copies the existing
backend/data/grocery.db REWE products into Postgres without scraping REWE again.
The cloud catalog then survives deploys and can be reused for months until the
next manual refresh.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
LOCAL_DB = BACKEND_DIR / "data" / "grocery.db"
load_dotenv(BACKEND_DIR / ".env")

if not os.getenv("DATABASE_URL", "").strip():
    raise SystemExit("DATABASE_URL is required. Point it at the persistent Supabase/Postgres database first.")
if not LOCAL_DB.exists():
    raise SystemExit(f"Local catalog not found: {LOCAL_DB}")

from app.database import AppSetting, CatalogRun, Product, SessionLocal  # noqa: E402

PRODUCT_FIELDS = [
    "supermarket", "external_id", "ingredient", "name_original", "name_normalized",
    "translated_name", "brand", "category", "package_size", "package_unit", "price",
    "price_per_unit", "currency", "product_url", "availability", "postcode_context",
    "first_seen_at", "last_seen_at", "last_checked_at", "last_price",
]


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def set_setting(db, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def main() -> None:
    source = sqlite3.connect(LOCAL_DB)
    source.row_factory = sqlite3.Row
    tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "products" not in tables:
        raise SystemExit("The local SQLite database has no products table.")

    rows = source.execute("SELECT * FROM products WHERE supermarket = 'REWE'").fetchall()
    if not rows:
        raise SystemExit("No REWE products were found in the local SQLite database.")

    source_columns = {r[1] for r in source.execute("PRAGMA table_info(products)")}
    target = SessionLocal()
    created = 0
    updated = 0
    try:
        for src in rows:
            external_id = str(src["external_id"] or "").strip()
            supermarket = str(src["supermarket"] or "REWE")
            if not external_id:
                continue
            product = (
                target.query(Product)
                .filter(Product.supermarket == supermarket, Product.external_id == external_id)
                .first()
            )
            if product is None:
                product = Product(
                    supermarket=supermarket,
                    external_id=external_id,
                    ingredient=str(src["ingredient"] or ""),
                    name_original=str(src["name_original"] or ""),
                    name_normalized=str(src["name_normalized"] or ""),
                    package_size=float(src["package_size"] or 1),
                    package_unit=str(src["package_unit"] or "unit"),
                )
                target.add(product)
                created += 1
            else:
                updated += 1

            for field in PRODUCT_FIELDS:
                if field not in source_columns or field in {"supermarket", "external_id"}:
                    continue
                value = src[field]
                if field in {"first_seen_at", "last_seen_at", "last_checked_at"}:
                    value = parse_dt(value)
                if value is not None:
                    setattr(product, field, value)

        latest = None
        if "catalog_runs" in tables:
            latest = source.execute(
                "SELECT * FROM catalog_runs WHERE provider='REWE' AND status != 'running' "
                "ORDER BY COALESCE(finished_at, started_at) DESC, id DESC LIMIT 1"
            ).fetchone()

        now = datetime.utcnow()
        last_sync = parse_dt(latest["finished_at"] if latest and "finished_at" in latest.keys() else None) or now
        product_count = len(rows)

        set_setting(target, "rewe_snapshot_persistent", "true")
        set_setting(target, "rewe_snapshot_source", "migrated-local-sqlite")
        set_setting(target, "rewe_snapshot_product_count", str(product_count))
        set_setting(target, "rewe_snapshot_last_success_at", last_sync.isoformat())
        set_setting(target, "rewe_refresh_interval_days", os.getenv("REWE_REFRESH_INTERVAL_DAYS", "90"))
        set_setting(target, "rewe_snapshot_migrated_at", now.isoformat())

        # Keep a cloud-side run record so /api/rewe/status has durable history even
        # before the next live refresh.
        target.add(CatalogRun(
            provider="REWE",
            status="healthy",
            products_seen=product_count,
            errors=0,
            categories_processed=int(latest["categories_processed"] or 0) if latest and "categories_processed" in latest.keys() else 0,
            categories_successful=int(latest["categories_successful"] or 0) if latest and "categories_successful" in latest.keys() else 0,
            categories_failed=int(latest["categories_failed"] or 0) if latest and "categories_failed" in latest.keys() else 0,
            started_at=parse_dt(latest["started_at"] if latest and "started_at" in latest.keys() else None) or last_sync,
            finished_at=last_sync,
        ))
        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()
        source.close()

    print(f"REWE snapshot preserved in cloud: {product_count} products ({created} created, {updated} updated).")
    print("No automatic refresh was scheduled. Bitewise will keep using this snapshot until you manually refresh it.")


if __name__ == "__main__":
    main()
