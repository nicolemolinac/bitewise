from datetime import datetime

from fastapi import APIRouter, HTTPException

from .database import (
    AppSetting,
    CatalogRun,
    Product,
    ProductOverride,
    SessionLocal,
    ShoppingState,
)
from .rewe.scraper import REWE_CATEGORY_URLS, ReweCatalogScraper

router = APIRouter(prefix="/api")


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

            if existing:
                incoming_price = data.get("price")
                if existing.price != incoming_price:
                    existing.last_price = existing.price
                for key, value in data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                existing.postcode_context = current_postcode
                existing.last_seen_at = now
                existing.last_checked_at = now
                db.flush()
                return False

            db.add(Product(supermarket="REWE", postcode_context=current_postcode, **data))
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

        after_count = db.query(Product).filter(Product.supermarket == "REWE").count()
        return {
            "ok": report["status"] != "failed",
            **report,
            **reconciliation,
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
