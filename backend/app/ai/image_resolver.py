import json
import re
from pathlib import Path
from urllib.parse import quote

import requests

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
        if len(ingredients) >= 3:
            break
    parts = [name, *ingredients]
    if cuisine and cuisine.lower() not in name.lower():
        parts.append(cuisine)
    parts.append("food dish")
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
    # Dish-name overlap matters most. Ingredient overlap is a weaker supporting signal.
    return 4 * len(title_tokens & name_tokens) + len(title_tokens & ingredient_tokens)


def resolve_meal_image(meal: dict, *, force: bool = False) -> str:
    """Resolve a meal photo without using LLM tokens.

    Uses Wikimedia Commons search, scores candidates against the actual dish name and
    ingredients, and caches the chosen URL permanently. If nothing looks relevant,
    returns a neutral Bitewise placeholder rather than a misleading photo.
    """
    key = _cache_key(meal)
    cache = _load_cache()
    if not force and key in cache:
        return str(cache[key] or PLACEHOLDER)

    query = _meal_query(meal)
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

    chosen = ""
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
            score = _candidate_score(title, meal)
            candidates.append((score, title, url))
        candidates.sort(key=lambda row: row[0], reverse=True)
        if candidates and candidates[0][0] >= 4:
            chosen = candidates[0][2]
    except Exception:
        chosen = ""

    result = chosen or PLACEHOLDER
    cache[key] = result
    _save_cache(cache)
    return result


def is_untrusted_generated_image(url: str) -> bool:
    """Old Gemini-provided remote food URLs were never verified against the recipe."""
    value = (url or "").lower().strip()
    if not value:
        return True
    return any(host in value for host in ("images.unsplash.com", "source.unsplash.com"))
