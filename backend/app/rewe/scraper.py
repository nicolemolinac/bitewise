"""REWE catalog ingestion with HTTP fast path and resilient Playwright delivery fallback."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

REWE_CATEGORY_URLS = [
    "https://www.rewe.de/shop/bonus/",
    "https://www.rewe.de/shop/c/obst-gemuese/",
    "https://www.rewe.de/shop/c/fleisch-wurst-fisch/",
    "https://www.rewe.de/shop/c/kaese-eier-molkerei/",
    "https://www.rewe.de/shop/c/tiefkuehlkost/",
    "https://www.rewe.de/shop/c/brot-cerealien-aufstriche/",
    "https://www.rewe.de/shop/c/kochen-backen/",
    "https://www.rewe.de/shop/c/oele-sossen-gewuerze/",
    "https://www.rewe.de/shop/c/fertiggerichte-konserven/",
    "https://www.rewe.de/shop/c/suesses-salziges/",
    "https://www.rewe.de/shop/c/kaffee-tee-kakao/",
    "https://www.rewe.de/shop/c/getraenke-genussmittel/",
    "https://www.rewe.de/shop/c/drogerie-gesundheit/",
    "https://www.rewe.de/shop/c/baby-kind/",
    "https://www.rewe.de/shop/c/tierbedarf/",
    "https://www.rewe.de/shop/c/kueche-haushalt/",
    "https://www.rewe.de/shop/c/haus-freizeit/",
]

SHOP_DELIVERY_URL = "https://www.rewe.de/shop/?serviceTypes=delivery"
STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "rewe_storage_state.json"
MAX_CATEGORY_PAGES = 50

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.6",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", (value or "").lower()).strip()


def package(text: str):
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|stk|st\.|stück)", text, re.I)
    if not match:
        return None, None
    amount = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if unit == "kg":
        return amount * 1000, "g"
    if unit == "l":
        return amount * 1000, "ml"
    if unit in ("stk", "st.", "stück"):
        return amount, "unit"
    return amount, unit


def price(text: str):
    for pattern in (r"(?:€|EUR|Euro)\s*(\d+[,.]\d{2})", r"(\d+[,.]\d{2})\s*(?:€|EUR|Euro)"):
        match = re.search(pattern, text, re.I)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def _canonical_product_url(value: str | None, base_url: str = "") -> str | None:
    """Return only exact REWE product-detail URLs, never category/shop landing pages."""
    if not value:
        return None
    absolute = urljoin(base_url, value)
    parts = urlsplit(absolute)
    if parts.netloc not in {"www.rewe.de", "rewe.de"} or "/shop/p/" not in parts.path:
        return None
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, parts.query, ""))


def _json_ld_products(soup: BeautifulSoup, base_url: str, category: str):
    rows = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        queue = payload if isinstance(payload, list) else [payload]
        for node in queue:
            if not isinstance(node, dict):
                continue
            items = node.get("itemListElement") or []
            for item in items:
                candidate = item.get("item", item) if isinstance(item, dict) else None
                if not isinstance(candidate, dict) or candidate.get("@type") != "Product":
                    continue
                name = candidate.get("name") or ""
                raw_url = candidate.get("url") or ""
                product_url = _canonical_product_url(raw_url, base_url)
                offers = candidate.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                offer_price = offers.get("price") if isinstance(offers, dict) else None
                try:
                    offer_price = float(str(offer_price).replace(",", ".")) if offer_price is not None else None
                except Exception:
                    offer_price = None
                size, unit = package(f"{name} {candidate.get('description') or ''}")
                external_id = str(candidate.get("sku") or candidate.get("gtin13") or candidate.get("productID") or "")
                if not external_id:
                    external_id = hashlib.sha256(f"{name}|{product_url or raw_url}".encode()).hexdigest()[:20]
                brand = candidate.get("brand")
                if isinstance(brand, dict):
                    brand = brand.get("name")
                rows.append({
                    "external_id": external_id,
                    "name_original": name[:300],
                    "name_normalized": normalize(name),
                    "ingredient": normalize(name),
                    "brand": brand,
                    "category": category,
                    "package_size": size or 1,
                    "package_unit": unit or "unit",
                    "price": offer_price,
                    "price_per_unit": (offer_price / size) if offer_price is not None and size else None,
                    "product_url": product_url,
                    "availability": "available" if offers else "unknown",
                })
    return rows


def _click_first(scope, patterns, timeout=1600):
    for pattern in patterns:
        for role in ("button", "link", "radio"):
            try:
                locator = scope.get_by_role(role, name=re.compile(pattern, re.I)).first
                if locator.count() and locator.is_visible():
                    locator.click(timeout=timeout)
                    return True
            except Exception:
                pass
        try:
            locator = scope.get_by_text(re.compile(pattern, re.I), exact=False).first
            if locator.count() and locator.is_visible():
                locator.click(timeout=timeout)
                return True
        except Exception:
            pass
    return False


def _visible_postcode_input(scope):
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
    try:
        labelled = scope.get_by_label(re.compile(r"Postleitzahl|PLZ", re.I)).first
        if labelled.count() and labelled.is_visible():
            return labelled
    except Exception:
        pass
    for selector in selectors:
        try:
            locator = scope.locator(selector).first
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            pass
    return None


class ReweCatalogScraper:
    def __init__(self, delay=0.35, session=None, browser_enabled=None):
        self.delay = delay
        self.session = session or requests.Session()
        self.browser_enabled = (
            os.getenv("REWE_BROWSER_ENABLED", "true").lower() not in {"0", "false", "no"}
            if browser_enabled is None else browser_enabled
        )

    @staticmethod
    def _same_category(candidate: str, start: str) -> bool:
        candidate_path = urlsplit(candidate).path.rstrip("/")
        start_path = urlsplit(start).path.rstrip("/")
        return candidate_path == start_path

    def _pagination_links(self, html: str, current_url: str, start_url: str):
        """Discover however many pages a category actually has instead of assuming a fixed count."""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for anchor in soup.select("a[href]"):
            href = urljoin(current_url, anchor.get("href", "")).split("#")[0]
            if not self._same_category(href, start_url):
                continue
            query = parse_qs(urlsplit(href).query)
            rel = " ".join(anchor.get("rel", [])) if anchor.get("rel") else ""
            label = " ".join(anchor.stripped_strings)
            aria = anchor.get("aria-label", "")
            is_pagination = (
                "page" in query
                or "seite" in query
                or re.search(r"\b(next|weiter|nächste|naechste)\b", f"{rel} {label} {aria}", re.I)
            )
            if is_pagination and href not in links:
                links.append(href)
        return links

    def pages(self, start):
        seen, pending = set(), [start]
        while pending and len(seen) < MAX_CATEGORY_PAGES:
            url = pending.pop(0).split("#")[0]
            if url in seen:
                continue
            seen.add(url)
            response = self.session.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            yield url, response.text
            for href in self._pagination_links(response.text, url, start):
                if href not in seen and href not in pending:
                    pending.append(href)
            time.sleep(self.delay)

    def extract(self, html, url, category):
        soup = BeautifulSoup(html, "html.parser")
        found = _json_ld_products(soup, url, category)
        pdp_by_name = {}
        anchor_products = []
        for anchor in soup.select('a[href*="/shop/p/"]'):
            href = _canonical_product_url(anchor.get("href", ""), url)
            if not href:
                continue
            box = anchor.find_parent(["article", "li"]) or anchor.find_parent("div") or anchor
            raw = " ".join(box.stripped_strings)
            visible = " ".join(anchor.stripped_strings)
            if len(raw) < 4:
                continue
            product_name = visible or raw
            name_key = normalize(product_name)
            if name_key:
                pdp_by_name[name_key] = href
            size, unit = package(raw)
            cost = price(raw)
            external_id = href.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or hashlib.sha256((product_name + href).encode()).hexdigest()[:20]
            anchor_products.append({
                "external_id": external_id,
                "name_original": product_name[:300],
                "name_normalized": name_key,
                "ingredient": name_key,
                "brand": None,
                "category": category,
                "package_size": size or 1,
                "package_unit": unit or "unit",
                "price": cost,
                "price_per_unit": (cost / size) if cost is not None and size else None,
                "product_url": href,
                "availability": "unknown",
            })

        # JSON-LD often contains a generic shop/category URL. Replace it with the exact
        # product-card href whenever the visible product name lets us match the two.
        for product in found:
            if product.get("product_url"):
                continue
            key = normalize(product.get("name_original", ""))
            exact = pdp_by_name.get(key)
            if not exact and key:
                exact = next((link for name, link in pdp_by_name.items() if key in name or name in key), None)
            product["product_url"] = exact
        found.extend(anchor_products)

        unique = {}
        for product in found:
            current = unique.get(product["external_id"])
            if current is None:
                unique[product["external_id"]] = product
                continue
            candidate_is_better = (
                (not current.get("product_url") and product.get("product_url"))
                or (current.get("price") is None and product.get("price") is not None)
            )
            if candidate_is_better:
                merged = {**current, **{k: v for k, v in product.items() if v is not None}}
                unique[product["external_id"]] = merged
        return list(unique.values())

    def _location_scopes(self, page):
        yield page
        for frame in page.frames:
            if frame != page.main_frame:
                yield frame

    def _set_delivery_location(self, page, postcode):
        response = page.goto(SHOP_DELIVERY_URL, wait_until="domcontentloaded", timeout=45000)
        if response and response.status >= 400:
            raise RuntimeError(f"REWE blocked browser request with HTTP {response.status}")
        page.wait_for_timeout(1200)
        _click_first(page, [r"Alle akzeptieren", r"Akzeptieren", r"Zustimmen"], timeout=1200)

        body = page.locator("body").inner_text(timeout=8000)
        if postcode in body and re.search(r"Lieferservice|Lieferung", body, re.I):
            return

        for scope in list(self._location_scopes(page)):
            _click_first(scope, [r"Lieferservice", r"Lieferung", r"Liefern lassen", r"Standort", r"Lieferadresse", r"PLZ"], timeout=1200)
        page.wait_for_timeout(800)

        postcode_input = None
        for _ in range(4):
            for scope in self._location_scopes(page):
                postcode_input = _visible_postcode_input(scope)
                if postcode_input is not None:
                    break
            if postcode_input is not None:
                break
            _click_first(page, [r"Standort ändern", r"Lieferadresse", r"Lieferservice", r"Lieferung"], timeout=1200)
            page.wait_for_timeout(700)
        if postcode_input is None:
            title = page.title()
            body = page.locator("body").inner_text(timeout=5000)[:800]
            raise RuntimeError(f"REWE postcode input was not found; title={title!r}; page={body!r}")

        postcode_input.fill(postcode)
        try:
            postcode_input.press("Enter")
        except Exception:
            pass
        page.wait_for_timeout(900)
        for scope in self._location_scopes(page):
            _click_first(scope, [r"Suchen", r"Weiter", r"Übernehmen", r"Bestätigen", r"Standort.*wählen"], timeout=1800)
        page.wait_for_timeout(1200)

        delivery_selected = False
        for scope in self._location_scopes(page):
            delivery_selected = _click_first(scope, [r"Lieferservice", r"Lieferung", r"Liefern lassen"], timeout=2500) or delivery_selected
        if delivery_selected:
            page.wait_for_timeout(1200)
        for scope in self._location_scopes(page):
            _click_first(scope, [r"Auswählen", r"Weiter", r"Übernehmen", r"Bestätigen"], timeout=1800)
        page.wait_for_timeout(1500)

        text = page.locator("body").inner_text(timeout=8000)
        if re.search(r"Abholservice|Abholung", text, re.I) and not re.search(r"Lieferservice|Lieferung", text, re.I):
            raise RuntimeError("REWE resolved to pickup instead of delivery")
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        page.context.storage_state(path=str(STATE_FILE))

    def _browser_category_html(self, page, url):
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if response and response.status >= 400:
            raise RuntimeError(f"REWE category returned HTTP {response.status}")
        try:
            page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass
        previous_height = 0
        for _ in range(10):
            _click_first(page, [r"Mehr laden", r"Mehr anzeigen", r"Weitere Produkte"], timeout=600)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(450)
            height = page.evaluate("document.body.scrollHeight")
            if height == previous_height:
                break
            previous_height = height
        return page.content()

    def _browser_category_pages(self, page, start):
        seen, pending = set(), [start]
        while pending and len(seen) < MAX_CATEGORY_PAGES:
            current = pending.pop(0).split("#")[0]
            if current in seen:
                continue
            seen.add(current)
            html = self._browser_category_html(page, current)
            yield current, html
            for href in self._pagination_links(html, current, start):
                if href not in seen and href not in pending:
                    pending.append(href)

    def _base_report(self, postcode, mode):
        return {
            "categories_processed": 0,
            "categories_successful": 0,
            "categories_failed": 0,
            "pages_processed": 0,
            "products_found": 0,
            "products_with_price": 0,
            "products_created": 0,
            "products_updated": 0,
            "errors": [],
            "fetch_mode": mode,
            "service_type": "delivery",
            "postcode": postcode,
        }

    def _ingest_products(self, report, products, upsert, postcode):
        priced = 0
        for product in products:
            if product.get("price") is not None:
                priced += 1
            created = upsert(product, postcode)
            report["products_created" if created else "products_updated"] += 1
        report["products_found"] += len(products)
        report["products_with_price"] += priced

    def _run_browser(self, upsert, postcode, urls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright browser fallback is not installed") from exc
        report = self._base_report(postcode, "playwright")
        headless = os.getenv("REWE_BROWSER_HEADLESS", "true").lower() not in {"0", "false", "no"}
        with sync_playwright() as pw:
            launch_args = {"headless": headless, "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"]}
            channel = os.getenv("REWE_BROWSER_CHANNEL", "").strip()
            if channel:
                launch_args["channel"] = channel
            try:
                browser = pw.chromium.launch(**launch_args)
            except Exception:
                launch_args.pop("channel", None)
                browser = pw.chromium.launch(**launch_args)
            context_args = {"locale": "de-DE", "user_agent": HEADERS["User-Agent"], "viewport": {"width": 1440, "height": 1000}}
            if STATE_FILE.exists():
                context_args["storage_state"] = str(STATE_FILE)
            context = browser.new_context(**context_args)
            page = context.new_page()
            try:
                try:
                    self._set_delivery_location(page, postcode)
                except Exception:
                    if STATE_FILE.exists():
                        STATE_FILE.unlink(missing_ok=True)
                    context.close()
                    browser.close()
                    browser = pw.chromium.launch(**launch_args)
                    context = browser.new_context(locale="de-DE", user_agent=HEADERS["User-Agent"], viewport={"width": 1440, "height": 1000})
                    page = context.new_page()
                    self._set_delivery_location(page, postcode)
                for start in urls:
                    report["categories_processed"] += 1
                    category = start.rstrip("/").split("/")[-1] or "bonus"
                    try:
                        by_id = {}
                        for page_url, html in self._browser_category_pages(page, start):
                            report["pages_processed"] += 1
                            for product in self.extract(html, page_url, category):
                                current = by_id.get(product["external_id"])
                                if current is None or (not current.get("product_url") and product.get("product_url")):
                                    by_id[product["external_id"]] = product
                        products = list(by_id.values())
                        if not products:
                            raise RuntimeError("No products found after localized delivery page load")
                        self._ingest_products(report, products, upsert, postcode)
                        report["categories_successful"] += 1
                    except Exception as exc:
                        report["categories_failed"] += 1
                        report["errors"].append({"category": category, "error": str(exc)[:300]})
            finally:
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

    def _run_http(self, upsert, postcode, urls):
        report = self._base_report(postcode, "http")
        for start in urls:
            report["categories_processed"] += 1
            category = start.rstrip("/").split("/")[-1] or "bonus"
            try:
                by_id = {}
                for url, html in self.pages(start):
                    report["pages_processed"] += 1
                    for product in self.extract(html, url, category):
                        current = by_id.get(product["external_id"])
                        if current is None or (not current.get("product_url") and product.get("product_url")):
                            by_id[product["external_id"]] = product
                products = list(by_id.values())
                if not products:
                    raise RuntimeError("No products found")
                self._ingest_products(report, products, upsert, postcode)
                report["categories_successful"] += 1
            except Exception as exc:
                report["categories_failed"] += 1
                report["errors"].append({"category": category, "error": str(exc)[:300]})
        report["status"] = "failed" if not report["categories_successful"] else ("partial" if report["categories_failed"] else "healthy")
        return report

    def run(self, upsert, postcode, urls=REWE_CATEGORY_URLS):
        http_report = self._run_http(upsert, postcode, urls)
        ratio = http_report["products_with_price"] / http_report["products_found"] if http_report["products_found"] else 0
        if http_report["status"] != "failed" and ratio >= 0.25:
            return http_report
        if not self.browser_enabled:
            return http_report
        browser_report = self._run_browser(upsert, postcode, urls)
        browser_report["http_fallback_reason"] = {
            "status": http_report["status"],
            "products_found": http_report["products_found"],
            "products_with_price": http_report["products_with_price"],
            "errors": http_report["errors"][:3],
        }
        return browser_report
