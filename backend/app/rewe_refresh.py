from datetime import datetime
import logging
import math

from fastapi import APIRouter, HTTPException

from .database import (
    AppSetting,
    CatalogRun,
    Product,
    ProductOverride,
    ProductSemanticEmbedding,
    SessionLocal,
    ShoppingState,
)
from .rewe.scraper import REWE_CATEGORY_URLS, ReweCatalogScraper

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _setting(db, key: str, default: str) -> str:
    item = db.get(AppSetting, key)
    return item.value if item else default


def _remove_stale_rewe_products(db, seen_external_ids: set[str], before_count: int):
    """Remove only products proven absent from a complete, healthy catalog refresh.

    The current catalog is treated as the baseline. We only reconcile deletions when the
    scraper returned enough products to look trustworthy. This protects the good existing
    catalog from transient REWE/scraper failures.
    """
    seen_count = len(seen_external_ids)
    minimum_safe = max(100, int(before_count * 0.70)) if before_count else 100
    if seen_count < minimum_safe:
        return {
            "removed": 0,
            "reconciliation_skipped": True,
            "reconciliation_reason": (
                f"Safety guard: refresh saw {seen_count} products, below the safe minimum "
                f"of {minimum_safe}; existing catalog was preserved."
            ),
        }

    stale = (
        db.query(Product)
        .filter(Product.supermarket == "REWE")
        .filter(~Product.external_id.in_(seen_external_ids))
        .all()
    )
    if not stale:
        return {"removed": 0, "reconciliation_skipped": False}

    stale_ids = [row.id for row in stale]

    # Avoid dangling references when a REWE product genuinely disappears.
    db.query(ProductOverride).filter(ProductOverride.product_id.in_(stale_ids)).delete(
        synchronize_session=False
    )
    for state in db.query(ShoppingState).filter(ShoppingState.product_id.in_(stale_ids)).all():
        state.product_id = None

    for row in stale:
        db.delete(row)

    db.flush()
    return {"removed": len(stale), "reconciliation_skipped": False}


@router.post("/rewe/refresh")
def rewe_refresh_safe():
    """Merge a fresh REWE snapshot into the existing catalog without destructive resets.

    Existing products are updated in place, including prices. New products are inserted.
    Products missing from REWE are removed only after a complete healthy refresh and only
    if the refreshed catalog passes a shrink-safety check.
    """
    db = SessionLocal()
    postcode = _setting(db, "postcode", "13353")
    run = CatalogRun(status="running")
    db.add(run)
    db.commit()

    before_count = db.query(Product).filter(Product.supermarket == "REWE").count()
    seen_external_ids: set[str] = set()

    try:
        def upsert(data, current_postcode):
            external_id = str(data["external_id"])
            seen_external_ids.add(external_id)
            existing = (
                db.query(Product)
                .filter_by(supermarket="REWE", external_id=external_id)
                .first()
            )
            now = datetime.utcnow()
            incoming = dict(data)

            # Unknown package sizes are represented as None by the scraper.
            # Keep a known existing package instead of replacing it with a fake
            # 1-unit package; only brand-new rows need a harmless placeholder.
            try:
                package_size = float(incoming.get("package_size"))
                package_unit = str(incoming.get("package_unit") or "").strip()
                valid_package = math.isfinite(package_size) and package_size > 0 and bool(package_unit)
            except (OverflowError, TypeError, ValueError):
                valid_package = False
            if valid_package:
                incoming["package_size"] = package_size
                incoming["package_unit"] = package_unit
            else:
                incoming.pop("package_size", None)
                incoming.pop("package_unit", None)

            # A missing/invalid live price is not a price change. Preserve the
            # last usable checkout price and its unit price instead of erasing it.
            try:
                incoming_price = float(incoming.get("price"))
                valid_price = math.isfinite(incoming_price) and incoming_price > 0
            except (OverflowError, TypeError, ValueError):
                valid_price = False
            if valid_price:
                incoming["price"] = incoming_price
                try:
                    unit_price = float(incoming.get("price_per_unit"))
                    valid_unit_price = math.isfinite(unit_price) and unit_price > 0
                except (OverflowError, TypeError, ValueError):
                    valid_unit_price = False
                if valid_unit_price:
                    incoming["price_per_unit"] = unit_price
                elif valid_package:
                    incoming["price_per_unit"] = incoming_price / package_size
                else:
                    incoming.pop("price_per_unit", None)
            else:
                incoming.pop("price", None)
                incoming.pop("price_per_unit", None)

            if existing:
                if valid_price and existing.price != incoming_price:
                    existing.last_price = existing.price
                for key, value in incoming.items():
                    if not hasattr(existing, key):
                        continue
                    # Missing fields from a partial card must never erase saved catalog data.
                    if key in {"image_url", "product_url"} and not value:
                        continue
                    setattr(existing, key, value)
                existing.postcode_context = current_postcode
                existing.last_seen_at = now
                existing.last_checked_at = now
                db.flush()
                return False

            incoming.setdefault("package_size", 1.0)
            incoming.setdefault("package_unit", "unit")
            db.add(Product(supermarket="REWE", postcode_context=current_postcode, **incoming))
            db.flush()
            return True

        report = ReweCatalogScraper().run(upsert, postcode)

        complete_healthy = (
            report.get("status") == "healthy"
            and report.get("categories_failed", 0) == 0
            and report.get("categories_processed", 0) == len(REWE_CATEGORY_URLS)
            and report.get("categories_successful", 0) == len(REWE_CATEGORY_URLS)
        )

        reconciliation = {
            "removed": 0,
            "reconciliation_skipped": True,
            "reconciliation_reason": "Refresh was partial or incomplete; existing catalog preserved.",
        }
        if complete_healthy:
            reconciliation = _remove_stale_rewe_products(db, seen_external_ids, before_count)

        run.status = report["status"]
        run.products_seen = report["products_found"]
        run.errors = len(report["errors"])
        run.categories_processed = report["categories_processed"]
        run.categories_successful = report["categories_successful"]
        run.categories_failed = report["categories_failed"]
        run.finished_at = datetime.utcnow()
        db.commit()

        semantic_index = {"status": "not_initialized"}
        if db.query(ProductSemanticEmbedding).count():
            try:
                from .semantic_catalog import index_rewe_products
                semantic_index = {"status": "updated", **index_rewe_products(db)}
            except Exception as exc:
                db.rollback()
                logger.warning("REWE catalog refreshed, but semantic index update failed: %s", exc)
                semantic_index = {"status": "failed", "reason": str(exc)[:180]}

        after_count = db.query(Product).filter(Product.supermarket == "REWE").count()
        return {
            "ok": report["status"] != "failed",
            **report,
            **reconciliation,
            "semantic_index": semantic_index,
            "catalog_before": before_count,
            "catalog_after": after_count,
            "message": (
                "REWE catalog merged into the existing baseline: prices/details updated, "
                "new products added, and missing products reconciled only after a safe full refresh."
            ),
        }
    except Exception as exc:
        db.rollback()
        recovery = db.get(CatalogRun, run.id)
        if recovery:
            recovery.status = "failed"
            recovery.errors = max(1, recovery.errors or 0)
            recovery.finished_at = datetime.utcnow()
            db.commit()
        raise HTTPException(502, f"REWE refresh failed: {str(exc)[:180]}")
    finally:
        db.close()
