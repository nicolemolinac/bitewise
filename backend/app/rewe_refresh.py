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


def _valid_rewe_package(data: dict) -> bool:
    raw_size = data.get("package_size")
    if isinstance(raw_size, bool):
        return False
    try:
        size = float(raw_size)
    except (OverflowError, TypeError, ValueError):
        return False
    return math.isfinite(size) and size > 0 and bool(str(data.get("package_unit") or "").strip())


def _valid_rewe_checkout_price(data: dict) -> bool:
    raw_price = data.get("price")
    if isinstance(raw_price, bool):
        return False
    try:
        price = float(raw_price)
    except (OverflowError, TypeError, ValueError):
        return False
    return math.isfinite(price) and price > 0


def _refresh_is_complete_healthy(report: dict) -> bool:
    """Allow destructive reconciliation only for complete, high-quality snapshots."""
    skipped = int(report.get("products_skipped", 0) or 0)
    found = int(report.get("products_found", 0) or 0)
    max_skips = max(5, int(found * 0.01))
    return (
        report.get("status") == "healthy"
        and report.get("categories_failed", 0) == 0
        and report.get("categories_processed", 0) == len(REWE_CATEGORY_URLS)
        and report.get("categories_successful", 0) == len(REWE_CATEGORY_URLS)
        and skipped <= max_skips
    )


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
    # Embeddings are stored without a database FK; remove them in the same
    # transaction so failed semantic re-indexing cannot leave orphan vectors.
    db.query(ProductSemanticEmbedding).filter(
        ProductSemanticEmbedding.product_id.in_(stale_ids)
    ).delete(synchronize_session=False)
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
    skipped_invalid_package = 0
    skipped_invalid_price = 0
    skipped_invalid_identity = 0

    try:
        def upsert(data, current_postcode):
            nonlocal skipped_invalid_package, skipped_invalid_price, skipped_invalid_identity
            external_id = str(data.get("external_id") or "").strip()
            if not external_id:
                skipped_invalid_identity += 1
                return None
            existing = (
                db.query(Product)
                .filter_by(supermarket="REWE", external_id=external_id)
                .first()
            )
            # Existing rows count as seen even when this observation omits a
            # package size: their previously verified dimensions are preserved.
            if existing is not None:
                seen_external_ids.add(external_id)
            now = datetime.utcnow()
            incoming = dict(data)

            # Unknown package sizes are represented as None by the scraper.
            # Keep a known existing package instead of replacing it with a fake
            # 1-unit package; only brand-new rows need a harmless placeholder.
            valid_package = _valid_rewe_package(incoming)
            try:
                package_size = float(incoming.get("package_size")) if valid_package else None
            except (OverflowError, TypeError, ValueError):
                package_size = None
            package_unit = str(incoming.get("package_unit") or "").strip()
            if valid_package:
                incoming["package_size"] = package_size
                incoming["package_unit"] = package_unit
            else:
                incoming.pop("package_size", None)
                incoming.pop("package_unit", None)

            # A missing/invalid live price is not a price change. Preserve the
            # last usable checkout price and its unit price instead of erasing it.
            valid_price = _valid_rewe_checkout_price(incoming)
            try:
                incoming_price = float(incoming.get("price")) if valid_price else None
            except (OverflowError, TypeError, ValueError):
                incoming_price = None
            if valid_price:
                incoming["price"] = incoming_price
            else:
                incoming.pop("price", None)

            # Derive unit price from checkout price and verified package
            # dimensions. Never trust a separately supplied reference price.
            checkout_for_unit_price = incoming_price if valid_price else (
                getattr(existing, "price", None) if existing is not None else None
            )
            package_for_unit_price = package_size if valid_package else (
                getattr(existing, "package_size", None) if existing is not None else None
            )
            try:
                checkout_for_unit_price = float(checkout_for_unit_price)
                package_for_unit_price = float(package_for_unit_price)
                derived_unit_price = checkout_for_unit_price / package_for_unit_price
            except (OverflowError, TypeError, ValueError, ZeroDivisionError):
                derived_unit_price = None
            if (
                derived_unit_price is not None
                and math.isfinite(derived_unit_price)
                and derived_unit_price > 0
            ):
                incoming["price_per_unit"] = derived_unit_price
            else:
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

            if not valid_package:
                # A new catalog row without a measurable package cannot be
                # costed safely. Do not invent a one-unit package and expose it as purchasable.
                skipped_invalid_package += 1
                return None
            if not valid_price:
                # A brand-new product without a real checkout price is not a
                # usable basket candidate. Preserve existing rows, but never
                # insert an unpriced product that can distort product ranking.
                skipped_invalid_price += 1
                return None
            seen_external_ids.add(external_id)
            incoming["package_size"] = package_size
            incoming["package_unit"] = package_unit
            db.add(Product(supermarket="REWE", postcode_context=current_postcode, **incoming))
            db.flush()
            return True

        report = ReweCatalogScraper().run(upsert, postcode)

        skipped_observations = int(report.get("products_skipped", 0) or 0)
        found_observations = int(report.get("products_found", 0) or 0)
        max_skips_for_reconciliation = max(5, int(found_observations * 0.01))
        complete_healthy = _refresh_is_complete_healthy(report)

        reconciliation = {
            "removed": 0,
            "reconciliation_skipped": True,
            "reconciliation_reason": (
                f"Refresh skipped {skipped_observations} product observations "
                f"(safe maximum {max_skips_for_reconciliation}); existing catalog preserved."
                if skipped_observations > max_skips_for_reconciliation
                else "Refresh was partial or incomplete; existing catalog preserved."
            ),
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
            "products_skipped_invalid_package": skipped_invalid_package,
            "products_skipped_invalid_price": skipped_invalid_price,
            "products_skipped_invalid_identity": skipped_invalid_identity,
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
