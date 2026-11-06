"""Backfill missing REWE product images by visiting each product detail page.

Run from backend/: python fill_rewe_product_images.py
The default is a small, sequential 10-product trial. Use --all only after
checking the trial results. Existing product_url values are never modified.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from app.database import Product, SessionLocal

logger = logging.getLogger("rewe_image_backfill")
CDP_ENDPOINT = os.getenv("BITEWISE_CHROME_CDP_URL", "http://127.0.0.1:9222").rstrip("/")
ALLOWED_HOSTS = {"www.rewe.de", "rewe.de"}


def _valid_product_url(value: str | None) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
        return (
            parsed.scheme == "https"
            and parsed.hostname in ALLOWED_HOSTS
            and parsed.path.startswith("/shop/p/")
        )
    except Exception:
        return False


def _valid_image_url(value: str | None, base_url: str) -> str | None:
    from urllib.parse import urljoin

    value = str(value or "").strip()
    if not value or value.startswith(("data:", "blob:")):
        return None
    absolute = urljoin(base_url, value)
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return None
    low = absolute.lower()
    if any(token in low for token in ("placeholder", "logo", "icon", "sprite", "avatar")):
        return None
    return absolute


def _product_image_from_html(html: str, base_url: str) -> str | None:
    """Extract a product-specific image, preferring page metadata and Product JSON-LD."""
    soup = BeautifulSoup(html, "html.parser")

    for selector in (
        'meta[property="og:image"]',
        'meta[property="og:image:secure_url"]',
        'meta[name="twitter:image"]',
    ):
        node = soup.select_one(selector)
        if node:
            image = _valid_image_url(node.get("content"), base_url)
            if image:
                return image

    def walk(node):
        if isinstance(node, dict):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(item).lower().rstrip("/").endswith("product") for item in types):
                raw = node.get("image")
                if isinstance(raw, list):
                    for item in raw:
                        candidate = item.get("url") or item.get("contentUrl") if isinstance(item, dict) else item
                        image = _valid_image_url(candidate, base_url)
                        if image:
                            return image
                elif isinstance(raw, dict):
                    image = _valid_image_url(raw.get("url") or raw.get("contentUrl"), base_url)
                    if image:
                        return image
                else:
                    image = _valid_image_url(raw, base_url)
                    if image:
                        return image
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found:
                    return found
        return None

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            found = walk(json.loads(raw))
        except (TypeError, ValueError):
            continue
        if found:
            return found

    for node in soup.select("main img, [data-testid*='product'] img, img"):
        for attr in ("data-zoom-image", "data-src", "data-lazy-src", "data-original", "src"):
            image = _valid_image_url(node.get(attr), base_url)
            if image:
                return image
        for attr in ("data-srcset", "srcset"):
            srcset = node.get(attr)
            if not srcset:
                continue
            candidates = []
            for entry in str(srcset).split(","):
                bits = entry.strip().split()
                if bits:
                    match = re.search(r"(\d+(?:\.\d+)?)(w|x)", bits[1]) if len(bits) > 1 else None
                    score = float(match.group(1)) if match else 1.0
                    image = _valid_image_url(bits[0], base_url)
                    if image:
                        candidates.append((score, image))
            if candidates:
                return max(candidates)[1]
    return None


def _open_existing_browser(playwright):
    browser = playwright.chromium.connect_over_cdp(CDP_ENDPOINT, timeout=15_000)
    if not browser.contexts:
        browser.close()
        raise RuntimeError(f"Chrome at {CDP_ENDPOINT} has no browser context")
    return browser


def backfill(limit: int | None = 10, delay: float = 1.2) -> dict:
    db = SessionLocal()
    browser = page = None
    stats = {"checked": 0, "saved": 0, "not_found": 0, "errors": 0}
    try:
        query = (
            db.query(Product)
            .filter(Product.supermarket == "REWE")
            .filter(Product.image_url.is_(None) | (Product.image_url == ""))
            .filter(Product.product_url.isnot(None))
            .order_by(Product.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        products = query.all()
        logger.info("Products queued for image lookup: %d", len(products))
        if not products:
            return stats

        with sync_playwright() as playwright:
            browser = _open_existing_browser(playwright)
            context = browser.contexts[0]
            page = context.new_page()
            for index, product in enumerate(products, start=1):
                stats["checked"] += 1
                product_url = product.product_url
                if not _valid_product_url(product_url):
                    stats["errors"] += 1
                    logger.warning("[%d/%d] Skipping invalid product URL: %s", index, len(products), product_url)
                    continue
                try:
                    response = page.goto(product_url, wait_until="domcontentloaded", timeout=35_000)
                    if response and response.status >= 400:
                        raise RuntimeError(f"HTTP {response.status}")
                    try:
                        page.wait_for_load_state("networkidle", timeout=5_000)
                    except Exception:
                        pass
                    page.wait_for_timeout(700)
                    html = page.content()
                    image_url = _product_image_from_html(html, page.url or product_url)
                    if not image_url:
                        # React-rendered product images may only be exposed as currentSrc.
                        rendered = page.locator("main img, img").evaluate_all(
                            "nodes => nodes.map(n => n.currentSrc || n.src || n.getAttribute('data-src') || '')"
                        )
                        for candidate in rendered:
                            image_url = _valid_image_url(candidate, page.url or product_url)
                            if image_url:
                                break
                    if image_url:
                        product.image_url = image_url
                        db.commit()
                        stats["saved"] += 1
                        logger.info("[%d/%d] SAVED %s -> %s", index, len(products), product.name_original, image_url)
                    else:
                        stats["not_found"] += 1
                        logger.warning("[%d/%d] No product image found: %s", index, len(products), product.name_original)
                except Exception as exc:
                    db.rollback()
                    stats["errors"] += 1
                    logger.warning("[%d/%d] Failed %s: %s", index, len(products), product.name_original, str(exc)[:220])
                if index < len(products):
                    time.sleep(max(0.0, delay))
        return stats
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()  # Disconnects Playwright; does not terminate the shared Chrome process.
            except Exception:
                pass
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Fill missing REWE product image URLs from product detail pages.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--limit", type=int, default=10, help="Maximum products to process (default: 10).")
    group.add_argument("--all", action="store_true", help="Process every REWE product with a missing image.")
    parser.add_argument("--delay", type=float, default=1.2, help="Seconds to wait between product pages.")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    stats = backfill(limit=None if args.all else max(1, args.limit), delay=args.delay)
    print(
        "REWE image backfill finished: "
        f"checked={stats['checked']}, saved={stats['saved']}, "
        f"not_found={stats['not_found']}, errors={stats['errors']}"
    )


if __name__ == "__main__":
    main()
