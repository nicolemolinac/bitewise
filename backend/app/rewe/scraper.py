"""REWE catalog ingestion with HTTP fast path and resilient Playwright delivery fallback."""
from __future__ import annotations

import hashlib
import json
import math
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


def package(text: str):
    # Remove reference prices first: "1 kg = 4,00 €" is €/kg, not proof
    # that the product is a 1 kg package.
    package_text = re.sub(
        r"\\b1\\s*(?:kg|l)\\s*=\\s*(?:€\\s*)?\\d+[,.]\\d{2}\\s*(?:€|EUR|Euro)?",
        " ",
        text or "",
        flags=re.I,
    )
    # Preserve multipack quantity: 2x200ml is 400ml, not 200ml.
    match = re.search(
        r"(?:(\\d+)\\s*[x×]\\s*)?(\\d+(?:[.,]\\d+)?)\\s*(kg|g|ml|l|stk|st\\.|stück)",
        package_text,
        re.I,
    )
    if not match:
        return None, None
    multiplier = int(match.group(1) or 1)
    amount = float(match.group(2).replace(",", ".")) * multiplier
    unit = match.group(3).lower()
    if unit == "kg":
        return amount * 1000, "g"
    if unit == "l":
        return amount * 1000, "ml"
    if unit in ("stk", "st.", "stück"):
        return amount, "unit"
    return amount, unit


def _displayed_unit_price(text: str):
    """Return the normalized price per g, ml or piece from a REWE reference price."""
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml|stk\.?|stück|st\.)\s*=\s*(?:€\s*)?(\d+[,.]\d{2})\s*(?:€|EUR|Euro)?",
        text,
        re.I,
    )
    if not match:
        return None, None
    reference_quantity = float(match.group(1).replace(",", "."))
    amount = float(match.group(3).replace(",", "."))
    raw_unit = match.group(2).lower()
    if raw_unit == "kg":
        reference_quantity *= 1000
        unit = "g"
    elif raw_unit == "l":
        reference_quantity *= 1000
        unit = "ml"
    elif raw_unit in {"g", "ml"}:
        unit = raw_unit
    else:
        unit = "unit"
    if not math.isfinite(reference_quantity) or reference_quantity <= 0 or amount <= 0:
        return None, None
    return amount / reference_quantity, unit


def price_details(text: str, package_size=None, package_unit=None):
    """Return (pack checkout price, price per normalized g/ml/unit).

    REWE cards show reference prices per kg, 100g, litre, 100ml or piece.
    Convert the reference price using the parsed package size before costing.
    """
    reference_price, reference_unit = _displayed_unit_price(text)
    checkout_text = text
    if reference_price is not None:
        try:
            size = float(package_size) if package_size is not None else None
        except (TypeError, ValueError):
            size = None
        if (
            size is not None and math.isfinite(size) and size > 0
            and package_unit == reference_unit
        ):
            pack_price = reference_price * size
            return round(pack_price, 2), reference_price
        # A €/kg or €/l reference is not a package checkout price. Remove it
        # before looking for a separate explicit pack price; if none exists,
        # leave the product unpriced rather than inventing a 1,000x cost.
        checkout_text = re.sub(
            r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stk\.?|stück|st\.)\s*=\s*(?:€\s*)?\d+[,.]\d{2}\s*(?:€|EUR|Euro)?",
            " ",
            text,
            flags=re.I,
        )

    for pattern in (
        r"(?:€|EUR|Euro)\s*(\d+[,.]\d{2})",
        r"(\d+[,.]\d{2})\s*(?:€|EUR|Euro)",
    ):
        match = re.search(pattern, checkout_text, re.I)
        if match:
            pack_price = float(match.group(1).replace(",", "."))
            per_unit = (
                pack_price / float(package_size)
                if package_size and float(package_size) > 0
                else None
            )
            return round(pack_price, 2), per_unit
    return None, None


def price(text: str):
    # Backwards-compatible helper: price now means checkout price per package.
    return price_details(text)[0]


def _offer_availability(offers):
    """Interpret schema.org stock state; an Offer alone does not prove in-stock."""
    values = offers if isinstance(offers, list) else [offers]
    states = []
    offer_count = 0
    for offer in values:
        if not isinstance(offer, dict):
            continue
        offer_count += 1
        raw = str(offer.get("availability") or "").strip().lower()
        if not raw:
            states.append("unknown")
        elif "instock" in raw or "limitedavailability" in raw:
            states.append("available")
        elif any(token in raw for token in ("outofstock", "soldout", "discontinued", "preorder")):
            states.append("unavailable")
        else:
            states.append("unknown")
    if "available" in states:
        return "available"
    if offer_count and len(states) == offer_count and all(state == "unavailable" for state in states):
        return "unavailable"
    return "unknown"




def _canonical_product_url(value: str | None, base_url: str = "") -> str | None:
    """Return only exact REWE product-detail URLs, never category/shop landing pages."""
    if not value:
        return None
    absolute = urljoin(base_url, value)
    parts = urlsplit(absolute)
    if parts.scheme.lower() != "https" or parts.netloc.lower() not in {"www.rewe.de", "rewe.de"} or not parts.path.startswith("/shop/p/"):
        return None
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, parts.query, ""))


def _cart_add_status(confirmation_seen: bool, packs_requested: int) -> str:
    """Never report multi-pack additions as verified without reading the cart quantity."""
    if not confirmation_seen:
        return "submitted_unverified"
    return "added" if int(packs_requested) == 1 else "quantity_unconfirmed"


def _image_url_from_card(box, anchor, base_url: str):
    """Read the real product image from REWE cards, including lazy-loaded variants."""
    nodes = []
    for scope in (box, anchor):
        if scope is not None:
            nodes.extend(scope.select("img"))
            nodes.extend(scope.select("picture source"))
    seen = set()
    for node in nodes:
        if id(node) in seen:
            continue
        seen.add(id(node))
        candidates = [
            node.get("data-srcset"),
            node.get("srcset"),
            node.get("data-src"),
            node.get("data-lazy-src"),
            node.get("data-original"),
            node.get("data-image"),
            node.get("data-zoom-image"),
            node.get("src"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            # Pick the largest declared srcset candidate when available.
            candidate = str(candidate).strip()
            if "," in candidate:
                choices = []
                for item in candidate.split(","):
                    bits = item.strip().split()
                    if bits:
                        descriptor = bits[1] if len(bits) > 1 else "1x"
                        match = re.match(r"(\d+(?:\.\d+)?)(w|x)", descriptor)
                        score = float(match.group(1)) if match else 1.0
                        choices.append((score, bits[0]))
                if choices:
                    candidate = max(choices)[1]
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            absolute = urljoin(base_url, candidate)
            parsed = urlsplit(absolute)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return absolute
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
                offer_rows = offers if isinstance(offers, list) else [offers]
                overall_stock_status = _offer_availability(offers)
                offer_prices = []
                for offer in offer_rows:
                    if not isinstance(offer, dict):
                        continue
                    offer_stock_status = _offer_availability(offer)
                    # If REWE explicitly identifies an in-stock offer, only price
                    # those in-stock offers; otherwise retain unknown-but-not-
                    # explicitly-unavailable prices without claiming live stock.
                    if overall_stock_status == "available" and offer_stock_status != "available":
                        continue
                    if offer_stock_status == "unavailable":
                        continue
                    raw_price = offer.get("price")
                    try:
                        parsed_price = float(str(raw_price).replace(",", ".")) if raw_price is not None else None
                    except (TypeError, ValueError):
                        parsed_price = None
                    if parsed_price is not None and math.isfinite(parsed_price) and parsed_price > 0:
                        offer_prices.append(parsed_price)
                price_text = f"{name} {candidate.get('description') or ''}"
                size, unit = package(price_text)
                # schema.org Offer.price is the package checkout price. Prefer it
                # over parsing display text, which may contain reference €/kg prices.
                if offer_prices:
                    normalized_price = min(offer_prices)
                    normalized_price_per_unit = normalized_price / size if size and size > 0 else None
                else:
                    normalized_price, normalized_price_per_unit = price_details(price_text, size, unit)
                stock_status = overall_stock_status
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
                    "package_size": size if size is not None else 1,
                    "package_unit": unit or "unknown",
                    "price": normalized_price,
                    "price_per_unit": normalized_price_per_unit,
                    "product_url": product_url,
                    "image_url": image_url,
                    "availability": stock_status,
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


def _find_chrome_for_testing(playwright):
    """Find an installed Chrome for Testing / Playwright Chromium executable."""
    candidates = []
    configured = os.getenv("CHROME_FOR_TESTING_PATH", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    home = Path.home()
    candidates.extend([
        Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        home / "Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        home / "Applications/Chromium.app/Contents/MacOS/Chromium",
    ])
    for pattern in (
        "Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        "Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ".cache/ms-playwright/chromium-*/chrome-linux/chrome",
        ".cache/ms-playwright/chromium-*/chrome-linux64/chrome",
    ):
        candidates.extend(home.glob(pattern))

    try:
        candidates.append(Path(playwright.chromium.executable_path))
    except Exception:
        pass

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

    executable = _find_chrome_for_testing(playwright)
    if not executable:
        raise RuntimeError(
            "Chrome for Testing was not found. Install it with "
            "'python -m playwright install chromium' or set CHROME_FOR_TESTING_PATH "
            "to the Chrome for Testing executable."
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


def _rewe_cart_stepper_snapshot(page):
    """Read REWE's visible quantity control within the product content, not the header cart."""
    script = r"""
    () => {
      const root = document.querySelector('main') || document.body;
      const allButtons = Array.from(document.querySelectorAll('button, [role="button"]'));
      const buttons = allButtons.filter(el => root.contains(el));
      const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
      const label = el => [el.innerText,el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('data-testid'),el.className].filter(Boolean).join(' ').toLowerCase();
      const plus = el => (el.innerText||'').trim()==='+' || /increase|erh[oö]hen|mehr|plus|increment/.test(label(el));
      const minus = el => ['-','−','–'].includes((el.innerText||'').trim()) || /decrease|reduz|weniger|minus|decrement/.test(label(el));
      for (const p of buttons.filter(el => visible(el) && plus(el))) {
        let parent = p.parentElement;
        for (let depth=0;parent&&depth<6;depth++,parent=parent.parentElement) {
          const group = Array.from(parent.querySelectorAll('button, [role="button"]')).filter(el => visible(el));
          const m = group.find(minus);
          if (!m || !group.includes(p)) continue;
          let q = null;
          const input = parent.querySelector('input');
          if (input && /^\d+$/.test(input.value||'')) q = Number(input.value);
          if (q===null) {
            const t=(parent.innerText||'').replace(/\s+/g,' ').trim();
            const match=t.match(/(?:^|[^\d])(\d{1,2})(?:[^\d]|$)/);
            if(match)q=Number(match[1]);
          }
          if(Number.isInteger(q)&&q>=0&&q<=99)return {plus_index:allButtons.indexOf(p),minus_index:allButtons.indexOf(m),quantity:q};
        }
      }
      return null;
    }"""
    try: return page.evaluate(script)
    except Exception: return None


def _rewe_add_button_index(page):
    """Find the red cart-plus action in the product content, excluding header navigation."""
    script = r"""
    () => {
      const root = document.querySelector('main') || document.body;
      const allButtons = Array.from(document.querySelectorAll('button, [role="button"]'));
      const buttons = allButtons.filter(el => root.contains(el));
      const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>24&&r.height>24&&s.visibility!=='hidden'&&s.display!=='none'; };
      const score = el => {
        const attrs = [el.innerText,el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('data-testid'),el.getAttribute('data-test'),el.className,...Array.from(el.querySelectorAll('svg')).flatMap(svg=>[svg.getAttribute('aria-label'),svg.getAttribute('data-icon'),svg.getAttribute('class')])].filter(Boolean).join(' ').toLowerCase();
        const hasCart = /warenkorb|cart|basket/.test(attrs);
        const hasPlus = /\+|plus|add.?to.?cart|hinzuf[uü]gen/.test(attrs);
        const hasSvg = !!el.querySelector('svg');
        const bg = getComputedStyle(el).backgroundColor.match(/\d+/g)||[];
        const red = bg.length>=3&&Number(bg[0])>130&&Number(bg[1])<110&&Number(bg[2])<110;
        let points = 0;
        if(hasCart)points+=5;
        if(hasPlus)points+=4;
        if(red&&hasSvg)points+=5;
        if(red&&hasPlus)points+=3;
        if(/in den warenkorb|add.?to.?cart/.test(attrs))points+=5;
        return points;
      };
      const candidates = buttons.map(el=>({index:allButtons.indexOf(el),points:visible(el)?score(el):0})).filter(x=>x.points>=10).sort((a,b)=>b.points-a.points);
      return candidates.length?candidates[0].index:null;
    }"""
    try: return page.evaluate(script)
    except Exception: return None


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
            size, unit = package(raw)
            cost, unit_cost = price_details(raw, size, unit)
            image_url = _image_url_from_card(box, anchor, url)
            external_id = href.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or hashlib.sha256((product_name + href).encode()).hexdigest()[:20]
            anchor_products.append({
                "external_id": external_id,
                "name_original": product_name[:300],
                "name_normalized": name_key,
                "ingredient": name_key,
                "brand": None,
                "category": category,
                "package_size": size if size is not None else 1,
                "package_unit": unit or "unknown",
                "price": cost,
                "price_per_unit": unit_cost if unit_cost is not None else ((cost / size) if cost is not None and size else None),
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
            # Merge complementary data instead of discarding a later image-bearing card.
            merged = dict(current)
            for key, value in product.items():
                if value is not None and (merged.get(key) is None or merged.get(key) == ""):
                    merged[key] = value
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
        """Add products and verify their final REWE quantity. Never checks out."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright Python package is not installed") from exc
        endpoint = os.getenv("BITEWISE_CHROME_CDP_URL", os.getenv("REWE_CHROME_CDP_URL", "http://127.0.0.1:9222")).rstrip("/")
        browser = page = None
        owns_page = False
        results = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(endpoint, timeout=15_000)
                if not browser.contexts: raise RuntimeError("Chrome for Testing has no browser context")
                context = browser.contexts[0]
                page = next((p for p in context.pages if urlsplit(p.url).hostname and urlsplit(p.url).hostname.lower() in {"www.rewe.de","rewe.de"}), None)
                if page is None:
                    page=context.new_page()
                    owns_page=True
                for item in products:
                    name=str(item.get("name") or "REWE product")
                    url=_canonical_product_url(item.get("product_url") or "")
                    target=max(1,min(99,int(item.get("packs") or 1)))
                    if not url:
                        results.append({"name":name,"status":"rejected","message":"Not a verified REWE product URL"});continue
                    try:
                        response=page.goto(url,wait_until="domcontentloaded",timeout=45_000)
                        if response and response.status>=400:raise RuntimeError("REWE product page returned HTTP "+str(response.status))
                        try:page.wait_for_load_state("networkidle",timeout=6_000)
                        except Exception:pass
                        body=page.locator("body").inner_text(timeout=8_000)
                        if re.search(r"Anmelden|Einloggen|Bitte melden Sie sich an",body[:2500],re.I) and re.search(r"Passwort|E-Mail-Adresse",body[:2500],re.I):
                            results.append({"name":name,"status":"login_required","message":"REWE session is not authenticated"});continue
                        if re.search(r"ausverkauft|nicht verfügbar|derzeit nicht lieferbar",body,re.I):
                            results.append({"name":name,"status":"unavailable","message":"REWE marks this product as unavailable"});continue
                        state=_rewe_cart_stepper_snapshot(page)
                        if state is None:
                            add_index=_rewe_add_button_index(page)
                            if add_index is None:
                                results.append({"name":name,"status":"not_added","message":"Could not identify REWE's red add-to-cart control"});continue
                            page.locator("button, [role='button']").nth(add_index).click(timeout=8_000)
                            for _ in range(30):
                                page.wait_for_timeout(300)
                                state=_rewe_cart_stepper_snapshot(page)
                                if state is not None:break
                        if state is None:
                            results.append({"name":name,"status":"submitted_unverified","packs_requested":target,"quantity_verified":False,"message":"Add control clicked but REWE's - quantity + stepper did not appear"});continue
                        current=int(state["quantity"])
                        for _ in range(min(99,max(0,target-current))):
                            state=_rewe_cart_stepper_snapshot(page)
                            if state is None:break
                            page.locator("button, [role='button']").nth(int(state["plus_index"])).click(timeout=5_000)
                            page.wait_for_timeout(250)
                        for _ in range(min(99,max(0,current-target))):
                            state=_rewe_cart_stepper_snapshot(page)
                            if state is None:break
                            page.locator("button, [role='button']").nth(int(state["minus_index"])).click(timeout=5_000)
                            page.wait_for_timeout(250)
                        final=_rewe_cart_stepper_snapshot(page)
                        actual=int(final["quantity"]) if final else None
                        ok=actual==target
                        results.append({"name":name,"status":"added" if ok else "quantity_unconfirmed","packs_requested":target,"quantity_verified":ok,"quantity_actual":actual,"message":f"REWE quantity verified: {actual}" if ok else f"Could not verify requested quantity {target}; REWE showed {actual}"})
                    except Exception as exc:results.append({"name":name,"status":"error","message":str(exc)[:240]})
        finally:
            if page and owns_page:
                try:page.close()
                except Exception:pass
            if browser:
                try:browser.close()
                except Exception:pass
        return {"results":results,"checkout_performed":False}

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
                        and urlsplit(candidate.url).hostname.lower() in {"www.rewe.de", "rewe.de"}
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
                                if current is None:
                                    by_id[product["external_id"]] = product
                                else:
                                    for key, value in product.items():
                                        if value is not None and (current.get(key) is None or current.get(key) == ""):
                                            current[key] = value

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
                        if current is None:
                            by_id[product["external_id"]] = product
                        else:
                            for key, value in product.items():
                                if value is not None and (current.get(key) is None or current.get(key) == ""):
                                    current[key] = value
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
