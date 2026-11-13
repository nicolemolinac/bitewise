"""Regression QA: partial REWE refreshes must not erase valid saved product facts.

Run from backend/: python qa_rewe_refresh_merge.py
"""
import os
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-rewe-refresh-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "qa.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "false"

from app.rewe_refresh import _merge_rewe_product_data
from app.server import app as server_app


def product():
    return SimpleNamespace(
        price=2.49, last_price=None, price_per_unit=0.00498,
        package_size=500.0, package_unit="g", product_url="https://www.rewe.de/shop/p/test/1",
        image_url="https://img.rewe.de/test.jpg", brand="REWE Bio",
        category="Obst & Gemüse", name_original="Bio Reis 500g",
        name_normalized="bio reis 500g", ingredient="bio reis",
        availability="available", postcode_context="13353",
        last_seen_at=None, last_checked_at=None,
    )


def main():
    refresh_routes = [
        route for route in server_app.routes
        if getattr(route, "path", None) == "/api/rewe/refresh"
        and "POST" in (getattr(route, "methods", set()) or set())
    ]
    assert len(refresh_routes) == 1, (
        f"Expected one REWE refresh route, found {len(refresh_routes)}"
    )
    assert refresh_routes[0].endpoint.__name__ == "rewe_refresh"
    import inspect
    assert "rewe_refresh_safe" in inspect.getsource(refresh_routes[0].endpoint), (
        "The active API route must delegate to the guarded partial-refresh merge"
    )

    now = datetime(2026, 11, 13, 12, 0, 0)
    existing = product()
    _merge_rewe_product_data(existing, {
        "price": None, "price_per_unit": None,
        "package_size": 1, "package_unit": "unknown",
        "product_url": None, "image_url": None,
        "brand": None, "category": None,
        "name_original": "Bio Reis 500g", "availability": "unknown",
    }, "13353", now)
    assert existing.price == 2.49
    assert existing.price_per_unit == 0.00498
    assert existing.package_size == 500 and existing.package_unit == "g"
    assert existing.product_url and existing.image_url
    assert existing.brand == "REWE Bio" and existing.category == "Obst & Gemüse"
    assert existing.last_price is None
    assert existing.last_seen_at == now and existing.last_checked_at == now

    invalid_update = product()
    _merge_rewe_product_data(invalid_update, {
        "price": float("nan"), "price_per_unit": float("inf"),
        "package_size": float("nan"), "package_unit": "g",
    }, "13353", now)
    assert invalid_update.price == 2.49
    assert invalid_update.price_per_unit == 0.00498
    assert invalid_update.package_size == 500 and invalid_update.package_unit == "g"

    # A new trustworthy checkout price updates price history but keeps the
    # previous known pack size when the current card failed to expose it.
    _merge_rewe_product_data(existing, {
        "price": 2.99, "price_per_unit": None,
        "package_size": 1, "package_unit": "unknown",
        "product_url": None, "image_url": None,
    }, "13353", now)
    assert existing.price == 2.99 and existing.last_price == 2.49
    assert existing.package_size == 500 and existing.package_unit == "g"
    assert abs(existing.price_per_unit - 0.00598) < 1e-9

    # The scraper can parse a checkout price but only a fallback 1 x unknown
    # pack size. Ignore its apparently valid unit price and recompute against
    # the previously verified package size.
    partial_size_update = product()
    _merge_rewe_product_data(partial_size_update, {
        "price": 2.99, "price_per_unit": 2.99,
        "package_size": 1, "package_unit": "unknown",
    }, "13353", now)
    assert partial_size_update.price == 2.99
    assert partial_size_update.package_size == 500 and partial_size_update.package_unit == "g"
    assert abs(partial_size_update.price_per_unit - 0.00598) < 1e-9

    # A valid, complete package update is accepted together with its new price.
    _merge_rewe_product_data(existing, {
        "price": 3.49, "price_per_unit": 0.00698,
        "package_size": 500, "package_unit": "g",
    }, "13353", now)
    assert existing.price == 3.49 and existing.last_price == 2.99
    assert existing.package_size == 500 and existing.package_unit == "g"
    assert existing.price_per_unit == 0.00698

    print("REWE refresh merge QA PASS: partial cards preserve known prices, pack sizes and product links")


if __name__ == "__main__":
    main()
