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

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", (value or "").lower())
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
    values: list[str] = []
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


def _visual_context(meal: dict) -> str:
    name = str(meal.get("name") or "")
    description = str(meal.get("description") or "")
    tags = " ".join(str(x) for x in (meal.get("tags") or []))
    return f"{name} {description} {tags}".strip()


def _meal_query(meal: dict) -> str:
    name = str(meal.get("name") or "").strip()
    ingredients = [x for x in _ingredients(meal, 2) if x.lower() not in name.lower()]
    return " ".join([name, *ingredients]).strip()


def _query_variants(meal: dict) -> list[str]:
    """Build precise, zero-Gemini Google Images queries."""
    name = str(meal.get("name") or "").strip()
    low = _visual_context(meal).lower()
    ingredients = _ingredients(meal, 2)
    variants: list[str] = []

    def add(query: str) -> None:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query.lower() not in {x.lower() for x in variants}:
            variants.append(query)

    if name:
        add(name)
        add(f"{name} recipe")

    if "heart" in low or "heart-shaped" in low:
        if any(word in low for word in ("egg", "huevo", "oeuf")):
            add("heart shaped fried egg")
            add("fried egg heart mold breakfast")
            add("romantic breakfast heart shaped egg")
        else:
            add(f"heart shaped {ingredients[0] if ingredients else name}")

    if "romantic" in low or "valentine" in low:
        add(f"romantic {name} breakfast food")
        add(f"valentines {name}")
    if "cute" in low:
        add(f"cute {name} food presentation")
    if "flower" in low or "rose" in low:
        add(f"flower shaped {name}")
    if "star" in low:
        add(f"star shaped {name}")

    visual = [word for word in _VISUAL_WORDS if word in low]
    if visual:
        add(f"{' '.join(visual[:3])} {name}")
    if ingredients:
        add(f"{name} {' '.join(ingredients)}")

    return variants[:7]


def _cache_key(meal: dict) -> str:
    raw = f"{_meal_query(meal)} {_visual_context(meal)}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:240]


def _valid_image_url(url: str) -> bool:
    url = html.unescape(str(url or "").strip())
    if not url.startswith("https://"):
        return False
    try:
        response = requests.get(
            url,
            headers={**_HEADERS, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
            timeout=6,
            stream=True,
            allow_redirects=True,
        )
        ok = response.ok and (response.headers.get("content-type") or "").lower().startswith("image/")
        response.close()
        return ok
    except Exception:
        return False


def _decode_google_url(value: str) -> str:
    return html.unescape(value or "").replace("\\u003d", "=").replace("\\u0026", "&").replace("\\/", "/")


def _google_image_candidates(query: str) -> list[str]:
    """Extract both original image URLs and Google thumbnail URLs from current Images HTML.

    Google frequently hides original URLs in JS blobs and serves thumbnails without file
    extensions. The old resolver only accepted URLs ending in .jpg/.png/.webp, which meant
    a perfectly healthy Google Images page could yield zero candidates and blank cards.
    """
    search_url = f"https://www.google.com/search?tbm=isch&safe=active&hl=en&q={quote_plus(query)}"
    try:
        response = requests.get(search_url, headers=_HEADERS, timeout=10)
        response.raise_for_status()
        text = response.text
    except Exception:
        return []

    raw: list[str] = []

    # Modern/legacy JS payloads containing original image URLs.
    for pattern in (
        r'"ou"\s*:\s*"(https?:\\?/\\?/[^"\\]+(?:\\.[^"\\]+)*)"',
        r'\["(https?:\\?/\\?/[^"\\]+?\.(?:jpg|jpeg|png|webp)(?:\\?[^"\\]*)?)"',
        r'(https://[^"\\\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\\\s<>]*)?)',
    ):
        raw.extend(re.findall(pattern, text, flags=re.I))

    # Crucial fallback: Google result thumbnails usually have NO filename extension.
    raw.extend(re.findall(
        r'https://encrypted-tbn\d+\.gstatic\.com/images\?[^"\'<>\\\s]+',
        text,
        flags=re.I,
    ))
    raw.extend(re.findall(
        r'(?:src|data-src)=["\'](https://[^"\']+)["\']',
        text,
        flags=re.I,
    ))

    clean: list[str] = []
    for candidate in raw:
        candidate = _decode_google_url(candidate)
        lower = candidate.lower()
        if not candidate.startswith("https://"):
            continue
        if "google.com/images/branding" in lower or "gstatic.com/og/_/ss" in lower:
            continue
        # Keep encrypted-tbn*.gstatic.com thumbnails: they are the most reliable hotlink-safe
        # fallback when publisher sites block direct image embedding.
        if candidate not in clean:
            clean.append(candidate)
    return clean[:120]


def _google_images_image(meal: dict) -> str:
    """Find a displayable image without consuming Gemini quota."""
    for query in _query_variants(meal):
        candidates = _google_image_candidates(query)
        if not candidates:
            continue

        # Prefer Google thumbnails because publisher/CDN links often block browser hotlinking.
        thumbnails = [u for u in candidates if "encrypted-tbn" in u and "gstatic.com" in u]
        originals = [u for u in candidates if u not in thumbnails]
        for candidate in [*thumbnails[:12], *originals[:12]]:
            if _valid_image_url(candidate):
                return candidate
    return ""


def _candidate_score(title: str, meal: dict) -> int:
    candidate_tokens = _tokens(title)
    name_tokens = _tokens(str(meal.get("name") or ""))
    ingredient_tokens = set()
    for ingredient in _ingredients(meal, 4):
        ingredient_tokens |= _tokens(ingredient)
    return 4 * len(candidate_tokens & name_tokens) + len(candidate_tokens & ingredient_tokens)


def _wikimedia_image(meal: dict) -> str:
    name = str(meal.get("name") or "").strip()
    # Try the exact dish first, then a simpler ingredient fallback so cards do not stay blank.
    queries = [
        f"{name} food".strip(),
        f"{' '.join(_ingredients(meal, 2))} food".strip(),
    ]
    for query in queries:
        if not query or query == "food":
            continue
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 20,
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": 1200,
            "origin": "*",
        }
        try:
            response = requests.get(WIKIMEDIA_API, params=params, headers={"User-Agent": "Bitewise/1.0 meal-image-resolver"}, timeout=8)
            response.raise_for_status()
            pages = list((response.json().get("query") or {}).get("pages", {}).values())
            ranked = []
            for page in pages:
                title = str(page.get("title") or "")
                info = (page.get("imageinfo") or [{}])[0]
                mime = str(info.get("mime") or "")
                url = str(info.get("thumburl") or info.get("url") or "")
                if url.startswith("https://") and mime.startswith("image/"):
                    ranked.append((_candidate_score(title, meal), url))
            ranked.sort(key=lambda row: row[0], reverse=True)
            # Exact dish query should be semantically related; ingredient fallback may score low,
            # but a related food photo is better than a permanent blank card.
            for score, candidate in ranked[:6]:
                if (score >= 1 or query != queries[0]) and _valid_image_url(candidate):
                    return candidate
        except Exception:
            continue
    return ""


def resolve_meal_image(meal: dict, *, force: bool = False, gemini_client=None, gemini_model: str = "") -> str:
    # gemini_client/model are kept only for backward compatibility and intentionally ignored.
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
