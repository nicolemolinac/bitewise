from app.rewe.scraper import ReweCatalogScraper

URL = "https://www.rewe.de/shop/c/obst-gemuese/"
POSTCODE = "13353"


def main():
    products = []

    def collect(product, postcode):
        assert postcode == POSTCODE
        products.append(product)
        return True

    scraper = ReweCatalogScraper(delay=0, browser_enabled=True)
    report = scraper.run(collect, POSTCODE, urls=[URL])
    priced = [row for row in products if row.get("price") is not None]
    coverage = len(priced) / len(products) if products else 0
    print(
        "REWE delivery QA:",
        f"mode={report.get('fetch_mode')}",
        f"service={report.get('service_type')}",
        f"postcode={report.get('postcode')}",
        f"products={len(products)}",
        f"priced={len(priced)}",
        f"price_coverage={coverage:.1%}",
    )
    assert report.get("service_type") == "delivery"
    assert report.get("postcode") == POSTCODE
    assert report.get("status") != "failed", report
    assert len(products) >= 20, f"Expected localized product cards from REWE, got {len(products)}; report={report}"
    assert coverage >= 0.25, (
        "REWE delivery session did not expose enough localized prices; "
        f"coverage={coverage:.1%}, report={report}"
    )


if __name__ == "__main__":
    main()
