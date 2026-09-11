"""REWE catalog ingestion with a lightweight HTTP path and a Playwright fallback.

The browser path mirrors the normal REWE shop flow: enter a German postcode,
select Lieferservice (delivery), then read the localized catalog snapshot.
No login, cart mutation or checkout automation is performed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from urllib.parse import urljoin

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
    patterns = [
        r"(?:€|EUR|Euro)\s*(\d+[,.]\d{2})",
        r"(\d+[,.]\d{2})\s*(?:€|EUR|Euro)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


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
                url = candidate.get("url") or ""
                offers = candidate.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                offer_price = offers.get("price") if isinstance(offers, dict) else None
                try:
                    offer_price = float(str(offer_price).replace(",", ".")) if offer_price is not None else None
                except ValueError:
                    offer_price = None
                size, unit = package(f"{name} {candidate.get('description') or ''}")
                external_id = str(candidate.get("sku") or candidate.get("gtin13") or candidate.get("productID") or "")
                if not external_id:
                    external_id = hashlib.sha256(f"{name}|{url}".encode()).hexdigest()[:20]
                rows.append(
                    {
                        "external_id": external_id,
                        "name_original": name[:300],
                        "name_normalized": normalize(name),
                        "ingredient": normalize(name),
                        "brand": (candidate.get("brand") or {}).get("name") if isinstance(candidate.get("brand"), dict) else candidate.get("brand"),
                        "category": category,
                        "package_size": size or 1,
                        "package_unit": unit or "unit",
                        "price": offer_price,
                        "price_per_unit": (offer_price / size) if offer_price is not None and size else None,
                        "product_url": urljoin(base_url, url),
                        "availability": "available" if offers else "unknown",
                    }
                )
    return rows


def _click_first(page, patterns, timeout=1500):
    for pattern in patterns:
        try:
            locator = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            if locator.count() and locator.is_visible():
                locator.click(timeout=timeout)
                return True
        except Exception:
            pass
        try:
            locator = page.get_by_role("link", name=re.compile(pattern, re.I)).first
            if locator.count() and locator.is_visible():
                locator.click(timeout=timeout)
                return True
        except Exception:
            pass
    return False


class ReweCatalogScraper:
    def __init__(self, delay=0.35, session=None, browser_enabled=None):
        self.delay = delay
        self.session = session or requests.Session()
        self.browser_enabled = (
            os.getenv("REWE_BROWSER_ENABLED", "true").lower() not in {"0", "false", "no"}
            if browser_enabled is None
            else browser_enabled
        )

    def pages(self, start):
        seen = set()
        pending = [start]
        while pending:
            url = pending.pop(0).split("#")[0]
            if url in seen:
                continue
            seen.add(url)
            response = self.session.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            yield url, response.text
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.select("a[href]"):
                href = urljoin(url, anchor["href"])
                if "/shop/c/" in href and ("page=" in href or "seite=" in href) and href not in seen:
                    pending.append(href)
            time.sleep(self.delay)

    def extract(self, html, url, category):
        soup = BeautifulSoup(html, "html.parser")
        found = _json_ld_products(soup, url, category)
        for anchor in soup.select('a[href*="/shop/p/"]'):
            href = urljoin(url, anchor.get("href", ""))
            box = anchor.find_parent(["article", "li"]) or anchor.find_parent("div") or anchor
            raw = " ".join(box.stripped_strings)
            visible = " ".join(anchor.stripped_strings)
            if len(raw) < 4:
                continue
            product_name = visible or raw
            size, unit = package(raw)
            cost = price(raw)
            external_id = href.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
            if not external_id:
                external_id = hashlib.sha256((product_name + href).encode()).hexdigest()[:20]
            found.append(
                {
                    "external_id": external_id,
                    "name_original": product_name[:300],
                    "name_normalized": normalize(product_name),
                    "ingredient": normalize(product_name),
                    "brand": None,
                    "category": category,
                    "package_size": size or 1,
                    "package_unit": unit or "unit",
                    "price": cost,
                    "price_per_unit": (cost / size) if cost is not None and size else None,
                    "product_url": href,
                    "availability": "unknown",
                }
            )
        unique = {}
        for product in found:
            current = unique.get(product["external_id"])
            if current is None or (current.get("price") is None and product.get("price") is not None):
                unique[product["external_id"]] = product
        return list(unique.values())

    def _set_delivery_location(self, page, postcode):
        page.goto(SHOP_DELIVERY_URL, wait_until="domcontentloaded", timeout=45000)
        _click_first(page, [r"Alle akzeptieren", r"Akzeptieren", r"Zustimmen"], timeout=1200)

        # REWE changes markup periodically, so prefer semantic inputs and keep
        # several conservative fallbacks. We only fill a visible postcode field.
        candidates = [
            page.get_by_label(re.compile(r"Postleitzahl|PLZ", re.I)),
            page.locator('input[placeholder*="Postleitzahl" i]'),
            page.locator('input[placeholder*="PLZ" i]'),
            page.locator('input[name*="postal" i]'),
            page.locator('input[name*="zip" i]'),
        ]
        postcode_input = None
        for locator in candidates:
            try:
                first = locator.first
                if first.count() and first.is_visible():
                    postcode_input = first
                    break
            except Exception:
                continue
        if postcode_input is None:
            # If a previous persistent/session context already has a location,
            # REWE may not show the postcode prompt. Confirm that delivery is active.
            body = page.locator("body").inner_text(timeout=5000)
            if postcode in body and re.search(r"Lieferservice|Lieferung", body, re.I):
                return
            raise RuntimeError("REWE postcode input was not found")

        postcode_input.fill(postcode)
        try:
            postcode_input.press("Enter")
        except Exception:
            pass
        page.wait_for_timeout(800)
        _click_first(page, [r"Weiter", r"Suchen", r"Standort.*wählen", r"Übernehmen", r"Bestätigen"], timeout=1800)
        page.wait_for_timeout(1000)

        # The product requirement is delivery only. Never select pickup.
        selected = _click_first(page, [r"Lieferservice", r"Lieferung", r"Liefern lassen"], timeout=2500)
        if selected:
            page.wait_for_timeout(1200)
        # Some versions show a second confirmation after choosing delivery.
        _click_first(page, [r"Weiter", r"Auswählen", r"Übernehmen", r"Bestätigen"], timeout=1800)
        page.wait_for_timeout(1200)

        text = page.locator("body").inner_text(timeout=5000)
        if re.search(r"Abholservice|Abholung", text, re.I) and not re.search(r"Lieferservice|Lieferung", text, re.I):
            raise RuntimeError("REWE resolved to pickup instead of delivery")

    def _browser_category_html(self, page, url):
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        # Trigger lazy-loaded product cards and any simple 'load more' control.
        previous_height = 0
        for _ in range(8):
            try:
                _click_first(page, [r"Mehr laden", r"Mehr anzeigen", r"Weitere Produkte"], timeout=700)
            except Exception:
                pass
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(500)
            height = page.evaluate("document.body.scrollHeight")
            if height == previous_height:
                break
            previous_height = height
        return page.content()

    def _run_browser(self, upsert, postcode, urls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright browser fallback is not installed") from exc

        report = {
            "categories_processed": 0,
            "categories_successful": 0,
            "categories_failed": 0,
            "products_found": 0,
            "products_with_price": 0,
            "products_created": 0,
            "products_updated": 0,
            "errors": [],
            "fetch_mode": "playwright",
            "service_type": "delivery",
            "postcode": postcode,
        }
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                locale="de-DE",
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 1440, "height": 1000},
            )
            page = context.new_page()
            try:
                self._set_delivery_location(page, postcode)
                for start in urls:
                    report["categories_processed"] += 1
                    category = start.rstrip("/").split("/")[-1] or "bonus"
                    try:
                        html = self._browser_category_html(page, start)
                        products = self.extract(html, start, category)
                        priced = 0
                        for product in products:
                            if product.get("price") is not None:
                                priced += 1
                            created = upsert(product, postcode)
                            report["products_created" if created else "products_updated"] += 1
                        report["products_found"] += len(products)
                        report["products_with_price"] += priced
                        if not products:
                            raise RuntimeError("No products found after localized delivery page load")
                        report["categories_successful"] += 1
                    except Exception as exc:
                        report["categories_failed"] += 1
                        report["errors"].append({"category": category, "error": str(exc)[:180]})
            finally:
                context.close()
                browser.close()

        report["status"] = (
            "failed"
            if not report["categories_successful"]
            else ("partial" if report["categories_failed"] else "healthy")
        )
        return report

    def _run_http(self, upsert, postcode, urls):
        report = {
            "categories_processed": 0,
            "categories_successful": 0,
            "categories_failed": 0,
            "products_found": 0,
            "products_with_price": 0,
            "products_created": 0,
            "products_updated": 0,
            "errors": [],
            "fetch_mode": "http",
            "service_type": "delivery",
            "postcode": postcode,
        }
        for start in urls:
            report["categories_processed"] += 1
            category = start.rstrip("/").split("/")[-1] or "bonus"
            try:
                count = 0
                priced = 0
                for url, html in self.pages(start):
                    for product in self.extract(html, url, category):
                        if product.get("price") is not None:
                            priced += 1
                        created = upsert(product, postcode)
                        report["products_created" if created else "products_updated"] += 1
                        count += 1
                if not count:
                    raise RuntimeError("No products found")
                report["products_found"] += count
                report["products_with_price"] += priced
                report["categories_successful"] += 1
            except Exception as exc:
                report["categories_failed"] += 1
                report["errors"].append({"category": category, "error": str(exc)[:180]})
        report["status"] = (
            "failed"
            if not report["categories_successful"]
            else ("partial" if report["categories_failed"] else "healthy")
        )
        return report

    def run(self, upsert, postcode, urls=REWE_CATEGORY_URLS):
        # First try the cheap HTTP path. If REWE blocks it or it returns no
        # localized prices, fall back to the normal browser delivery flow.
        http_report = self._run_http(upsert, postcode, urls)
        price_ratio = (
            http_report["products_with_price"] / http_report["products_found"]
            if http_report["products_found"]
            else 0
        )
        if http_report["status"] != "failed" and price_ratio >= 0.25:
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
