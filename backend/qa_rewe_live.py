"""Live REWE delivery QA for all configured categories and discovered pages.

Run locally with the user's authenticated Chrome for Testing session. REWE may
block cloud CI IPs; the workflow therefore marks this external smoke test
continue-on-error while the deterministic pagination QA remains mandatory.
"""
from app.rewe.scraper import REWE_CATEGORY_URLS, ReweCatalogScraper

POSTCODE = "13353"


def main():
    scraper = ReweCatalogScraper(delay=0.2, browser_enabled=True)
    all_products = []
    category_reports = []

    for url in REWE_CATEGORY_URLS:
        category = url.rstrip("/").split("/")[-1] or "bonus"
        products = []
        def collect(product, postcode):
            assert postcode == POSTCODE
            products.append(product)
            all_products.append(product)
            return True

        report = scraper.run(collect, POSTCODE, urls=[url])
        category_reports.append((category, report, len(products)))
        priced = sum(row.get("price") is not None for row in products)
        coverage = priced / len(products) if products else 0
        print(
            f"{category}: status={report.get('status')} "
            f"mode={report.get('fetch_mode')} pages={report.get('pages_processed')} "
            f"products={len(products)} priced={priced} "
            f"price_coverage={coverage:.1%} errors={report.get('errors', [])[:2]}"
        )

    successful = sum(report.get("status") != "failed" for _, report, _ in category_reports)
    pages = sum(report.get("pages_processed", 0) for _, report, _ in category_reports)
    priced = sum(row.get("price") is not None for row in all_products)
    coverage = priced / len(all_products) if all_products else 0
    print(
        "REWE full catalog QA: "
        f"categories={len(category_reports)} successful={successful} "
        f"pages={pages} products={len(all_products)} "
        f"priced={priced} price_coverage={coverage:.1%}"
    )

    assert len(category_reports) == 17
    assert successful > 0, "No REWE categories could be scraped"
    assert len(all_products) >= 20, "No meaningful product catalog was extracted"
    assert coverage >= 0.25, (
        f"REWE delivery session did not expose enough localized prices: {coverage:.1%}"
    )


if __name__ == "__main__":
    main()
