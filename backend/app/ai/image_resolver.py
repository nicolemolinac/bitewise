import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageOps
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)
CDP_ENDPOINT = os.getenv("BITEWISE_CHROME_CDP_URL", "http://127.0.0.1:9222").rstrip("/")

CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "meal_image_cache.json"
IMAGE_DIR = Path(__file__).resolve().parents[2] / "data" / "recipe_images"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132 Safari/537.36",
}
_BAD_IMAGE_HINTS = (
    "logo", "icon", "avatar", "sprite", "favicon", "emoji", "banner",
    "youtube", "facebook", "instagram", "tiktok",
)


def _load_cache() -> dict:
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _ingredients(meal: dict, limit: int = 3) -> list[str]:
    result = []
    for item in meal.get("ingredients") or []:
        if isinstance(item, (list, tuple)) and item:
            name = str(item[0]).strip()
        elif isinstance(item, dict):
            name = str(item.get("ingredient") or item.get("name") or "").strip()
        else:
            name = ""
        if name and name.casefold() not in {x.casefold() for x in result}:
            result.append(name)
        if len(result) >= limit:
            break
    return result


def _query(meal: dict) -> str:
    name = str(meal.get("name") or "").strip()
    description = str(meal.get("description") or "").strip()
    tags = " ".join(str(x).strip() for x in (meal.get("tags") or [])[:3] if str(x).strip())
    ingredients = " ".join(_ingredients(meal, 3))
    # Search for the visual dish itself, not a generic recipe category.
    visual_terms = " ".join(x for x in (name, description, tags, ingredients) if x)
    visual_terms = re.sub(r"\s+", " ", visual_terms).strip()
    return f"{visual_terms} aesthetic food photography".strip()


def _cache_key(meal: dict) -> str:
    raw = "google-images-v2 " + _query(meal).casefold()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:220]


def _usable_url(url: str) -> bool:
    value = str(url or "").strip()
    low = value.lower()
    if not low.startswith("https://"):
        return False
    if low.startswith(("https://www.google.com/", "https://www.gstatic.com/images/branding")):
        return False
    if any(hint in low for hint in _BAD_IMAGE_HINTS):
        return False
    if any(host in low for host in ("gstatic.com/og/", "googleusercontent.com/logos")):
        return False
    return True


def _open_browser(playwright):
    """Attach to the user's already-running Chrome for Testing over CDP.

    Chrome is started separately with remote debugging enabled, so Bitewise
    never launches a second browser or takes ownership of the shared profile.
    """
    logger.info("Connecting to existing Chrome for Testing at %s", CDP_ENDPOINT)
    browser = playwright.chromium.connect_over_cdp(CDP_ENDPOINT, timeout=10_000)
    if not browser.contexts:
        browser.close()
        raise RuntimeError(
            f"Chrome at {CDP_ENDPOINT} has no available browser context"
        )
    logger.info("Connected to Chrome for Testing; reusing its existing profile")
    return browser


def _search_one(page, meal: dict) -> dict[str, str]:
    query = _query(meal)
    search_url = f"https://www.google.com/search?tbm=isch&safe=active&hl=en&gl=de&q={quote_plus(query)}"
    network_candidates: list[str] = []

    def on_response(response):
        try:
            content_type = (response.headers.get("content-type") or "").lower()
            if response.ok and content_type.startswith("image/") and _usable_url(response.url):
                network_candidates.append(response.url)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
        for label in ("Accept all", "I agree", "Alle akzeptieren", "Accept"):
            try:
                button = page.get_by_role("button", name=label)
                if button.count():
                    button.first.click(timeout=1200)
                    break
            except Exception:
                pass
        page.wait_for_timeout(1600)
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(500)

        # Google Images exposes thumbnail URLs and, on many result cards,
        # the original image and source-page URL in data attributes.
        dom_candidates = page.locator("img").evaluate_all("""imgs => imgs.map(img => {
          const card = img.closest('a') || img.parentElement?.closest('a');
          return {
            src: img.getAttribute('src') || '',
            dataSrc: img.getAttribute('data-src') || '',
            original: img.getAttribute('data-iurl') || img.getAttribute('data-original') || '',
            alt: img.getAttribute('alt') || '',
            width: img.naturalWidth || img.width || 0,
            height: img.naturalHeight || img.height || 0,
            page: card?.href || ''
          };
        })""")

        ordered = []
        # Prefer visible result thumbnails in DOM order, then network responses.
        for item in dom_candidates:
            if max(int(item.get("width") or 0), int(item.get("height") or 0)) < 120:
                continue
            image = item.get("original") or item.get("src") or item.get("dataSrc")
            if _usable_url(image):
                ordered.append({
                    "image": image,
                    "image_page": item.get("page") or "",
                    "photographer": "",
                    "search_query": query,
                })
        for image in network_candidates:
            if _usable_url(image):
                ordered.append({
                    "image": image,
                    "image_page": "",
                    "photographer": "",
                    "search_query": query,
                })

        unique = []
        seen = set()
        for item in ordered:
            if item["image"] not in seen:
                seen.add(item["image"])
                unique.append(item)
        return unique
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


def _persist_image(image_url: str, key: str) -> str:
    """Download, optimize as WebP and persist a recipe photo inside the Git repo."""
    value = str(image_url or "").strip()
    if value.startswith("/api/meal-photos/files/"):
        filename = Path(value).name
        return value if re.fullmatch(r"[a-f0-9]{24}[.]webp", filename) and (IMAGE_DIR / filename).is_file() else ""
    if not value.startswith("https://"):
        return ""

    name = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24] + ".webp"
    target = IMAGE_DIR / name
    if target.is_file():
        return "/api/meal-photos/files/" + name

    response = None
    try:
        response = requests.get(value, headers=_HEADERS, timeout=20, stream=True)
        response.raise_for_status()
        mime = (response.headers.get("content-type") or "").split(";", 1)[0].lower()
        if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            return ""
        chunks = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > 8 * 1024 * 1024:
                return ""
            chunks.append(chunk)
        raw = b"".join(chunks)
        if len(raw) < 256:
            return ""

        with Image.open(BytesIO(raw)) as source:
            source.seek(0)
            if source.width < 1 or source.height < 1 or source.width * source.height > 30_000_000:
                return ""
            rgba = ImageOps.exif_transpose(source).convert("RGBA")
            image = Image.new("RGB", rgba.size, (255, 255, 255))
            image.paste(rgba, mask=rgba.getchannel("A"))
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="WEBP", quality=82, method=6)
            optimized = output.getvalue()
        if len(optimized) < 100 or len(optimized) > 1_500_000:
            return ""

        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".webp.tmp")
        temporary.write_bytes(optimized)
        temporary.replace(target)
        return "/api/meal-photos/files/" + name
    except Exception:
        logger.warning("Could not persist recipe image %s", value[:160], exc_info=True)
        return ""
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def resolve_meal_images(meals: list[dict], *, force: bool = False) -> list[dict[str, str]]:
    """Resolve a batch of meal photos with one local Chrome/Chromium session.

    Uses Google Images, a local JSON cache and no Gemini/image-generation API.
    Returns one result per input meal; failed lookups return an empty image.
    """
    cache = _load_cache()
    results: list[dict[str, str]] = [{} for _ in meals]
    used_images: set[str] = set()
    pending = []

    for index, meal in enumerate(meals):
        key = _cache_key(meal)
        cached = cache.get(key)
        if not force and isinstance(cached, dict) and cached.get("image"):
            image = _persist_image(str(cached.get("image") or ""), key)
            if image and image not in used_images:
                results[index] = {"image":image,"image_page":str(cached.get("image_page") or ""),"photographer":"","search_query":str(cached.get("search_query") or _query(meal))}
                cached["image"] = image
                used_images.add(image)
                continue
        pending.append((index, key, meal))

    if pending:
        browser = None
        page = None
        try:
            with sync_playwright() as playwright:
                browser = _open_browser(playwright)
                # Use a fresh tab in the existing profile. Do not close or reset
                # the shared browser context, cookies, or other apps' tabs.
                context = browser.contexts[0]
                page = context.new_page()
                for index, key, meal in pending:
                    query = _query(meal)
                    logger.info("Searching Google Images for meal %d/%d: %s", index + 1, len(meals), query)
                    try:
                        candidates = _search_one(page, meal)
                        chosen = next((x for x in candidates if x["image"] not in used_images), None)
                        if chosen:
                            stored_image = _persist_image(chosen["image"], key)
                            if stored_image:
                                stored = {**chosen, "image": stored_image, "source_image": chosen["image"]}
                                results[index] = stored
                                used_images.add(stored_image)
                                cache[key] = {**stored, "updated_at": datetime.now(timezone.utc).isoformat()}
                            else:
                                results[index] = {"image":"","image_page":chosen.get("image_page",""),"photographer":"","search_query":query}
                            logger.info("Found image for %s", query)
                        else:
                            results[index] = {"image": "", "image_page": "", "photographer": "", "search_query": query}
                            logger.warning("No usable image found for %s", query)
                    except Exception:
                        logger.exception("Image search failed for meal: %s", query)
                        results[index] = {"image": "", "image_page": "", "photographer": "", "search_query": query}
                _save_cache(cache)
        except Exception:
            # Do not break recipe generation if Chrome/Playwright or Google is unavailable.
            logger.exception("Could not connect to Chrome for Testing or resolve meal photos")
            for index, _, meal in pending:
                if not results[index]:
                    results[index] = {"image": "", "image_page": "", "photographer": "", "search_query": _query(meal)}
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            if browser:
                try:
                    # For a CDP connection this disconnects Playwright; it does
                    # not shut down the externally launched Chrome process.
                    browser.close()
                except Exception:
                    pass

    return results


def resolve_meal_image(meal: dict, *, force: bool = False, gemini_client=None, gemini_model: str = "") -> str:
    """Compatibility wrapper for callers that need a single image."""
    result = resolve_meal_images([meal], force=force)[0]
    return result.get("image", "")


def is_untrusted_generated_image(url: str) -> bool:
    value = (url or "").lower().strip()
    if not value:
        return True
    return any(host in value for host in ("images.unsplash.com", "source.unsplash.com", "placehold.co", "mm.bing.net"))
