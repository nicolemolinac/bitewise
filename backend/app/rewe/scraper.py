"""REWE catalog ingestion with HTTP fast path and resilient Playwright delivery fallback."""
from __future__ import annotations

import hashlib
import math
import json
import os
import re
import subprocess
import sys
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


_PACKAGE_NUMBER = r"(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
_PACKAGE_UNIT = r"glas|gläser|glaeser|bund|bünde|buende|kopf|köpfe|koepfe|zehe|zehen|stange|stangen|knolle|knollen|netz|netze|rolle|rollen|schale|schalen|dutzend|dozens?|dozen|packung(?:en)?|pack|flasche(?:n)?|dose(?:n)?|kg|mg|g|ml|cl|l|stk\.?|st\.?|stück|stueck|pcs?\.?|eier|beutel|becher"


def _parse_de_number(raw):
    value = str(raw or "").strip()
    if not value:
        return None
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        value = value.replace(".", "")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _package_unit(amount, unit):
    unit = unit.lower().rstrip(".")
    if unit == "kg": return amount * 1000, "g"
    if unit == "mg": return amount / 1000, "g"
    if unit == "g": return amount, "g"
    if unit == "l": return amount * 1000, "ml"
    if unit == "cl": return amount * 10, "ml"
    if unit == "ml": return amount, "ml"
    if unit in {"dutzend", "dozen"}: return amount * 12, "unit"
    # Preserve ingredient-relevant count units rather than collapsing them
    # into generic pieces (e.g. garlic cloves and herb bunches).
    if unit in {"zehe", "zehen"}: return amount, "clove"
    if unit in {"bund", "bünde", "buende"}: return amount, "bunch"
    if unit in {"kopf", "köpfe", "koepfe"}: return amount, "head"
    if unit in {"stange", "stangen"}: return amount, "stalk"
    if unit in {"knolle", "knollen"}: return amount, "bulb"
    if unit in {"flasche", "flaschen"}: return amount, "bottle"
    if unit in {"dose", "dosen"}: return amount, "can"
    if unit in {"glas", "gläser", "glaeser"}: return amount, "jar"
    if unit == "beutel": return amount, "bag"
    if unit == "becher": return amount, "cup_container"
    if unit in {"pack", "packung", "packungen"}: return amount, "pack"
    if unit in {"netz", "netze"}: return amount, "net"
    if unit in {"rolle", "rollen"}: return amount, "roll"
    if unit in {"schale", "schalen"}: return amount, "tray"
    if unit in {"stk", "st", "stück", "stueck", "pcs", "pc", "eier"}:
        return amount, "unit"
    return None, None


def package(text: str):
    """Parse total sellable package content; reject unit-price denominators."""
    value = str(text or "").replace("\u00a0", " ").replace("×", "x").replace("✕", "x")
    if not value.strip():
        return None, None

    # A price-per-unit denominator is not the package content.
    value = re.sub(r"(?:grundpreis|preis\s*/?\s*kg|€/|€\s*/|eur\s*/|/\s*)\s*\d+(?:[.,]\d+)?\s*(?:kg|g|ml|l)\b", " ", value, flags=re.I)
    # Remove signed negative quantities even when whitespace follows the minus.
    value = re.sub(rf"(?<!\w)-\s*{_PACKAGE_NUMBER}\s*(?:{_PACKAGE_UNIT})\b", " ", value, flags=re.I)
    # Do not accept negative values by matching the positive suffix of "-2 g".
    multi = re.compile(
        rf"(?<![\w.,+-])(?P<n>{_PACKAGE_NUMBER})\s*x\s*(?P<q>{_PACKAGE_NUMBER})\s*(?P<u>{_PACKAGE_UNIT})(?![\w])",
        re.I,
    )
    for m in multi.finditer(value):
        n, q = _parse_de_number(m.group("n")), _parse_de_number(m.group("q"))
        if n is None or q is None:
            continue
        base, unit = _package_unit(q, m.group("u"))
        total = n * base if base is not None else None
        if total is not None and math.isfinite(total) and total > 0:
            return total, unit

    single = re.compile(
        rf"(?<![\w.,+-])(?P<q>{_PACKAGE_NUMBER})\s*(?P<u>{_PACKAGE_UNIT})(?![\w])",
        re.I,
    )
    single_matches = list(single.finditer(value))
    # If a title includes both a container count and net contents (e.g.
    # "1 Flasche Wasser 500 ml"), the measurable contents are authoritative.
    physical_units = {"kg", "mg", "g", "l", "cl", "ml"}
    ordered_matches = [
        match for match in single_matches
        if match.group("u").lower().rstrip(".") in physical_units
    ] + [
        match for match in single_matches
        if match.group("u").lower().rstrip(".") not in physical_units
    ]
    for m in ordered_matches:
        q = _parse_de_number(m.group("q"))
        if q is None:
            continue
        base, unit = _package_unit(q, m.group("u"))
        if base is not None:
            return base, unit

    # Count packs such as "10er Pack" only if the product is clearly a count item.
    count = re.search(r"(?<![\w])(\d+)\s*(?:er[- ]?pack|er packung)\b", value, re.I)
    if count:
        n = _parse_de_number(count.group(1))
        if n is not None:
            return n, "unit"
    return None, None

def price(text: str):
    # Grundpreis is a normalized unit price, not the checkout price of the pack.
    # Remove both labelled and bare €/100g-style denominators before extracting
    # the product price so a missing pack price never becomes a false price.
    value = re.sub(
        r"(?:grundpreis|base\s*price)\s*:?\s*(?:€|EUR|Euro)?\s*"
        r"\d+[,.]\d{1,2}\s*(?:€|EUR|Euro)?\s*/\s*"
        r"(?:\d+(?:[,.]\d+)?\s*)?(?:kg|g|ml|l)\b",
        " ",
        str(text or ""),
        flags=re.I,
    )
    value = re.sub(
        r"\d+[,.]\d{1,2}\s*(?:€|EUR|Euro)?\s*/\s*"
        r"(?:\d+(?:[,.]\d+)?\s*)?(?:kg|g|ml|l)\b",
        " ",
        value,
        flags=re.I,
    )
    for pattern in (r"(?:€|EUR|Euro)\s*(\d+[,.]\d{2})", r"(\d+[,.]\d{2})\s*(?:€|EUR|Euro)"):
        match = re.search(pattern, value, re.I)
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


def _schema_availability(offers) -> str:
    """Translate schema.org availability into the catalog's conservative status."""
    if not isinstance(offers, dict):
        return "unknown"
    raw = str(offers.get("availability") or "").strip().lower()
    token = re.split(r"[/#]", raw)[-1].replace("_", "").replace("-", "")
    if any(marker in token for marker in ("outofstock", "soldout", "discontinued")):
        return "unavailable"
    if any(marker in token for marker in ("instock", "limitedavailability")):
        return "available"
    return "unknown"


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
                raw_image = candidate.get("image")
                if isinstance(raw_image, list):
                    raw_image = next((value for value in raw_image if isinstance(value, str)), None)
                elif isinstance(raw_image, dict):
                    raw_image = raw_image.get("url") or raw_image.get("contentUrl")
                image_url = urljoin(base_url, str(raw_image)) if raw_image else None
                if image_url and urlsplit(image_url).scheme not in {"http", "https"}:
                    image_url = None
                offers = candidate.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                offer_price = (offers.get("price") or offers.get("lowPrice")) if isinstance(offers, dict) else None
                try:
                    offer_price = float(str(offer_price).replace(",", ".")) if offer_price is not None else None
                except Exception:
                    offer_price = None
                size, unit = package(name)
                if size is None:
                    size, unit = package(candidate.get("description") or "")
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
                    "package_size": size if size is not None else 0,
                    "package_unit": unit or "unknown",
                    "price": offer_price,
                    "price_per_unit": (offer_price / size) if offer_price is not None and size else None,
                    "product_url": product_url,
                    "image_url": image_url,
                    "availability": _schema_availability(offers),
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


def _find_chrome_for_testing():
    """Find an installed Google Chrome for Testing executable; never substitute Chromium."""
    candidates = []
    configured = os.getenv("CHROME_FOR_TESTING_PATH", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    home = Path.home()
    candidates.extend([
        Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        home / "Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    ])
    candidates.extend([
        Path("/usr/bin/google-chrome-for-testing"),
        Path("/opt/google/chrome-for-testing/chrome"),
        home / "AppData/Local/Google/Chrome for Testing/Application/chrome.exe",
        home / "Downloads/chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        home / "Downloads/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    ])
    # Deliberately do not fall back to Playwright's bundled Chromium. Bitewise
    # uses Google's Chrome for Testing build for the REWE browser session.

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _ensure_chrome_for_testing(playwright, endpoint):
    """Attach to an existing CDP browser or launch an isolated local one."""
    try:
        response = requests.get(endpoint + "/json/version", timeout=1.5)
        if response.ok:
            return
    except requests.RequestException:
        pass

    parsed = urlsplit(endpoint)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(
            f"No Chrome for Testing is reachable at {endpoint}; automatic launch is local-only."
        )

    executable = _find_chrome_for_testing()
    if not executable:
        raise RuntimeError(
            "Google Chrome for Testing was not found. Install Chrome for Testing or set "
            "CHROME_FOR_TESTING_PATH to its executable. Playwright's bundled Chromium "
            "is intentionally not used."
        )

    port = parsed.port or 9222
    profile = Path(__file__).resolve().parents[2] / "data" / "chrome-for-testing-profile"
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-blink-features=AutomationControlled",
    ]
    headless_setting = os.getenv("REWE_BROWSER_HEADLESS")
    # Local macOS runs are visible by default; Linux/CI runs have no desktop
    # session, so start the same Chrome for Testing build in headless mode.
    headless = (
        headless_setting.strip().lower() in {"1", "true", "yes"}
        if headless_setting is not None
        else sys.platform != "darwin" or bool(os.getenv("CI"))
    )
    if headless:
        command.append("--headless=new")
    command.append("about:blank")
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)

    last_error = None
    for _ in range(40):
        try:
            response = requests.get(endpoint + "/json/version", timeout=1)
            if response.ok:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(
        f"Chrome for Testing was launched from {executable} but CDP did not become "
        f"available at {endpoint}. {last_error or ''}"
    )


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

    @staticmethod
    def _page_number(url: str):
        query = parse_qs(urlsplit(url).query)
        for key in ("page", "seite"):
            values = query.get(key)
            if values:
                match = re.search(r"\d+", values[0])
                if match:
                    return int(match.group())
        return None

    @staticmethod
    def _page_fingerprint(html: str):
        """Fingerprint visible product IDs/links so URL aliases cannot loop forever."""
        soup = BeautifulSoup(html, "html.parser")
        ids = sorted({
            urlsplit(urljoin("https://www.rewe.de", node.get("href", ""))).path
            for node in soup.select('a[href*="/shop/p/"]')
            if node.get("href")
        })
        if ids:
            return hashlib.sha256("\n".join(ids).encode()).hexdigest()
        # Fallback for pages whose product cards do not expose product links.
        text = normalize(soup.get_text(" ", strip=True))
        return hashlib.sha256(text[:12000].encode()).hexdigest()

    def _pagination_links(self, html: str, current_url: str, start_url: str):
        """Return only forward pagination targets, not every page number including page 1."""
        soup = BeautifulSoup(html, "html.parser")
        current_number = self._page_number(current_url)
        candidates = []
        numeric = []
        for anchor in soup.select("a[href]"):
            href = urljoin(current_url, anchor.get("href", "")).split("#")[0]
            if not self._same_category(href, start_url):
                continue
            rel = " ".join(anchor.get("rel", [])) if anchor.get("rel") else ""
            label = " ".join(anchor.stripped_strings)
            aria = anchor.get("aria-label", "")
            title = anchor.get("title", "")
            marker = f"{rel} {label} {aria} {title}"
            if re.search(r"\b(next|weiter|nächste|naechste)\b", marker, re.I):
                candidates.append(href)
                continue

            number = self._page_number(href)
            if number is None:
                # Some REWE page controls expose the page number in their label.
                match = re.fullmatch(r"\s*(\d+)\s*", label)
                if match:
                    number = int(match.group(1))
            if number is not None:
                numeric.append((number, href))

        # Prefer an explicit "next" link when REWE provides one. Otherwise
        # queue only the immediate next numeric page, never the whole page strip.
        if not candidates and numeric:
            threshold = current_number if current_number is not None else 1
            forward = sorted(
                (number, href) for number, href in numeric
                if number > threshold
            )
            if forward:
                candidates.append(forward[0][1])

        unique = []
        for href in candidates:
            if href not in unique:
                unique.append(href)
        return unique

    def pages(self, start):
        seen_urls, seen_content = set(), set()
        pending = [start]
        while pending and len(seen_urls) < MAX_CATEGORY_PAGES:
            url = pending.pop(0).split("#")[0]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            response = self.session.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            fingerprint = self._page_fingerprint(response.text)
            if fingerprint in seen_content:
                # REWE sometimes serves page 1 again under a different pagination URL.
                # Stop this category rather than repeatedly ingesting identical content.
                break
            seen_content.add(fingerprint)
            yield url, response.text
            for href in self._pagination_links(response.text, url, start):
                if href not in seen_urls and href not in pending:
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
            size, unit = package(product_name)
            if size is None:
                size, unit = package(raw)
            cost = price(raw)
            image_node = box.select_one("img")
            image_src = None
            if image_node:
                image_src = (image_node.get("src") or image_node.get("data-src") or image_node.get("data-lazy-src") or "")
                if not image_src and image_node.get("srcset"):
                    image_src = image_node.get("srcset").split(",")[0].strip().split(" ")[0]
            image_url = urljoin(url, image_src) if image_src else None
            if image_url and urlsplit(image_url).scheme not in {"http", "https"}:
                image_url = None
            external_id = href.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or hashlib.sha256((product_name + href).encode()).hexdigest()[:20]
            anchor_products.append({
                "external_id": external_id,
                "name_original": product_name[:300],
                "name_normalized": name_key,
                "ingredient": name_key,
                "brand": None,
                "category": category,
                "package_size": size if size is not None else 0,
                "package_unit": unit or "unknown",
                "price": cost,
                "price_per_unit": (cost / size) if cost is not None and size else None,
                "product_url": href,
                "image_url": image_url,
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
            current_size = current.get("package_size")
            candidate_size = product.get("package_size")
            current_has_size = isinstance(current_size, (int, float)) and math.isfinite(current_size) and current_size > 0
            candidate_has_size = isinstance(candidate_size, (int, float)) and math.isfinite(candidate_size) and candidate_size > 0
            candidate_is_better = (
                (not current.get("product_url") and product.get("product_url"))
                or (not current.get("image_url") and product.get("image_url"))
                or (current.get("price") is None and product.get("price") is not None)
                or (not current_has_size and candidate_has_size)
                or (not current.get("price_per_unit") and product.get("price_per_unit"))
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
            # A saved delivery address in an authenticated REWE session does not
            # necessarily expose the postcode form. Do not break a valid session
            # by demanding the postcode again; only fail later if catalog pages
            # themselves cannot be loaded or contain no products.
            title = page.title()
            body = page.locator("body").inner_text(timeout=5000)[:1200]
            if re.search(r"Lieferservice|Lieferung|Lieferadresse|Liefergebiet|Lieferung an", body, re.I):
                STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                page.context.storage_state(path=str(STATE_FILE))
                return
            raise RuntimeError(
                f"REWE has no visible postcode form or confirmed delivery context; "
                f"title={title!r}; page={body!r}"
            )

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
        seen_urls, seen_content = set(), set()
        pending = [start]
        while pending and len(seen_urls) < MAX_CATEGORY_PAGES:
            current = pending.pop(0).split("#")[0]
            if current in seen_urls:
                continue
            seen_urls.add(current)
            html = self._browser_category_html(page, current)
            fingerprint = self._page_fingerprint(html)
            if fingerprint in seen_content:
                # Stop when REWE returns the same product page for a different URL.
                break
            seen_content.add(fingerprint)
            yield current, html
            for href in self._pagination_links(html, current, start):
                if href not in seen_urls and href not in pending:
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


    def add_products_to_cart(self, products):
        """Add an explicit, user-requested product list to the authenticated REWE cart via CDP.

        This never checks out or pays. It reuses the user's existing Chrome context and
        reports any product whose add action cannot be confidently completed.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright Python package is not installed") from exc

        endpoint = os.getenv(
            "BITEWISE_CHROME_CDP_URL",
            os.getenv("REWE_CHROME_CDP_URL", "http://127.0.0.1:9222"),
        ).rstrip("/")
        browser = None
        page = None
        owns_page = False
        results = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(endpoint, timeout=15_000)
                if not browser.contexts:
                    raise RuntimeError("Chrome for Testing has no browser context")
                context = browser.contexts[0]
                page = next(
                    (candidate for candidate in context.pages
                     if urlsplit(candidate.url).hostname
                     and urlsplit(candidate.url).hostname.lower().endswith("rewe.de")),
                    None,
                )
                if page is None:
                    page = context.new_page()
                    owns_page = True

                for item in products:
                    name = str(item.get("name") or "REWE product")
                    product_url = _canonical_product_url(item.get("product_url") or "")
                    packs = max(1, min(99, int(item.get("packs") or 1)))
                    if not product_url:
                        results.append({"name": name, "status": "rejected", "message": "Not a verified REWE product URL"})
                        continue
                    try:
                        response = page.goto(product_url, wait_until="domcontentloaded", timeout=45_000)
                        if response and response.status >= 400:
                            raise RuntimeError("REWE product page returned HTTP " + str(response.status))
                        try:
                            page.wait_for_load_state("networkidle", timeout=6_000)
                        except Exception:
                            pass
                        body = page.locator("body").inner_text(timeout=8_000)
                        if re.search(r"Anmelden|Einloggen|Bitte melden Sie sich an", body[:2500], re.I) and re.search(r"Passwort|E-Mail-Adresse", body[:2500], re.I):
                            results.append({"name": name, "status": "login_required", "message": "REWE session is not authenticated"})
                            continue
                        if re.search(r"ausverkauft|nicht verfügbar|derzeit nicht lieferbar", body, re.I):
                            results.append({"name": name, "status": "unavailable", "message": "REWE marks this product as unavailable"})
                            continue

                        quantity_set = False
                        for selector in ('input[aria-label*="Menge" i]', 'input[name*="quantity" i]', 'input[type="number"]'):
                            try:
                                field = page.locator(selector).first
                                if field.count() and field.is_visible() and field.is_enabled():
                                    field.fill(str(packs))
                                    quantity_set = True
                                    break
                            except Exception:
                                pass

                        add_button = None
                        for pattern in (r"In den Warenkorb", r"Warenkorb hinzufügen"):
                            try:
                                candidate = page.get_by_role("button", name=re.compile(pattern, re.I)).first
                                if candidate.count() and candidate.is_visible() and candidate.is_enabled():
                                    add_button = candidate
                                    break
                            except Exception:
                                pass
                        if add_button is None:
                            results.append({"name": name, "status": "not_added", "message": "Could not find an enabled add-to-cart button"})
                            continue

                        add_button.click(timeout=8_000)
                        page.wait_for_timeout(1_400)
                        confirmation = page.locator("body").inner_text(timeout=8_000)
                        confirmed = bool(re.search(r"hinzugefügt|zum Warenkorb gelegt|Warenkorb wurde aktualisiert", confirmation, re.I))
                        fully_confirmed = confirmed and (packs == 1 or quantity_set)
                        results.append({
                            "name": name,
                            "status": "added" if fully_confirmed else ("quantity_unconfirmed" if confirmed else "submitted_unverified"),
                            "packs_requested": packs,
                            "quantity_set": quantity_set,
                            "message": "REWE displayed an add confirmation" if confirmed else "Add action was clicked; verify the cart before checkout",
                        })
                    except Exception as exc:
                        results.append({"name": name, "status": "error", "message": str(exc)[:240]})
        finally:
            if page and owns_page:
                try:
                    page.close()
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
        return {"results": results, "checkout_performed": False}

    def _run_browser(self, upsert, postcode, urls):
        """Scrape REWE in the already-running Chrome for Testing via CDP.

        This deliberately mirrors image_resolver._open_browser: Playwright is only
        the CDP client. It never downloads/launches its bundled Chromium and never
        owns or terminates the shared Chrome process/profile.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright Python package is not installed") from exc

        endpoint = os.getenv(
            "BITEWISE_CHROME_CDP_URL",
            os.getenv("REWE_CHROME_CDP_URL", "http://127.0.0.1:9222"),
        ).rstrip("/")
        report = self._base_report(postcode, "chrome-for-testing-cdp")
        browser = None
        page = None

        try:
            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.connect_over_cdp(endpoint, timeout=15_000)
                except Exception:
                    # If no browser is running, start an isolated Chrome for Testing
                    # profile, then attach over CDP. Never call chromium.launch().
                    _ensure_chrome_for_testing(pw, endpoint)
                    browser = pw.chromium.connect_over_cdp(endpoint, timeout=15_000)

                if not browser.contexts:
                    raise RuntimeError(
                        f"Chrome for Testing at {endpoint} has no browser context"
                    )

                # Reuse an already-open REWE tab when possible. This preserves
                # the user's authenticated account and saved delivery address instead
                # of opening a fresh tab and forcing the postcode dialog.
                context = browser.contexts[0]
                page = next(
                    (
                        candidate for candidate in context.pages
                        if urlsplit(candidate.url).hostname
                        and urlsplit(candidate.url).hostname.lower().endswith("rewe.de")
                    ),
                    None,
                )
                owns_page = page is None
                if page is None:
                    page = context.new_page()
                    self._set_delivery_location(page, postcode)

                for category_url in urls:
                    report["categories_processed"] += 1
                    category = category_url.rstrip("/").split("/")[-1] or "bonus"
                    try:
                        by_id = {}
                        for page_url, html in self._browser_category_pages(page, category_url):
                            report["pages_processed"] += 1
                            for product in self.extract(html, page_url, category):
                                current = by_id.get(product["external_id"])
                                if current is None or (
                                    (not current.get("product_url") and product.get("product_url"))
                                    or (current.get("price") is None and product.get("price") is not None)
                                ):
                                    by_id[product["external_id"]] = product

                        products = list(by_id.values())
                        if not products:
                            raise RuntimeError(
                                "No products found after localized REWE delivery page load"
                            )
                        self._ingest_products(report, products, upsert, postcode)
                        report["categories_successful"] += 1
                    except Exception as exc:
                        report["categories_failed"] += 1
                        report["errors"].append({
                            "category": category,
                            "error": str(exc)[:300],
                        })

        finally:
            if page and locals().get("owns_page", False):
                try:
                    page.close()
                except Exception:
                    pass
            if browser:
                try:
                    # Closing a CDP-connected Playwright Browser disconnects the
                    # client; it does not terminate the externally managed Chrome.
                    browser.close()
                except Exception:
                    pass

        report["status"] = (
            "failed" if not report["categories_successful"]
            else ("partial" if report["categories_failed"] else "healthy")
        )
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
        http_is_complete = (
            http_report["status"] == "healthy"
            and http_report["categories_failed"] == 0
        )
        if http_is_complete and ratio >= 0.25:
            return http_report
        if not self.browser_enabled:
            return http_report

        # When HTTP found enough priced products but only some categories failed,
        # retry just those categories in the authenticated browser session. This
        # avoids needlessly re-scraping the successful categories and lets the
        # final report combine both sources without double-counting products.
        failed_categories = {
            str(error.get("category") or "")
            for error in http_report.get("errors", [])
            if isinstance(error, dict) and error.get("category")
        }
        browser_urls = [
            url for url in urls
            if url.rstrip("/").split("/")[-1] in failed_categories
        ] if http_report["status"] == "partial" and ratio >= 0.25 else list(urls)
        if not browser_urls:
            browser_urls = list(urls)

        browser_report = self._run_browser(upsert, postcode, browser_urls)
        browser_report["http_fallback_reason"] = {
            "status": http_report["status"],
            "categories_failed": http_report["categories_failed"],
            "products_found": http_report["products_found"],
            "products_with_price": http_report["products_with_price"],
            "errors": http_report["errors"][:3],
        }

        if len(browser_urls) < len(urls):
            # The browser retried only categories that HTTP failed. Successful
            # HTTP categories and browser-retried categories are disjoint.
            for key in (
                "pages_processed", "products_found", "products_with_price",
                "products_created", "products_updated",
            ):
                browser_report[key] = (
                    int(http_report.get(key, 0) or 0)
                    + int(browser_report.get(key, 0) or 0)
                )
            browser_report["categories_processed"] = (
                int(http_report.get("categories_successful", 0) or 0)
                + int(browser_report.get("categories_processed", 0) or 0)
            )
            browser_report["categories_successful"] = (
                int(http_report.get("categories_successful", 0) or 0)
                + int(browser_report.get("categories_successful", 0) or 0)
            )
            browser_report["fetch_mode"] = "http+chrome-for-testing-cdp"
            successes = browser_report["categories_successful"]
            failures = browser_report["categories_failed"]
            browser_report["status"] = (
                "failed" if successes == 0
                else ("healthy" if successes == len(urls) and failures == 0 else "partial")
            )
        elif browser_report["status"] == "failed" and http_report["categories_successful"] > 0:
            # Preserve products already ingested by a partially successful HTTP
            # pass if the browser itself is blocked or unavailable.
            http_report["errors"].extend(browser_report.get("errors", [])[:3])
            http_report["browser_fallback_reason"] = browser_report.get("errors", [])[:3]
            http_report["status"] = "partial"
            return http_report

        return browser_report
