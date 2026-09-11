"""Manual REWE public-category ingestion. No login or checkout automation."""
import hashlib
import json
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BitewiseCatalog/1.0; manual local refresh)",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
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
                if not isinstance(candidate, dict):
                    continue
                if candidate.get("@type") != "Product":
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


class ReweCatalogScraper:
    def __init__(self, delay=0.35, session=None):
        self.delay = delay
        self.session = session or requests.Session()

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

    def run(self, upsert, postcode, urls=REWE_CATEGORY_URLS):
        report = {
            "categories_processed": 0,
            "categories_successful": 0,
            "categories_failed": 0,
            "products_found": 0,
            "products_created": 0,
            "products_updated": 0,
            "errors": [],
        }
        for start in urls:
            report["categories_processed"] += 1
            category = start.rstrip("/").split("/")[-1] or "bonus"
            try:
                count = 0
                for url, html in self.pages(start):
                    for product in self.extract(html, url, category):
                        created = upsert(product, postcode)
                        report["products_created" if created else "products_updated"] += 1
                        count += 1
                report["products_found"] += count
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
