import html
import json
import re
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import requests

CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "meal_image_cache.json"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
PLACEHOLDER = ""

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


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


def _meal_query(meal: dict) -> str:
    name = str(meal.get("name") or "").strip()
    ingredients = _ingredients(meal, 2)
    return " ".join([name, *ingredients, "recipe"]).strip()


def _cache_key(meal: dict) -> str:
    raw = f"{meal.get('name','')} {meal.get('description','')} {' '.join(map(str, meal.get('tags') or []))} {_meal_query(meal)}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:240]


def _valid_image_url(url: str) -> bool:
    url = html.unescape(str(url or "").strip())
    if not url.startswith("https://"):
        return False
    try:
        r = requests.get(url, headers={**_HEADERS, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}, timeout=6, stream=True, allow_redirects=True)
        ok = r.ok and (r.headers.get("content-type") or "").lower().startswith("image/")
        r.close()
        return ok
    except Exception:
        return False


def _search_result_pages(query: str) -> list[str]:
    """Return ordinary web result pages, not image-search thumbnails.

    This avoids the failure mode where image-search scraping returns logos, anatomy charts,
    memes or unrelated thumbnails. We fetch relevant recipe/article pages, then use their
    OpenGraph/Twitter image metadata, which is much more likely to represent the dish itself.
    """
    urls: list[str] = []

    # Bing web search is currently easier to parse reliably than Google result markup.
    try:
        r = requests.get(f"https://www.bing.com/search?q={quote_plus(query)}&count=10", headers=_HEADERS, timeout=10)
        r.raise_for_status()
        text = html.unescape(r.text)
        for href in re.findall(r'<a[^>]+href=["\'](https://[^"\']+)["\']', text, flags=re.I):
            host = urlparse(href).netloc.lower()
            if any(x in host for x in ("bing.com", "microsoft.com", "go.microsoft.com")):
                continue
            if href not in urls:
                urls.append(href)
    except Exception:
        pass

    # Lightweight Google web-search fallback.
    if len(urls) < 4:
        try:
            r = requests.get(f"https://www.google.com/search?q={quote_plus(query)}&num=10&hl=en", headers=_HEADERS, timeout=10)
            r.raise_for_status()
            text = html.unescape(r.text)
            for href in re.findall(r'href=["\']/url\?q=(https://[^&"\']+)', text, flags=re.I):
                host = urlparse(href).netloc.lower()
                if "google." in host:
                    continue
                if href not in urls:
                    urls.append(href)
        except Exception:
            pass

    return urls[:10]


def _page_image(page_url: str) -> str:
    try:
        r = requests.get(page_url, headers=_HEADERS, timeout=8, allow_redirects=True)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" not in ctype:
            return ""
        text = html.unescape(r.text[:800000])
    except Exception:
        return ""

    candidates: list[str] = []
    patterns = [
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text, flags=re.I))

    # Schema.org Recipe image fallback.
    candidates.extend(re.findall(r'"image"\s*:\s*"(https://[^"\\]+)"', text, flags=re.I))

    for candidate in candidates:
        candidate = html.unescape(candidate).replace("\\/", "/")
        candidate = urljoin(page_url, candidate)
        if _valid_image_url(candidate):
            return candidate
    return ""


def _source_page_image(meal: dict) -> str:
    name = str(meal.get("name") or "").strip()
    ingredients = _ingredients(meal, 2)
    queries = [
        f'"{name}" recipe',
        f"{name} {' '.join(ingredients)} recipe",
    ]
    low = f"{name} {meal.get('description','')} {' '.join(map(str, meal.get('tags') or []))}".lower()
    if "heart" in low and any(x in low for x in ("egg", "huevo")):
        queries.insert(0, '"heart shaped fried egg" recipe')
    elif "romantic" in low:
        queries.insert(0, f"romantic {name} recipe")

    for query in queries:
        for page in _search_result_pages(query):
            image = _page_image(page)
            if image:
                return image
    return ""


def resolve_meal_image(meal: dict, *, force: bool = False, gemini_client=None, gemini_model: str = "") -> str:
    # No Gemini is used for images. Keep legacy args only so older callers do not break.
    key = _cache_key(meal)
    cache = _load_cache()
    cached = str(cache.get(key) or "").strip()
    if not force and cached and _valid_image_url(cached):
        return cached

    chosen = _source_page_image(meal)
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
    return any(host in value for host in ("images.unsplash.com", "source.unsplash.com", "placehold.co", "encrypted-tbn", "mm.bing.net"))
