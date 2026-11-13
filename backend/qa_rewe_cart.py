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
from app.rewe.scraper import _canonical_product_url, _cart_add_status


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


def test_rewe_cart_dom_probe_contract():
    from playwright.sync_api import sync_playwright, Error as PlaywrightError
    from app.rewe.scraper import _rewe_add_button_index, _rewe_cart_stepper_snapshot

    html = """
    <header>
      <button aria-label="Warenkorb" style="width:48px;height:48px;background:white">
        <svg aria-label="cart" viewBox="0 0 24 24"><path d="M2 2h2l2 10h12"/></svg>
      </button>
    </header>
    <main>
      <h1>QA product</h1>
      <div id="purchase">
        <button id="add" aria-label="In den Warenkorb" style="width:160px;height:48px;background:rgb(220,20,30);color:white">
          <svg class="icon-cart-plus" viewBox="0 0 24 24"><path d="M2 2h2l2 10h12M12 5v8M8 9h8"/></svg>
        </button>
      </div>
    </main>
    <script>
      document.getElementById('add').addEventListener('click', () => {
        document.getElementById('purchase').innerHTML =
          '<div id="stepper"><button aria-label="Weniger">−</button><span id="quantity">1</span><button aria-label="Mehr">+</button></div>';
        const stepper=document.getElementById('stepper');
        stepper.querySelector('[aria-label="Mehr"]').addEventListener('click',()=>{document.getElementById('quantity').textContent=String(Number(document.getElementById('quantity').textContent)+1)});
        stepper.querySelector('[aria-label="Weniger"]').addEventListener('click',()=>{document.getElementById('quantity').textContent=String(Math.max(0,Number(document.getElementById('quantity').textContent)-1))});
      });
    </script>
    """
    endpoint = os.getenv(
        "BITEWISE_CHROME_CDP_URL",
        os.getenv("REWE_CHROME_CDP_URL", "http://127.0.0.1:9222"),
    ).rstrip("/")
    with sync_playwright() as playwright:
        # Prefer the developer's Chrome for Testing session locally. GitHub
        # Actions has no user CDP process, so use its installed headless Chromium.
        owns_context = False
        try:
            browser = playwright.chromium.connect_over_cdp(endpoint, timeout=1_500)
            if not browser.contexts:
                raise AssertionError(f"Chrome for Testing at {endpoint} has no browser context")
            context = browser.contexts[0]
        except PlaywrightError:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            owns_context = True
        page = None
        try:
            page = context.new_page()
            page.set_content(html)
            add_index = _rewe_add_button_index(page)
            assert add_index is not None
            page.locator("button, [role='button']").nth(add_index).click()
            state = _rewe_cart_stepper_snapshot(page)
            assert state and state["quantity"] == 1
            for _ in range(2):
                state = _rewe_cart_stepper_snapshot(page)
                page.locator("button, [role='button']").nth(state["plus_index"]).click()
            state = _rewe_cart_stepper_snapshot(page)
            assert state and state["quantity"] == 3
        finally:
            if page:
                page.close()
            if owns_context:
                context.close()
            # For CDP this only disconnects; for CI it also closes the
            # headless Chromium process started by this test.
            browser.close()


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
    test_rewe_cart_dom_probe_contract()
    test_cart_endpoint_only_hands_off_valid_rewe_catalog_products()
    print("REWE cart handoff QA PASS: HTTPS URL allowlist, truthful quantity status, endpoint product filtering, no checkout")


if __name__ == "__main__":
    main()
