import html
import json
import re
from pathlib import Path
from urllib.parse import quote_plus

import requests

CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "meal_image_cache.json"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
PLACEHOLDER = ""

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/144 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_BAD_IMAGE_HINTS = (
    "logo", "icon", "avatar", "sprite", "favicon", "emoji", "banner", "thumbnail",
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
    raw = f"v4-google-images {_meal_context(meal)}"
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:240]


def _query_variants(meal: dict) -> list[str]:
    name = str(meal.get("name") or "").strip()
    ingredients = _ingredients(meal, 3)
    context = _meal_context(meal)
    variants: list[str] = []

    def add(query: str) -> None:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query.lower() not in {x.lower() for x in variants}:
            variants.append(query)

    if name:
        add(f"{name} recipe food")
        add(f'"{name}" recipe')

    if "heart" in context and any(x in context for x in ("egg", "huevo")):
        add("heart shaped fried egg breakfast")
    if "romantic" in context:
        add(f"romantic {name or 'breakfast'} food")
    if "rose" in context or "flower" in context:
        add(f"{name} flower shaped food")
    if "cute" in context:
        add(f"cute {name} food presentation")

    if ingredients:
        add(f"{name} {' '.join(ingredients[:2])} recipe")

    return variants[:5]


def _decode(value: str) -> str:
    return (
        html.unescape(value or "")
        .replace("\\u003d", "=")
        .replace("\\u0026", "&")
        .replace("\\u002F", "/")
        .replace("\\/", "/")
    )


def _google_image_candidates(query: str) -> list[str]:
    """Scrape Google Images result HTML and return actual image URLs.

    Prefer publisher/original image URLs (`ou`) and only then Google CDN thumbnails.
    This mirrors the user experience of searching Google Images and choosing a food photo.
    """
    url = f"https://www.google.com/search?tbm=isch&safe=active&hl=en&gl=de&q={quote_plus(query)}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.raise_for_status()
        text = r.text
    except Exception:
        return []

    raw: list[str] = []

    # Older/newer Google image metadata embeds originals as ou/murl-like JSON fields.
    patterns = [
        r'"ou"\s*:\s*"(https?:\\?/\\?/[^"\\]+(?:\\.[^"\\]+)*)"',
        r'"murl"\s*:\s*"(https?:\\?/\\?/[^"\\]+)"',
        r'\["(https?:\\?/\\?/[^"\\]+?\.(?:jpg|jpeg|png|webp|avif)(?:\\?[^"\\]*)?)"',
        r'(https://[^"\\\s<>]+?\.(?:jpg|jpeg|png|webp|avif)(?:\?[^"\\\s<>]*)?)',
    ]
    for pattern in patterns:
        raw.extend(re.findall(pattern, text, flags=re.I))

    # Google CDN image thumbnails are allowed only after original URLs.
    raw.extend(re.findall(r'https://encrypted-tbn\d+\.gstatic\.com/images\?[^"\'<>\\\s]+', text, flags=re.I))

    clean: list[str] = []
    for candidate in raw:
        candidate = _decode(candidate).strip()
        low = candidate.lower()
        if not candidate.startswith("https://"):
            continue
        if any(bad in low for bad in _BAD_IMAGE_HINTS):
            continue
        if "google.com/images/branding" in low or "gstatic.com/og/_/ss" in low:
            continue
        if candidate not in clean:
            clean.append(candidate)

    originals = [u for u in clean if "encrypted-tbn" not in u and "gstatic.com" not in u]
    thumbnails = [u for u in clean if u not in originals]
    return [*originals[:40], *thumbnails[:40]]


def _valid_image_url(url: str) -> bool:
    if not str(url or "").startswith("https://"):
        return False
    try:
        r = requests.get(
            url,
            headers={**_HEADERS, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
            timeout=7,
            stream=True,
            allow_redirects=True,
        )
        ctype = (r.headers.get("content-type") or "").lower()
        length = int(r.headers.get("content-length") or 0)
        ok = r.ok and ctype.startswith("image/") and (length == 0 or length >= 5000)
        r.close()
        return ok
    except Exception:
        return False


def _google_images_image(meal: dict) -> str:
    for query in _query_variants(meal):
        candidates = _google_image_candidates(query)
        for candidate in candidates:
            if _valid_image_url(candidate):
                return candidate
    return ""


def resolve_meal_image(meal: dict, *, force: bool = False, gemini_client=None, gemini_model: str = "") -> str:
    # No Gemini usage: images come directly from Google Images search results.
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
    # Old fixed/fallback images must be repaired after this resolver upgrade.
    return any(
        host in value
        for host in (
            "images.unsplash.com",
            "source.unsplash.com",
            "placehold.co",
            "mm.bing.net",
        )
    )
