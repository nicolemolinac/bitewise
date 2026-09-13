import html
import json
import re
from pathlib import Path
from urllib.parse import quote_plus

import requests
from playwright.sync_api import sync_playwright

CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "meal_image_cache.json"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/144 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_BAD_IMAGE_HINTS = (
    "logo", "icon", "avatar", "sprite", "favicon", "emoji", "banner",
    "youtube", "facebook", "instagram", "tiktok", "pinterest",
)


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _ingredients(meal: dict, limit: int = 3) -> list[str]:
    out: list[str] = []
    for item in meal.get("ingredients") or []:
        if isinstance(item, (list, tuple)) and item:
            value = str(item[0]).strip()
        elif isinstance(item, dict):
            value = str(item.get("ingredient") or item.get("name") or "").strip()
        else:
            value = ""
        if value and value.lower() not in {x.lower() for x in out}:
            out.append(value)
        if len(out) >= limit:
            break
    return out


def _meal_context(meal: dict) -> str:
    return " ".join(
        [
            str(meal.get("name") or ""),
            str(meal.get("description") or ""),
            " ".join(str(x) for x in (meal.get("tags") or [])),
            *(_ingredients(meal, 3)),
        ]
    ).lower()


def _cache_key(meal: dict) -> str:
    raw = f"v6-playwright-google-images {_meal_context(meal)}"
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:240]


def _query_variants(meal: dict) -> list[str]:
    name = str(meal.get("name") or "").strip()
    context = _meal_context(meal)
    variants: list[str] = []

    def add(query: str) -> None:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query.lower() not in {x.lower() for x in variants}:
            variants.append(query)

    if "heart" in context and "egg" in context:
        add("heart shaped fried egg breakfast recipe")
    if "romantic" in context:
        add(f"romantic {name or 'breakfast'} recipe food")
    if name:
        add(f"{name} recipe food")
        add(f'"{name}" recipe food')
    return variants[:4]


def _clean_candidate(value: str) -> str:
    value = html.unescape(value or "").strip()
    value = value.replace("\\u003d", "=").replace("\\u0026", "&").replace("\\/", "/")
    return value


def _playwright_image_candidates(query: str) -> list[str]:
    search_url = f"https://www.google.com/search?tbm=isch&safe=active&hl=en&gl=de&q={quote_plus(query)}"
    candidates: list[str] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=_HEADERS["User-Agent"],
                locale="en-US",
                viewport={"width": 1440, "height": 1100},
            )
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            # Consent screens occasionally appear in Germany. Try common accept buttons but
            # don't fail if Google changes the wording.
            for label in ("Accept all", "I agree", "Alle akzeptieren", "Accept"): 
                try:
                    button = page.get_by_role("button", name=label)
                    if button.count():
                        button.first.click(timeout=1500)
                        page.wait_for_timeout(800)
                        break
                except Exception:
                    pass

            page.wait_for_timeout(1800)
            imgs = page.locator("img")
            count = min(imgs.count(), 120)
            for i in range(count):
                img = imgs.nth(i)
                for attr in ("src", "data-src"):
                    try:
                        src = img.get_attribute(attr)
                    except Exception:
                        src = None
                    if src:
                        candidates.append(src)

                # Google result images sometimes expose a larger URL in srcset.
                try:
                    srcset = img.get_attribute("srcset")
                except Exception:
                    srcset = None
                if srcset:
                    for part in srcset.split(","):
                        candidates.append(part.strip().split(" ")[0])

            browser.close()
    except Exception:
        return []

    clean: list[str] = []
    for candidate in candidates:
        candidate = _clean_candidate(candidate)
        low = candidate.lower()
        if not candidate.startswith("https://"):
            continue
        if any(bad in low for bad in _BAD_IMAGE_HINTS):
            continue
        if "google.com/images/branding" in low or "gstatic.com/og/_/ss" in low:
            continue
        if candidate not in clean:
            clean.append(candidate)
    return clean


def _valid_image_url(url: str) -> bool:
    if not str(url or "").startswith("https://"):
        return False
    try:
        r = requests.get(
            url,
            headers={**_HEADERS, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8", "Referer": "https://www.google.com/"},
            timeout=8,
            stream=True,
            allow_redirects=True,
        )
        ctype = (r.headers.get("content-type") or "").lower()
        ok = r.ok and ctype.startswith("image/")
        r.close()
        return ok
    except Exception:
        return False


def _google_images_image(meal: dict) -> str:
    for query in _query_variants(meal):
        for candidate in _playwright_image_candidates(query):
            if _valid_image_url(candidate):
                return candidate
    return ""


def resolve_meal_image(meal: dict, *, force: bool = False, gemini_client=None, gemini_model: str = "") -> str:
    key = _cache_key(meal)
    cache = _load_cache()
    cached = str(cache.get(key) or "").strip()
    if not force and cached and _valid_image_url(cached):
        return cached

    chosen = _google_images_image(meal)
    if chosen:
        cache[key] = chosen
    else:
        cache.pop(key, None)
    _save_cache(cache)
    return chosen


def is_untrusted_generated_image(url: str) -> bool:
    value = (url or "").lower().strip()
    if not value:
        return True
    return any(host in value for host in ("images.unsplash.com", "source.unsplash.com", "placehold.co", "mm.bing.net"))
