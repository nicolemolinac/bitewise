import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

try:
    from google.genai import types
except Exception:
    types = None

CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "meal_image_cache.json"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
PLACEHOLDER = ""

_STOPWORDS = {
    "and", "with", "the", "a", "an", "of", "in", "on", "style", "inspired",
    "warm", "quick", "easy", "fresh", "creamy", "crispy", "spicy", "sweet",
    "italian", "asian", "mexican", "mediterranean", "german", "french",
    "breakfast", "lunch", "dinner", "snack", "dessert", "dish", "food",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if len(token) >= 3 and token not in _STOPWORDS
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


def _meal_query(meal: dict) -> str:
    name = str(meal.get("name") or "").strip()
    cuisine = str(meal.get("cuisine") or "").strip()
    ingredients = []
    for item in meal.get("ingredients") or []:
        if isinstance(item, (list, tuple)) and item:
            ingredient = str(item[0]).strip()
        elif isinstance(item, dict):
            ingredient = str(item.get("ingredient") or item.get("name") or "").strip()
        else:
            ingredient = ""
        if ingredient and ingredient.lower() not in name.lower():
            ingredients.append(ingredient)
        if len(ingredients) >= 3:
            break
    parts = [name, *ingredients]
    if cuisine and cuisine.lower() not in name.lower():
        parts.append(cuisine)
    return " ".join(part for part in parts if part).strip()


def _cache_key(meal: dict) -> str:
    query = _meal_query(meal).lower()
    return re.sub(r"[^a-z0-9]+", "-", query).strip("-")[:220]


def _candidate_score(title: str, meal: dict) -> int:
    title_tokens = _tokens(title)
    name_tokens = _tokens(str(meal.get("name") or ""))
    ingredient_tokens = set()
    for item in (meal.get("ingredients") or [])[:4]:
        if isinstance(item, (list, tuple)) and item:
            ingredient_tokens |= _tokens(str(item[0]))
        elif isinstance(item, dict):
            ingredient_tokens |= _tokens(str(item.get("ingredient") or item.get("name") or ""))
    return 4 * len(title_tokens & name_tokens) + len(title_tokens & ingredient_tokens)


def _valid_image_url(url: str) -> bool:
    url = str(url or "").strip()
    if not url.startswith("https://"):
        return False
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
            timeout=8,
            stream=True,
            allow_redirects=True,
        )
        content_type = (response.headers.get("content-type") or "").lower()
        ok = response.ok and content_type.startswith("image/")
        response.close()
        return ok
    except Exception:
        return False


def _extract_page_image(page_url: str) -> str:
    if not str(page_url).startswith("https://"):
        return ""
    try:
        response = requests.get(
            page_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36"},
            timeout=8,
            allow_redirects=True,
        )
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        if content_type.startswith("image/"):
            return response.url if _valid_image_url(response.url) else ""
        text = response.text[:800000]
        patterns = [
            r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::url)?["\']',
            r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if not match:
                continue
            candidate = html.unescape(match.group(1).strip())
            candidate = urljoin(response.url, candidate)
            if _valid_image_url(candidate):
                return candidate
    except Exception:
        return ""
    return ""


def _urls_from_text(text: str) -> list[str]:
    urls = re.findall(r"https://[^\s<>\]\[\)\}\"']+", text or "")
    clean = []
    for value in urls:
        value = html.unescape(value.rstrip(".,;:"))
        if value not in clean:
            clean.append(value)
    return clean[:12]


def _gemini_direct_image(meal: dict, client, model: str) -> str:
    """Ask grounded Gemini for real candidate image URLs, then verify them ourselves."""
    if not client or types is None:
        return ""
    query = _meal_query(meal)
    prompt = (
        "Use Google Search to find an accurate appetizing photo for this exact dish: "
        f"{query}. Return up to 5 DIRECT HTTPS IMAGE URLs only, one URL per line. "
        "The URL must point to the actual image file (jpg/jpeg/png/webp), not a webpage. "
        "Prefer established recipe sites or Wikimedia. Never invent URLs."
    )
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0,
            ),
        )
    except Exception:
        return ""

    # First: direct URLs Gemini returned. These are always validated before use.
    for candidate in _urls_from_text(getattr(response, "text", "") or ""):
        if _valid_image_url(candidate):
            return candidate

    # Second: grounded source pages. Extract their real og:image and validate it.
    page_urls = []
    try:
        candidates = getattr(response, "candidates", None) or []
        metadata = getattr(candidates[0], "grounding_metadata", None) if candidates else None
        chunks = getattr(metadata, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            uri = str(getattr(web, "uri", "") or "") if web else ""
            if uri.startswith("https://") and uri not in page_urls:
                page_urls.append(uri)
    except Exception:
        pass

    for page_url in page_urls[:8]:
        image = _extract_page_image(page_url)
        if image:
            return image
    return ""


def _wikimedia_image(meal: dict) -> str:
    query = _meal_query(meal) + " food"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 12,
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": 1200,
        "origin": "*",
    }
    headers = {"User-Agent": "Bitewise/1.0 meal-image-resolver"}
    try:
        response = requests.get(WIKIMEDIA_API, params=params, headers=headers, timeout=8)
        response.raise_for_status()
        pages = list((response.json().get("query") or {}).get("pages", {}).values())
        candidates = []
        for page in pages:
            title = str(page.get("title") or "")
            info = (page.get("imageinfo") or [{}])[0]
            mime = str(info.get("mime") or "")
            url = str(info.get("thumburl") or info.get("url") or "")
            if not url.startswith("https://") or not mime.startswith("image/"):
                continue
            candidates.append((_candidate_score(title, meal), url))
        candidates.sort(key=lambda row: row[0], reverse=True)
        # Allow a weaker but still related Wikimedia match; direct Gemini validation is the next fallback.
        if candidates and candidates[0][0] >= 2 and _valid_image_url(candidates[0][1]):
            return candidates[0][1]
    except Exception:
        pass
    return ""


def resolve_meal_image(
    meal: dict,
    *,
    force: bool = False,
    gemini_client=None,
    gemini_model: str = "gemini-3.8-flash",
) -> str:
    """Return a real, validated image URL and cache it permanently.

    Broken/blank cached URLs are retried. No fake placeholder URL is cached anymore.
    """
    key = _cache_key(meal)
    cache = _load_cache()
    cached = str(cache.get(key) or "").strip()
    if not force and cached and _valid_image_url(cached):
        return cached

    # Gemini Search first when available because accuracy matters more than Wikimedia coverage.
    chosen = ""
    if gemini_client:
        chosen = _gemini_direct_image(meal, gemini_client, gemini_model)
    if not chosen:
        chosen = _wikimedia_image(meal)

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
    return any(host in value for host in ("images.unsplash.com", "source.unsplash.com", "placehold.co"))
