"""REWE package bootstrap patches for resilient location selection and pagination."""
from __future__ import annotations

import hashlib
import re

from . import scraper as _scraper


def _editable_postcode_input(scope):
    """Return only a visible, editable postcode field.

    REWE renders a visible readonly postcode summary before the actual location
    editor opens. Skip readonly/disabled fields so Playwright can open the real
    editor and only call fill() on an editable control.
    """
    selectors = [
        'input[autocomplete="postal-code"]',
        'input[inputmode="numeric"]',
        'input[placeholder*="Postleitzahl" i]',
        'input[placeholder*="PLZ" i]',
        'input[name*="postal" i]',
        'input[name*="postcode" i]',
        'input[name*="zip" i]',
        'input[id*="postal" i]',
        'input[id*="postcode" i]',
    ]

    candidates = []
    try:
        labelled = scope.get_by_label(re.compile(r"Postleitzahl|PLZ", re.I)).first
        if labelled.count():
            candidates.append(labelled)
    except Exception:
        pass

    for selector in selectors:
        try:
            locator = scope.locator(selector).first
            if locator.count():
                candidates.append(locator)
        except Exception:
            pass

    for locator in candidates:
        try:
            if not locator.is_visible():
                continue
            if locator.get_attribute("readonly") is not None:
                continue
            if locator.get_attribute("disabled") is not None:
                continue
            if not locator.is_editable(timeout=500):
                continue
            return locator
        except Exception:
            continue
    return None


def _load_current_category_html(page):
    """Finish lazy-loading the currently open REWE category without navigating away."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass

    previous_height = 0
    for _ in range(10):
        _scraper._click_first(page, [r"Mehr laden", r"Mehr anzeigen", r"Weitere Produkte"], timeout=600)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(400)
            height = page.evaluate("document.body.scrollHeight")
        except Exception:
            break
        if height == previous_height:
            break
        previous_height = height
    return page.content()


def _page_fingerprint(html: str) -> str:
    """Use product-detail links to tell whether pagination actually changed products."""
    links = re.findall(r'href=["\']([^"\']*/shop/p/[^"\']+)["\']', html, flags=re.I)
    stable = "\n".join(sorted(set(links))[:200])
    if not stable:
        stable = re.sub(r"\s+", " ", html)[:12000]
    return hashlib.sha256(stable.encode("utf-8", errors="ignore")).hexdigest()


def _current_page_number(page, fallback: int) -> int:
    selectors = [
        '[aria-current="page"]',
        '[aria-current="true"]',
        '[data-current="true"]',
        '[class*="active" i][class*="page" i]',
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector)
            for i in range(min(locator.count(), 8)):
                item = locator.nth(i)
                if not item.is_visible():
                    continue
                text = (item.inner_text(timeout=400) or "").strip()
                match = re.fullmatch(r"\D*(\d+)\D*", text)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
    return fallback


def _click_next_pagination(page, current_number: int) -> bool:
    """Click REWE's real pagination control, independent of vertical position.

    REWE can render pagination as JS buttons rather than hrefs. First try semantic
    next controls, then fall back to clicking the visible numeric control for the
    next page. scroll_into_view_if_needed() means the pager can sit anywhere in
    the document; it does not need to be at the bottom.
    """
    semantic_selectors = [
        'a[rel="next"]',
        'button[aria-label*="nächste" i]',
        'a[aria-label*="nächste" i]',
        'button[aria-label*="naechste" i]',
        'a[aria-label*="naechste" i]',
        'button[aria-label*="weiter" i]',
        'a[aria-label*="weiter" i]',
        'button[title*="nächste" i]',
        'a[title*="nächste" i]',
        'button[title*="weiter" i]',
        'a[title*="weiter" i]',
    ]
    for selector in semantic_selectors:
        try:
            locator = page.locator(selector)
            for i in range(min(locator.count(), 8)):
                item = locator.nth(i)
                if not item.is_visible() or not item.is_enabled():
                    continue
                item.scroll_into_view_if_needed(timeout=1500)
                item.click(timeout=2500)
                return True
        except Exception:
            continue

    wanted = str(current_number + 1)
    candidates = page.locator("button, a")
    numeric = []
    try:
        count = min(candidates.count(), 1000)
    except Exception:
        count = 0
    for i in range(count):
        item = candidates.nth(i)
        try:
            if not item.is_visible() or not item.is_enabled():
                continue
            text = (item.inner_text(timeout=250) or "").strip()
            if text == wanted:
                numeric.append(item)
        except Exception:
            continue

    # Prefer a candidate living in something that looks like pagination.
    ordered = []
    for item in numeric:
        try:
            looks_like_pager = item.evaluate(
                """el => {
                    let n = el;
                    for (let i = 0; i < 6 && n; i++, n = n.parentElement) {
                        const meta = [n.tagName, n.className, n.id,
                          n.getAttribute && n.getAttribute('aria-label'),
                          n.getAttribute && n.getAttribute('data-testid')]
                          .filter(Boolean).join(' ').toLowerCase();
                        if (/pagin|seite|page/.test(meta) || n.tagName === 'NAV') return true;
                    }
                    return false;
                }"""
            )
            if looks_like_pager:
                ordered.insert(0, item)
            else:
                ordered.append(item)
        except Exception:
            ordered.append(item)

    for item in ordered:
        try:
            item.scroll_into_view_if_needed(timeout=1500)
            item.click(timeout=2500)
            return True
        except Exception:
            continue
    return False


def _interactive_browser_category_pages(self, page, start):
    """Traverse every category page by clicking the UI pager instead of guessing URLs."""
    response = page.goto(start, wait_until="domcontentloaded", timeout=45000)
    if response and response.status >= 400:
        raise RuntimeError(f"REWE category returned HTTP {response.status}")

    seen_fingerprints = set()
    expected_page = 1

    for _ in range(_scraper.MAX_CATEGORY_PAGES):
        html = _load_current_category_html(page)
        fingerprint = _page_fingerprint(html)
        if fingerprint in seen_fingerprints:
            break
        seen_fingerprints.add(fingerprint)

        current_number = _current_page_number(page, expected_page)
        yield page.url or f"{start}#page-{current_number}", html

        if not _click_next_pagination(page, current_number):
            break

        previous_url = page.url
        page.wait_for_timeout(900)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        # Wait briefly for either URL or product content to change. This also
        # supports SPA pagination where the URL remains exactly the same.
        changed = False
        for _ in range(12):
            page.wait_for_timeout(250)
            try:
                probe_html = page.content()
                if page.url != previous_url or _page_fingerprint(probe_html) != fingerprint:
                    changed = True
                    break
            except Exception:
                pass
        if not changed:
            break
        expected_page = current_number + 1


_scraper._visible_postcode_input = _editable_postcode_input
_scraper.ReweCatalogScraper._browser_category_pages = _interactive_browser_category_pages
