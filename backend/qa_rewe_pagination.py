"""Deterministic pagination regression QA across every configured REWE category."""
from urllib.parse import parse_qs, urlsplit

from app.rewe.scraper import REWE_CATEGORY_URLS, ReweCatalogScraper


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
    scraper = ReweCatalogScraper(delay=0, browser_enabled=False)
    session = FakeSession()
    scraper.session = session

    total_pages = 0
    for category_url in REWE_CATEGORY_URLS:
        pages = list(scraper.pages(category_url))
        urls = [url for url, _ in pages]
        assert len(urls) == 3, (
            f"{category_url}: expected pages 1, 2, 3, got {urls}"
        )
        assert len(urls) == len(set(urls)), (
            f"{category_url}: duplicate page URLs: {urls}"
        )
        assert len({scraper._page_fingerprint(html) for _, html in pages}) == 3, (
            f"{category_url}: duplicate page content"
        )
        total_pages += len(pages)

    assert len(REWE_CATEGORY_URLS) == 17, (
        f"Expected 17 configured category URLs, found {len(REWE_CATEGORY_URLS)}"
    )
    assert len(session.calls) == total_pages == 51, (
        f"Expected exactly 51 unique page requests, got {len(session.calls)}"
    )
    print(
        "REWE pagination regression QA: "
        f"{len(REWE_CATEGORY_URLS)} categories, {total_pages} unique pages, "
        "no repeated URLs or repeated page content"
    )


if __name__ == "__main__":
    main()
