"""REWE package bootstrap patch for deterministic direct category pagination.

Keep the browser transport in scraper.py: it attaches to Chrome for Testing over
CDP. This module must not override it with Playwright's chromium.launch().
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import scraper as _scraper


def _page_url(start: str, page_number: int) -> str:
    parts = urlsplit(start)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _direct_browser_category_pages(self, page, start):
    """Visit category pages directly until REWE stops returning new products."""
    previous_ids = set()
    for page_number in range(1, _scraper.MAX_CATEGORY_PAGES + 1):
        current = _page_url(start, page_number)
        html = self._browser_category_html(page, current)
        category = start.rstrip("/").split("/")[-1] or "bonus"
        products = self.extract(html, current, category)
        ids = {p.get("external_id") for p in products if p.get("external_id")}
        if not products or (previous_ids and ids and ids.issubset(previous_ids)):
            break
        previous_ids.update(ids)
        yield current, html


# Preserve the CDP connection implementation in scraper.py. Do not replace it
# with chromium.launch(), which expects a Playwright-managed browser binary.
_scraper.ReweCatalogScraper._browser_category_pages = _direct_browser_category_pages
