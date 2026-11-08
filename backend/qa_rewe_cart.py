"""Offline contract and route QA for safe REWE cart handoff.

Uses a temporary SQLite database and a mocked CDP handoff. It never touches a
developer's REWE session, persistent catalog, or hosted database.
"""
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

_QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-rewe-cart-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_QA_TEMP.name) / "qa.sqlite")
os.environ["BITEWISE_AI_MEALS_PATH"] = str(Path(_QA_TEMP.name) / "ai_meals.json")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_PUBLISHABLE_KEY"] = ""

from fastapi.testclient import TestClient

from app import server
from app.database import Product, SessionLocal
from app.rewe.scraper import (
    _canonical_product_url,
    _cart_add_status,
    _cart_quantity_submission_allowed,
    _cart_quantity_matches,
)


def test_url_and_status_contract():
    assert _canonical_product_url("https://www.rewe.de/shop/p/test-product/123456") == "https://www.rewe.de/shop/p/test-product/123456"
    assert _canonical_product_url("https://rewe.de/shop/p/test-product/123456?foo=bar") == "https://rewe.de/shop/p/test-product/123456?foo=bar"
    for unsafe in (
        "https://evil.example/shop/p/test/1",
        "https://www.rewe.de/shop/c/tiefkuehlkost/",
        "https://www.rewe.de/not-a-product/shop/p/fake/123456",
        "javascript:alert(1)",
        "https://rewe.de.evil.example/shop/p/test/1",
        "https://evilrewe.de/shop/p/test/1",
        "http://www.rewe.de/shop/p/test/1",
        "",
    ):
        assert _canonical_product_url(unsafe) is None, unsafe

    assert _cart_add_status(True, 1) == "added"
    assert _cart_add_status(True, 3) == "quantity_unconfirmed"
    assert _cart_add_status(False, 1) == "submitted_unverified"
    assert _cart_quantity_submission_allowed(False, 1) is True
    assert _cart_quantity_submission_allowed(False, 2) is False
    assert _cart_quantity_submission_allowed(True, 2) is True
    assert _cart_quantity_matches("2", 2) is True
    assert _cart_quantity_matches(" 2 ", 2) is True
    assert _cart_quantity_matches("1", 2) is False
    assert _cart_quantity_matches("2.0", 2) is False
    assert _cart_quantity_matches("", 2) is False


def test_cart_endpoint_only_hands_off_valid_rewe_catalog_products():
    db = SessionLocal()
    try:
        rewe_product = Product(
            supermarket="REWE",
            external_id="qa-rewe-salmon-001",
            ingredient="salmon",
            name_original="QA Salmon Fillet",
            name_normalized="qa salmon fillet",
            package_size=1,
            package_unit="pack",
            price=4.25,
            product_url="https://www.rewe.de/shop/p/qa-salmon/123456",
        )
        other_product = Product(
            supermarket="OTHER",
            external_id="qa-other-salmon-001",
            ingredient="salmon",
            name_original="Other Salmon",
            name_normalized="other salmon",
            package_size=1,
            package_unit="pack",
            price=3.50,
            product_url="https://example.com/shop/p/salmon",
        )
        db.add_all([rewe_product, other_product])
        db.commit()
        db.refresh(rewe_product)
        db.refresh(other_product)
        rewe_id, other_id = rewe_product.id, other_product.id
    finally:
        db.close()

    handed_off = []

    def fake_handoff(_scraper, products):
        handed_off.extend(products)
        return {"results": [{"name": products[0]["name"], "status": "added"}], "checkout_performed": False}

    client = TestClient(server.app)
    with patch("app.rewe.scraper.ReweCatalogScraper.add_products_to_cart", fake_handoff):
        response = client.post("/api/rewe/cart/add", json={
            "items": [
                {"product_id": rewe_id, "packs": 2},
                {"product_id": other_id, "packs": 4},
                {"product_id": 99999999, "packs": 1},
            ]
        })
        assert response.status_code == 200, response.text
        assert response.json()["checkout_performed"] is False
        assert handed_off == [{
            "name": "QA Salmon Fillet",
            "product_url": "https://www.rewe.de/shop/p/qa-salmon/123456",
            "packs": 2,
        }]

        invalid = client.post("/api/rewe/cart/add", json={"items": [{"product_id": other_id, "packs": 1}]})
        assert invalid.status_code == 422, invalid.text
        assert len(handed_off) == 1, "Invalid catalog rows must never reach the CDP handoff"

        empty = client.post("/api/rewe/cart/add", json={"items": []})
        assert empty.status_code == 422, empty.text


def main():
    test_url_and_status_contract()
    test_cart_endpoint_only_hands_off_valid_rewe_catalog_products()
    print("REWE cart handoff QA PASS: HTTPS URL allowlist, truthful quantity status, endpoint product filtering, no checkout")


if __name__ == "__main__":
    main()
