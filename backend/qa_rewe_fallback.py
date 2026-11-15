"""Regression QA for partial HTTP catalog recovery through Chrome for Testing."""

from app.rewe.scraper import REWE_CATEGORY_URLS, ReweCatalogScraper


def _report(status, processed, successful, failed, pages, products, priced, errors=None):
    return {
        "status": status,
        "categories_processed": processed,
        "categories_successful": successful,
        "categories_failed": failed,
        "pages_processed": pages,
        "products_found": products,
        "products_with_price": priced,
        "products_created": products,
        "products_updated": 0,
        "errors": list(errors or []),
        "fetch_mode": "http",
    }


def main():
    urls = REWE_CATEGORY_URLS[:2]
    failed_category = urls[1].rstrip("/").split("/")[-1]
    scraper = ReweCatalogScraper(delay=0, browser_enabled=True)

    http = _report(
        "partial", 2, 1, 1, 3, 30, 18,
        [{"category": failed_category, "error": "HTTP 403"}],
    )
    browser = _report("healthy", 1, 1, 0, 2, 12, 11)
    calls = []
    scraper._run_http = lambda upsert, postcode, requested: http
    scraper._run_browser = lambda upsert, postcode, requested: (
        calls.append(list(requested)) or browser
    )

    result = scraper.run(lambda product, postcode: True, "13353", urls=urls)

    assert calls == [[urls[1]]], (
        "A partial HTTP result with sufficient price coverage must retry only failed categories"
    )
    assert result["status"] == "healthy"
    assert result["categories_processed"] == 2
    assert result["categories_successful"] == 2
    assert result["categories_failed"] == 0
    assert result["pages_processed"] == 5
    assert result["products_found"] == 42
    assert result["products_with_price"] == 29
    assert result["products_created"] == 42
    assert result["fetch_mode"] == "http+chrome-for-testing-cdp"

    # A fully healthy HTTP pass with sufficient price coverage remains the fast path.
    fast = ReweCatalogScraper(delay=0, browser_enabled=True)
    fast._run_http = lambda upsert, postcode, requested: _report(
        "healthy", 2, 2, 0, 4, 30, 20
    )
    browser_calls = []
    fast._run_browser = lambda *args: browser_calls.append(args) or {}
    fast_result = fast.run(lambda product, postcode: True, "13353", urls=urls)
    assert fast_result["fetch_mode"] == "http"
    assert not browser_calls

    print(
        "REWE partial fallback QA: failed categories retried via Chrome, "
        "HTTP/browser counts merged without duplicate category ingestion"
    )


if __name__ == "__main__":
    main()
