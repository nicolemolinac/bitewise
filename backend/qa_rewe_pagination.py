"""Deterministic pagination regression QA across every configured REWE category."""
from urllib.parse import parse_qs, urlsplit

from app.rewe.scraper import REWE_CATEGORY_URLS, ReweCatalogScraper, category_slug_from_url


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


def compact_page(category_path: str, page_number: int) -> str:
    product_id = f"{category_path.rsplit('/', 1)[-1]}-long-{page_number}"
    # Mirrors REWE's compact pagination strip: 1, 2, 3, …, last page.
    links = "".join(f'<a href="?page={n}">{n}</a>' for n in (1, 2, 3, 139))
    return (
        f'<html><body><article><a href="/shop/p/{product_id}">'
        f'Product {product_id}</a></article><nav>{links}</nav></body></html>'
    )


class LongPaginationSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        parsed = urlsplit(url)
        page = int(parse_qs(parsed.query).get("page", ["1"])[0])
        return FakeResponse(compact_page(parsed.path, page))


def main():
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

    # REWE's real category pages use compact strips like 1, 2, 3, …, 139.
    # The scraper must request pages 4–138 sequentially instead of jumping to 139.
    long_scraper = ReweCatalogScraper(delay=0, browser_enabled=False)
    long_session = LongPaginationSession()
    long_scraper.session = long_session
    long_url = "https://www.rewe.de/shop/c/backwaren-cerealien-aufstriche/"
    long_pages = list(long_scraper.pages(long_url))
    assert len(long_pages) == 139, f"Expected all 139 REWE pages, got {len(long_pages)}"
    assert len(long_session.calls) == 139
    assert long_scraper._page_number(long_session.calls[3]) == 4
    assert long_scraper._page_number(long_session.calls[-1]) == 139

    browser_long = ReweCatalogScraper(delay=0, browser_enabled=False)
    browser_long._browser_category_html = lambda page, url: compact_page(
        urlsplit(url).path, int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
    )
    browser_long_pages = list(browser_long._browser_category_pages(object(), long_url))
    assert len(browser_long_pages) == 139, (
        f"Expected browser pagination to cover all 139 pages, got {len(browser_long_pages)}"
    )

    # Repeated content and the hard page cap must fail closed, not masquerade as
    # a complete category (which could trigger destructive stale-product cleanup).
    duplicate_scraper = ReweCatalogScraper(delay=0, browser_enabled=False)
    duplicate_scraper.session = type("DuplicateSession", (), {
        "get": lambda self, url, **kwargs: FakeResponse(product_page(urlsplit(url).path, 1))
    })()
    try:
        list(duplicate_scraper.pages(REWE_CATEGORY_URLS[0]))
        raise AssertionError("Repeated pagination content must raise")
    except RuntimeError as exc:
        assert "repeated page content" in str(exc).lower()

    import app.rewe.scraper as scraper_module
    original_limit = scraper_module.MAX_CATEGORY_PAGES
    try:
        scraper_module.MAX_CATEGORY_PAGES = 2
        capped_scraper = ReweCatalogScraper(delay=0, browser_enabled=False)
        capped_scraper.session = FakeSession()
        try:
            list(capped_scraper.pages(REWE_CATEGORY_URLS[0]))
            raise AssertionError("Hitting the pagination cap with pages pending must raise")
        except RuntimeError as exc:
            assert "safety limit" in str(exc).lower()

        browser_duplicate = ReweCatalogScraper(delay=0, browser_enabled=False)
        browser_duplicate._browser_category_html = lambda page, url: product_page(urlsplit(url).path, 1)
        try:
            list(browser_duplicate._browser_category_pages(object(), REWE_CATEGORY_URLS[0]))
            raise AssertionError("Browser repeated pagination content must raise")
        except RuntimeError as exc:
            assert "repeated page content" in str(exc).lower()
    finally:
        scraper_module.MAX_CATEGORY_PAGES = original_limit

    current_bread_category = "https://www.rewe.de/shop/c/backwaren-cerealien-aufstriche/"
    assert current_bread_category in REWE_CATEGORY_URLS
    assert "https://www.rewe.de/shop/c/brot-cerealien-aufstriche/" not in REWE_CATEGORY_URLS
    assert category_slug_from_url(current_bread_category) == "brot-cerealien-aufstriche"
    assert category_slug_from_url(REWE_CATEGORY_URLS[0]) == "bonus"
    assert scraper_module.MAX_CATEGORY_PAGES >= 150, (
        "The current REWE bread/cereals parent department spans 139 pages; "
        "the scraper safety cap must not silently make that category incomplete."
    )
    assert len(REWE_CATEGORY_URLS) == 17, (
        f"Expected 17 configured category URLs, found {len(REWE_CATEGORY_URLS)}"
    )
    assert len(session.calls) == total_pages == 51, (
        f"Expected exactly 51 unique HTTP page requests, got {len(session.calls)}"
    )
    assert browser_pages == 51, (
        f"Expected exactly 51 unique browser page navigations, got {browser_pages}"
    )
    print(
        "REWE pagination regression QA: "
        f"{len(REWE_CATEGORY_URLS)} categories, {total_pages} HTTP pages and "
        f"{browser_pages} browser pages, no repeated URLs or page content"
    )


if __name__ == "__main__":
    main()
