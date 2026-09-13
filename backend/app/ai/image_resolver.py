import html
import json
import re
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests

CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "meal_image_cache.json"
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
PLACEHOLDER = ""

_STOPWORDS = {
    "and", "with", "the", "a", "an", "of", "in", "on", "style", "inspired",
    "warm", "quick", "easy", "fresh", "creamy", "crispy", "spicy", "sweet",
    "italian", "asian", "mexican", "mediterranean", "german", "french",
    "breakfast", "lunch", "dinner", "snack", "dessert", "dish", "food",
    "recipe", "recipes", "photo", "image", "homemade",
}

_VISUAL_WORDS = {
    "heart", "heart-shaped", "romantic", "cute", "flower", "rose", "star", "bunny",
    "bear", "smiley", "rainbow", "pink", "red", "layered", "swirl", "spiral", "bow",
    "christmas", "halloween", "valentine", "birthday", "elegant", "aesthetic",
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


def _ingredients(meal: dict, limit: int = 3) -> list[str]:
    values = []
    for item in meal.get("ingredients") or []:
        if isinstance(item, (list, tuple)) and item:
            value = str(item[0]).strip()
        elif isinstance(item, dict):
            value = str(item.get("ingredient") or item.get("name") or "").strip()
        else:
            value = ""
        if value and value.lower() not in {x.lower() for x in values}:
            values.append(value)
        if len(values) >= limit:
            break
    return values


def _meal_query(meal: dict) -> str:
    name = str(meal.get("name") or "").strip()
    cuisine = str(meal.get("cuisine") or "").strip()
    ingredients = [x for x in _ingredients(meal) if x.lower() not in name.lower()]
    parts = [name, *ingredients]
    if cuisine and cuisine.lower() not in name.lower():
        parts.append(cuisine)
    return " ".join(part for part in parts if part).strip()


def _visual_context(meal: dict) -> str:
    name = str(meal.get("name") or "")
    description = str(meal.get("description") or "")
    tags = " ".join(str(x) for x in (meal.get("tags") or []))
    return f"{name} {description} {tags}".strip()


def _query_variants(meal: dict) -> list[str]:
    """Build precise zero-token search variants for visually specific dishes."""
    name = str(meal.get("name") or "").strip()
    context = _visual_context(meal)
    low = context.lower()
    ingredients = _ingredients(meal, 2)
    visual = [w for w in _VISUAL_WORDS if w in low]
    variants: list[str] = []

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q.lower() not in {x.lower() for x in variants}:
            variants.append(q)

    # Exact generated dish name first. This is intentionally not diluted with extra ingredients.
    if name:
        add(f'"{name}"')
        add(name)

    # Explicit presentation words are hard search constraints.
    if visual:
        visual_phrase = " ".join(visual[:3])
        add(f"{name} {visual_phrase}")
        if ingredients:
            add(f"{visual_phrase} {' '.join(ingredients)}")

    # High-value semantic rewrites for common aesthetic recipes.
    if "heart" in low or "heart-shaped" in low:
        if any(word in low for word in ("egg", "huevo", "oeuf", "ei ")):
            add("heart shaped fried egg")
            add("fried egg heart mold")
            add("romantic breakfast heart shaped egg")
            add("heart egg breakfast")
        else:
            add(f"heart shaped {ingredients[0] if ingredients else name}")
            add(f"romantic {name} heart shaped")
    if "romantic" in low or "valentine" in low:
        add(f"romantic {name}")
        add(f"valentines {name}")
    if "cute" in low:
        add(f"cute {name} food presentation")
    if "flower" in low or "rose" in low:
        add(f"flower shaped {name}")
    if "star" in low:
        add(f"star shaped {name}")

    # Last precise fallback before generic food imagery.
    if ingredients:
        add(f"{name} {' '.join(ingredients)}")
    add(f"{name} plated recipe")
    return variants[:8]


def _cache_key(meal: dict) -> str:
    context = f"{_meal_query(meal)} {_visual_context(meal)}".lower()
    return re.sub(r"[^a-z0-9]+", "-", context).strip("-")[:240]


def _candidate_score(text: str, meal: dict, query: str = "") -> int:
    candidate_tokens = _tokens(text)
    name_tokens = _tokens(str(meal.get("name") or ""))
    visual_tokens = _tokens(_visual_context(meal)) & _VISUAL_WORDS
    query_tokens = _tokens(query)
    ingredient_tokens = set()
    for ingredient in _ingredients(meal, 4):
        ingredient_tokens |= _tokens(ingredient)
    return (
        5 * len(candidate_tokens & name_tokens)
        + 5 * len(candidate_tokens & visual_tokens)
        + 2 * len(candidate_tokens & query_tokens)
        + len(candidate_tokens & ingredient_tokens)
    )


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
            timeout=6,
            stream=True,
            allow_redirects=True,
        )
        ok = response.ok and (response.headers.get("content-type") or "").lower().startswith("image/")
        response.close()
        return ok
    except Exception:
        return False


def _url_text(url: str) -> str:
    try:
        parsed = urlparse(url)
        return html.unescape(f"{parsed.netloc} {parsed.path} {parsed.query}").replace("-", " ").replace("_", " ")
    except Exception:
        return url


def _google_image_candidates(query: str) -> list[str]:
    url = f"https://www.google.com/search?tbm=isch&safe=active&q={quote_plus(query)}"
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=10,
        )
        response.raise_for_status()
        text = html.unescape(response.text)
        candidates = re.findall(
            r'https://[^"\\\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\\\s<>]*)?',
            text,
            flags=re.I,
        )
        clean = []
        for candidate in candidates[:100]:
            candidate = candidate.replace("\\u003d", "=").replace("\\u0026", "&")
            lower = candidate.lower()
            if any(host in lower for host in ("gstatic.com", "googleusercontent.com/images/branding", "google.com/images")):
                continue
            if candidate not in clean:
                clean.append(candidate)
        return clean
    except Exception:
        return []


def _google_images_image(meal: dict) -> str:
    """Zero-Gemini lookup with semantic query expansion for visually specific dishes."""
    visual_tokens = _tokens(_visual_context(meal)) & _VISUAL_WORDS
    for query_index, query in enumerate(_query_variants(meal)):
        candidates = _google_image_candidates(query)
        if not candidates:
            continue
        ranked = sorted(
            candidates,
            key=lambda url: _candidate_score(_url_text(url), meal, query),
            reverse=True,
        )
        # For visually specific dishes prefer a URL that contains some semantic evidence.
        # If Google strips descriptive filenames, trust top result only after trying several precise queries.
        for candidate in ranked[:8]:
            score = _candidate_score(_url_text(candidate), meal, query)
            if visual_tokens and query_index < 4 and score == 0:
                continue
            if _valid_image_url(candidate):
                return candidate
    return ""


def _wikimedia_image(meal: dict) -> str:
    # Wikimedia is a final fallback; use the simplest dish concept because its coverage of aesthetic food is limited.
    name = str(meal.get("name") or "").strip()
    query = f"{name} {' '.join(_ingredients(meal, 2))} food".strip()
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 16,
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": 1200,
        "origin": "*",
    }
    try:
        response = requests.get(
            WIKIMEDIA_API,
            params=params,
            headers={"User-Agent": "Bitewise/1.0 meal-image-resolver"},
            timeout=8,
        )
        response.raise_for_status()
        pages = list((response.json().get("query") or {}).get("pages", {}).values())
        candidates = []
        for page in pages:
            title = str(page.get("title") or "")
            info = (page.get("imageinfo") or [{}])[0]
            mime = str(info.get("mime") or "")
            url = str(info.get("thumburl") or info.get("url") or "")
            if url.startswith("https://") and mime.startswith("image/"):
                candidates.append((_candidate_score(title, meal, query), url))
        candidates.sort(key=lambda row: row[0], reverse=True)
        if candidates and candidates[0][0] >= 2 and _valid_image_url(candidates[0][1]):
            return candidates[0][1]
    except Exception:
        pass
    return ""


def resolve_meal_image(meal: dict, *, force: bool = False, gemini_client=None, gemini_model: str = "") -> str:
    # gemini_client/model remain only for backward compatibility and are intentionally ignored.
    key = _cache_key(meal)
    cache = _load_cache()
    cached = str(cache.get(key) or "").strip()
    if not force and cached and _valid_image_url(cached):
        return cached

    chosen = _google_images_image(meal) or _wikimedia_image(meal)
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
