import html
import json
import re
from pathlib import Path
from urllib.parse import quote_plus

import requests

CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "meal_image_cache.json"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
PLACEHOLDER = ""

_STOPWORDS = {"and", "with", "the", "a", "an", "of", "in", "on", "style", "inspired", "warm", "quick", "easy", "fresh", "creamy", "crispy", "spicy", "sweet", "italian", "asian", "mexican", "mediterranean", "german", "french", "breakfast", "lunch", "dinner", "snack", "dessert", "dish", "food"}


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(token) >= 3 and token not in _STOPWORDS}


def _load_cache() -> dict:
    if not CACHE_FILE.exists(): return {}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8")); return data if isinstance(data, dict) else {}
    except Exception: return {}


def _save_cache(cache: dict) -> None:
    try: CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass


def _meal_query(meal: dict) -> str:
    name = str(meal.get("name") or "").strip(); cuisine = str(meal.get("cuisine") or "").strip(); ingredients = []
    for item in meal.get("ingredients") or []:
        if isinstance(item, (list, tuple)) and item: ingredient = str(item[0]).strip()
        elif isinstance(item, dict): ingredient = str(item.get("ingredient") or item.get("name") or "").strip()
        else: ingredient = ""
        if ingredient and ingredient.lower() not in name.lower(): ingredients.append(ingredient)
        if len(ingredients) >= 3: break
    parts = [name, *ingredients]
    if cuisine and cuisine.lower() not in name.lower(): parts.append(cuisine)
    return " ".join(part for part in parts if part).strip()


def _cache_key(meal: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _meal_query(meal).lower()).strip("-")[:220]


def _candidate_score(title: str, meal: dict) -> int:
    title_tokens = _tokens(title); name_tokens = _tokens(str(meal.get("name") or "")); ingredient_tokens = set()
    for item in (meal.get("ingredients") or [])[:4]:
        if isinstance(item, (list, tuple)) and item: ingredient_tokens |= _tokens(str(item[0]))
        elif isinstance(item, dict): ingredient_tokens |= _tokens(str(item.get("ingredient") or item.get("name") or ""))
    return 4 * len(title_tokens & name_tokens) + len(title_tokens & ingredient_tokens)


def _valid_image_url(url: str) -> bool:
    url = str(url or "").strip()
    if not url.startswith("https://"): return False
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"}, timeout=6, stream=True, allow_redirects=True)
        ok = response.ok and (response.headers.get("content-type") or "").lower().startswith("image/"); response.close(); return ok
    except Exception: return False


def _google_images_image(meal: dict) -> str:
    """Zero-Gemini image lookup: scrape Google Images result HTML, then validate the original image URL."""
    query = _meal_query(meal) + " recipe food"
    url = f"https://www.google.com/search?tbm=isch&safe=active&q={quote_plus(query)}"
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}, timeout=10)
        response.raise_for_status(); text = html.unescape(response.text)
        candidates = re.findall(r'https://[^"\\\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\\\s<>]*)?', text, flags=re.I)
        seen = set()
        for candidate in candidates[:60]:
            candidate = candidate.replace("\\u003d", "=").replace("\\u0026", "&")
            if candidate in seen: continue
            seen.add(candidate); lower = candidate.lower()
            if any(host in lower for host in ("gstatic.com", "googleusercontent.com/images/branding", "google.com/images")): continue
            if _valid_image_url(candidate): return candidate
    except Exception: return ""
    return ""


def _wikimedia_image(meal: dict) -> str:
    query = _meal_query(meal) + " food"
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": 1200, "origin": "*"}
    try:
        response = requests.get(WIKIMEDIA_API, params=params, headers={"User-Agent": "Bitewise/1.0 meal-image-resolver"}, timeout=8); response.raise_for_status()
        pages = list((response.json().get("query") or {}).get("pages", {}).values()); candidates = []
        for page in pages:
            title = str(page.get("title") or ""); info = (page.get("imageinfo") or [{}])[0]; mime = str(info.get("mime") or ""); url = str(info.get("thumburl") or info.get("url") or "")
            if url.startswith("https://") and mime.startswith("image/"): candidates.append((_candidate_score(title, meal), url))
        candidates.sort(key=lambda row: row[0], reverse=True)
        if candidates and candidates[0][0] >= 2 and _valid_image_url(candidates[0][1]): return candidates[0][1]
    except Exception: pass
    return ""


def resolve_meal_image(meal: dict, *, force: bool = False, gemini_client=None, gemini_model: str = "") -> str:
    # gemini_client/model are retained only for backward compatibility. They are intentionally ignored.
    key = _cache_key(meal); cache = _load_cache(); cached = str(cache.get(key) or "").strip()
    if not force and cached and _valid_image_url(cached): return cached
    chosen = _google_images_image(meal) or _wikimedia_image(meal)
    if chosen: cache[key] = chosen
    else: cache.pop(key, None)
    _save_cache(cache); return chosen


def is_untrusted_generated_image(url: str) -> bool:
    value = (url or "").lower().strip()
    if not value: return True
    return any(host in value for host in ("images.unsplash.com", "source.unsplash.com", "placehold.co"))
