from app.rewe.scraper import ReweCatalogScraper

URL = "https://www.rewe.de/shop/c/obst-gemuese/"


def main():
    scraper = ReweCatalogScraper(delay=0)
    first_page = next(scraper.pages(URL))
    url, html = first_page
    products = scraper.extract(html, url, "obst-gemuese")
    assert len(products) >= 20, f"Expected product cards from REWE, got {len(products)}"
    priced = [row for row in products if row.get("price") is not None]
    coverage = len(priced) / len(products)
    print(f"REWE live QA: products={len(products)} priced={len(priced)} price_coverage={coverage:.1%}")
    if coverage < 0.25:
        raise AssertionError(
            "REWE public category HTML does not expose enough location-specific prices. "
            "The current HTTP scraper can discover products, but postcode/store context needs a browser/session fallback."
        )


if __name__ == "__main__":
    main()
