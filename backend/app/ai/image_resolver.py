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
PLACEHOLDER = "https://placehold.co/1200x800/f4efe7/6b5f52?text=Bitewise+meal"

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
        if len(ingredients) >= 2:
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
    if not str(url).startswith("https://"):
        return False
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 Bitewise/1.0"},
            timeout=7,
            stream=True,
            allow_redirects=True,
        )
        content_type = (response.headers.get("content-type") or "").lower()
        response.close()
        return response.ok and content_type.startswith("image/")
    except Exception:
        return False


def _extract_page_image(page_url: str) -> str:
    """Fetch a grounded source page and extract its social/hero image URL."""
    if not str(page_url).startswith("https://"):
        return ""
    try:
        response = requests.get(
            page_url,
            headers={"User-Agent": "Mozilla/5.0 Bitewise/1.0"},
            timeout=8,
            allow_redirects=True,
        )
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        if content_type.startswith("image/"):
            return response.url if _valid_image_url(response.url) else ""
        text = response.text[:600000]
        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
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
        value = value.rstrip(".,;:")
        if value not in clean:
            clean.append(value)
    return clean[:5]


def _gemini_grounded_image(meal: dict, client, model: str) -> str:
    """Use one tiny grounded search only when free lookup failed.

    Gemini finds an accurate page for the dish; Bitewise extracts and validates the real
    page image itself. The chosen URL is then cached permanently, so this usually costs
    model/search tokens only once per unique recipe.
    """
    if not client or types is None:
        return ""
    query = _meal_query(meal)
    prompt = (
        "Find the single best public recipe/food page whose photo visually matches this dish: "
        f"{query}. Return ONLY the page URL. Do not invent a URL."
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

    page_urls = _urls_from_text(getattr(response, "text", "") or "")
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

    for page_url in page_urls[:5]:
        image = _extract_page_image(page_url)
        if image:
            return image
    return ""


def _wikimedia_image(meal: dict) -> str:
    query = _meal_query(meal) + " food dish"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 8,
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": 1000,
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
        if candidates and candidates[0][0] >= 4:
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
    """Resolve and permanently cache a relevant meal photo.

    Order: valid cache -> free Wikimedia -> tiny grounded Gemini web search -> placeholder.
    Cached placeholders are intentionally retried when Gemini is available.
    """
    key = _cache_key(meal)
    cache = _load_cache()
    cached = str(cache.get(key) or "")
    if not force and cached and cached != PLACEHOLDER:
        return cached

    chosen = _wikimedia_image(meal)
    if not chosen and gemini_client:
        chosen = _gemini_grounded_image(meal, gemini_client, gemini_model)

    result = chosen or PLACEHOLDER
    cache[key] = result
    _save_cache(cache)
    return result


def is_untrusted_generated_image(url: str) -> bool:
    value = (url or "").lower().strip()
    if not value or value == PLACEHOLDER.lower():
        return True
    return any(host in value for host in ("images.unsplash.com", "source.unsplash.com"))
