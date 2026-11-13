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


def _merge_rewe_product_data(existing, data: dict, current_postcode: str, now: datetime) -> None:
    """Merge a partial REWE card without erasing previously verified product facts."""
    raw_price = data.get("price")
    try:
        incoming_price = float(raw_price) if raw_price is not None else None
    except (TypeError, ValueError):
        incoming_price = None
    valid_price = incoming_price is not None and math.isfinite(incoming_price) and incoming_price > 0

    raw_unit_price = data.get("price_per_unit")
    try:
        incoming_unit_price = float(raw_unit_price) if raw_unit_price is not None else None
    except (TypeError, ValueError):
        incoming_unit_price = None
    valid_unit_price = (
        incoming_unit_price is not None
        and math.isfinite(incoming_unit_price)
        and incoming_unit_price > 0
    )

    raw_size = data.get("package_size")
    try:
        incoming_size = float(raw_size) if raw_size is not None else None
    except (TypeError, ValueError):
        incoming_size = None
    incoming_unit = str(data.get("package_unit") or "").strip().lower()
    valid_package = (
        incoming_size is not None and math.isfinite(incoming_size) and incoming_size > 0
        and incoming_unit not in {"", "unknown"}
    )

    if valid_price and existing.price is not None:
        try:
            previous_price = float(existing.price)
            if math.isfinite(previous_price) and previous_price > 0 and previous_price != incoming_price:
                existing.last_price = previous_price
        except (TypeError, ValueError):
            pass

    # A new price with no parsed pack size belongs to the existing SKU/package;
    # keep its known size and derive a coherent unit price from that size.
    for key, value in data.items():
        if not hasattr(existing, key):
            continue
        if key in {"image_url", "product_url", "brand", "category"} and not value:
            continue
        if key == "price":
            if not valid_price:
                continue
            setattr(existing, key, incoming_price)
            continue
        if key == "price_per_unit":
            if valid_price and valid_unit_price:
                existing.price_per_unit = incoming_unit_price
            continue
        if key in {"package_size", "package_unit"}:
            # Never replace a known mass/volume pack with the scraper's
            # 1 x unknown fallback when the card did not expose its size.
            if valid_package and (valid_price or existing.price is None):
                setattr(existing, key, incoming_size if key == "package_size" else incoming_unit)
            continue
        setattr(existing, key, value)

    if valid_price and not valid_unit_price:
        try:
            known_size = float(existing.package_size)
            if math.isfinite(known_size) and known_size > 0:
                existing.price_per_unit = incoming_price / known_size
        except (TypeError, ValueError):
            pass
    existing.postcode_context = current_postcode
    existing.last_seen_at = now
    existing.last_checked_at = now


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
                _merge_rewe_product_data(existing, data, current_postcode, now)
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
