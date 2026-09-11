"""REWE package bootstrap patches for direct category pagination."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import scraper as _scraper


def _page_url(start: str, page_number: int) -> str:
    parts = urlsplit(start)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _direct_browser_category_pages(self, page, start):
    """Open REWE category URLs directly as ?page=N until a page has no products.

    This deliberately avoids clicking REWE pagination controls and avoids opening
    the generic /shop/ landing page first. Page 1 uses ?page=1 as well, so every
    request follows the same deterministic URL pattern.
    """
    previous_ids = set()
    for page_number in range(1, _scraper.MAX_CATEGORY_PAGES + 1):
        current = _page_url(start, page_number)
        html = self._browser_category_html(page, current)
        category = start.rstrip("/").split("/")[-1] or "bonus"
        products = self.extract(html, current, category)
        ids = {p.get("external_id") for p in products if p.get("external_id")}

        # REWE can redirect an out-of-range page back to a previous page. Treat a
        # page with no products OR no new product ids as the end of pagination.
        if not products or (previous_ids and ids and ids.issubset(previous_ids)):
            break
        previous_ids.update(ids)
        yield current, html


def _run_browser_direct(self, upsert, postcode, urls):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright browser fallback is not installed") from exc

    report = self._base_report(postcode, "playwright-direct-pages")
    headless = _scraper.os.getenv("REWE_BROWSER_HEADLESS", "true").lower() not in {"0", "false", "no"}
    with sync_playwright() as pw:
        launch_args = {
            "headless": headless,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }
        channel = _scraper.os.getenv("REWE_BROWSER_CHANNEL", "").strip()
        if channel:
            launch_args["channel"] = channel
        try:
            browser = pw.chromium.launch(**launch_args)
        except Exception:
            launch_args.pop("channel", None)
            browser = pw.chromium.launch(**launch_args)

        context_args = {
            "locale": "de-DE",
            "user_agent": _scraper.HEADERS["User-Agent"],
            "viewport": {"width": 1440, "height": 1000},
        }
        # Reuse the last valid REWE browser state when available, but do not
        # navigate to the generic shop landing page just to set location.
        if _scraper.STATE_FILE.exists():
            context_args["storage_state"] = str(_scraper.STATE_FILE)

        context = browser.new_context(**context_args)
        page = context.new_page()
        try:
            for start in urls:
                report["categories_processed"] += 1
                category = start.rstrip("/").split("/")[-1] or "bonus"
                try:
                    by_id = {}
                    for page_url, html in self._browser_category_pages(page, start):
                        report["pages_processed"] += 1
                        page_products = self.extract(html, page_url, category)
                        if not page_products:
                            break
                        for product in page_products:
                            current = by_id.get(product["external_id"])
                            if current is None or (not current.get("product_url") and product.get("product_url")):
                                by_id[product["external_id"]] = product

                    products = list(by_id.values())
                    if not products:
                        raise RuntimeError("No products found on direct REWE category pages")
                    self._ingest_products(report, products, upsert, postcode)
                    report["categories_successful"] += 1
                except Exception as exc:
                    report["categories_failed"] += 1
                    report["errors"].append({"category": category, "error": str(exc)[:300]})
        finally:
            try:
                context.storage_state(path=str(_scraper.STATE_FILE))
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    report["status"] = "failed" if not report["categories_successful"] else ("partial" if report["categories_failed"] else "healthy")
    return report


_scraper.ReweCatalogScraper._browser_category_pages = _direct_browser_category_pages
_scraper.ReweCatalogScraper._run_browser = _run_browser_direct
