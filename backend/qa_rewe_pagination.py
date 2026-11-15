"""Deterministic pagination regression QA across every configured REWE category."""
from urllib.parse import parse_qs, urlsplit

from app.rewe.scraper import REWE_CATEGORY_URLS, ReweCatalogScraper
from app.rewe_refresh import (
    _derive_rewe_unit_price, _minimum_safe_rewe_seen_count,
    _valid_rewe_checkout_price, _valid_rewe_package,
)


def product_page(category_path: str, page_number: int) -> str:
    product_id = f"{category_path.rsplit('/', 1)[-1]}-{page_number}"
    links = "".join(
        f'<a href="?page={n}">{n}</a>' for n in (1, 2, 3)
    )
    return (
        f'<html><body><article><a href="/shop/p/{product_id}">'
        f'Product {product_id}</a></article><nav>{links}'
        f'<a rel="next" href="?page={min(page_number + 1, 3)}">Weiter</a>'
        "</nav></body></html>"
    )


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        parsed = urlsplit(url)
        page = int(parse_qs(parsed.query).get("page", ["1"])[0])
        page = max(1, min(page, 3))
        return FakeResponse(product_page(parsed.path, page))


def main():
    assert _minimum_safe_rewe_seen_count(0) == 100
    assert _minimum_safe_rewe_seen_count(1000) == 900
    assert _minimum_safe_rewe_seen_count(12000) == 10800
    assert _valid_rewe_package({"package_size": 500, "package_unit": "g"}) is True
    assert _valid_rewe_package({"package_size": True, "package_unit": "g"}) is False
    assert _valid_rewe_package({"package_size": float("inf"), "package_unit": "g"}) is False
    assert _valid_rewe_package({"package_size": 0, "package_unit": "g"}) is False
    assert _valid_rewe_package({"package_size": 500, "package_unit": "unknown"}) is False
    assert _valid_rewe_checkout_price({"price": 2.49}) is True
    assert _valid_rewe_checkout_price({"price": True}) is False
    assert _valid_rewe_checkout_price({"price": float("nan")}) is False
    assert _valid_rewe_checkout_price({"price": 0}) is False
    assert _derive_rewe_unit_price(2.50, 500) == 0.005
    assert _derive_rewe_unit_price(2.50, 0) is None
    assert _derive_rewe_unit_price(True, 500) is None
    scraper = ReweCatalogScraper(delay=0, browser_enabled=False)
    session = FakeSession()
    scraper.session = session

    total_pages = 0
    browser_pages = 0
    scraper._browser_category_html = lambda page, url: product_page(
        urlsplit(url).path, int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
    )

    for category_url in REWE_CATEGORY_URLS:
        pages = list(scraper.pages(category_url))
        urls = [url for url, _ in pages]
        assert len(urls) == 3, (
            f"HTTP {category_url}: expected pages 1, 2, 3, got {urls}"
        )
        assert len(urls) == len(set(urls)), (
            f"HTTP {category_url}: duplicate page URLs: {urls}"
        )
        assert len({scraper._page_fingerprint(html) for _, html in pages}) == 3, (
            f"HTTP {category_url}: duplicate page content"
        )
        total_pages += len(pages)

        browser_result = list(scraper._browser_category_pages(object(), category_url))
        browser_urls = [url for url, _ in browser_result]
        assert len(browser_urls) == 3, (
            f"Browser {category_url}: expected pages 1, 2, 3, got {browser_urls}"
        )
        assert len(browser_urls) == len(set(browser_urls)), (
            f"Browser {category_url}: duplicate page URLs: {browser_urls}"
        )
        assert len({scraper._page_fingerprint(html) for _, html in browser_result}) == 3, (
            f"Browser {category_url}: duplicate page content"
        )
        browser_pages += len(browser_result)

    assert len(REWE_CATEGORY_URLS) == 17, (
        f"Expected 17 configured category URLs, found {len(REWE_CATEGORY_URLS)}"
    )
    assert len(session.calls) == total_pages == 51, (
        f"Expected exactly 51 unique HTTP page requests, got {len(session.calls)}"
    )
    assert browser_pages == 51, (
        f"Expected exactly 51 unique browser page navigations, got {browser_pages}"
    )

    # Never silently treat a category as complete when pagination exceeds the
    # configured safety cap. That could otherwise allow stale-product deletion.
    class LongSession:
        def get(self, url, **kwargs):
            page_number = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
            return FakeResponse(f"<html><body>Unique catalog page {page_number}</body></html>")

    long_scraper = ReweCatalogScraper(delay=0, browser_enabled=False)
    long_scraper.session = LongSession()

    def next_long_page(html, current, start):
        page_number = int(parse_qs(urlsplit(current).query).get("page", ["1"])[0])
        return [f"{start}?page={page_number + 1}"] if page_number < 51 else []

    long_scraper._pagination_links = next_long_page
    try:
        list(long_scraper.pages(REWE_CATEGORY_URLS[0]))
        raise AssertionError("HTTP pagination cap must fail closed")
    except RuntimeError as exc:
        assert "pagination did not complete" in str(exc)

    long_scraper._browser_category_html = lambda page, url: (
        f"<html><body>Unique browser catalog page "
        f"{parse_qs(urlsplit(url).query).get('page', ['1'])[0]}</body></html>"
    )
    try:
        list(long_scraper._browser_category_pages(object(), REWE_CATEGORY_URLS[0]))
        raise AssertionError("Browser pagination cap must fail closed")
    except RuntimeError as exc:
        assert "pagination did not complete" in str(exc)

    # Repeated page bodies are also failures, not successful early termination.
    repeated = ReweCatalogScraper(delay=0, browser_enabled=False)
    repeated.session = type(
        "RepeatedSession", (), {"get": lambda self, url, **kwargs: FakeResponse("<html><body>same</body></html>")}
    )()
    repeated._pagination_links = lambda html, current, start: [f"{start}?page=2"] if "page=2" not in current else []
    try:
        list(repeated.pages(REWE_CATEGORY_URLS[0]))
        raise AssertionError("Repeated page content must fail closed")
    except RuntimeError as exc:
        assert "repeated page content" in str(exc)

    print(
        "REWE pagination regression QA: "
        f"{len(REWE_CATEGORY_URLS)} categories, {total_pages} HTTP pages and "
        f"{browser_pages} browser pages, no repeated URLs or page content"
    )


if __name__ == "__main__":
    main()
