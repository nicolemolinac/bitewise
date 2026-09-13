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

_STOPWORDS = {
    "the", "and", "with", "for", "from", "into", "your", "you", "this", "that", "recipe",
    "recipes", "easy", "quick", "simple", "classic", "fresh", "homemade", "food", "dish",
    "breakfast", "lunch", "dinner", "dessert", "snack", "bowl", "plate", "style",
}

_BAD_PAGE_HINTS = {
    "orthopedic", "orthopaedic", "anatomy", "clinic", "hospital", "vlog", "youtube", "fuel",
    "petrol", "gas station", "astronomy", "government", "map", "travel", "real estate",
}

_TRUSTED_RECIPE_HOSTS = {
    "allrecipes.com", "bbcgoodfood.com", "foodnetwork.com", "simplyrecipes.com", "delish.com",
    "tasteofhome.com", "seriouseats.com", "recipetineats.com", "thekitchn.com", "eatingwell.com",
    "bonappetit.com", "epicurious.com", "loveandlemons.com", "damndelicious.net", "budgetbytes.com",
    "gimmesomeoven.com", "minimalistbaker.com", "cookieandkate.com", "skinnytaste.com",
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
    raw = f"v3 {meal.get('name','')} {meal.get('description','')} {' '.join(map(str, meal.get('tags') or []))} {_meal_query(meal)}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:240]


def _valid_image_url(url: str) -> bool:
    url = html.unescape(str(url or "").strip())
    if not url.startswith("https://"):
        return False
    try:
        r = requests.get(
            url,
            headers={**_HEADERS, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
            timeout=6,
            stream=True,
            allow_redirects=True,
        )
        ctype = (r.headers.get("content-type") or "").lower()
        ok = r.ok and ctype.startswith("image/")
        r.close()
        return ok
    except Exception:
        return False


def _host_is_trusted(host: str) -> bool:
    host = (host or "").lower().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in _TRUSTED_RECIPE_HOSTS)


def _search_result_pages(query: str) -> list[str]:
    urls: list[str] = []

    try:
        r = requests.get(f"https://www.bing.com/search?q={quote_plus(query)}&count=12", headers=_HEADERS, timeout=10)
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

    if len(urls) < 6:
        try:
            r = requests.get(f"https://www.google.com/search?q={quote_plus(query)}&num=12&hl=en", headers=_HEADERS, timeout=10)
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

    # Recipe publishers first, then everything else.
    urls.sort(key=lambda u: (not _host_is_trusted(urlparse(u).netloc), urls.index(u) if u in urls else 999))
    return urls[:14]


def _json_ld_recipe_images(text: str) -> list[str]:
    images: list[str] = []
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', text, flags=re.I | re.S):
        try:
            data = json.loads(html.unescape(block))
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            node_type = node.get("@type")
            types = [node_type] if isinstance(node_type, str) else (node_type or [])
            if any(str(t).lower() == "recipe" for t in types):
                raw = node.get("image")
                if isinstance(raw, str):
                    images.append(raw)
                elif isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, str):
                            images.append(item)
                        elif isinstance(item, dict) and item.get("url"):
                            images.append(str(item["url"]))
                elif isinstance(raw, dict) and raw.get("url"):
                    images.append(str(raw["url"]))
    return images


def _page_metadata(page_url: str) -> tuple[list[str], str, str, str, bool]:
    try:
        r = requests.get(page_url, headers=_HEADERS, timeout=8, allow_redirects=True)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" not in ctype:
            return [], "", "", "", False
        text = html.unescape(r.text[:900000])
    except Exception:
        return [], "", "", "", False

    def first(patterns: list[str]) -> str:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I | re.S)
            if match:
                return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
        return ""

    title = first([
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r'<title[^>]*>(.*?)</title>',
    ])
    description = first([
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
    ])

    recipe_images = _json_ld_recipe_images(text)
    candidates: list[str] = list(recipe_images)
    for pattern in [
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
    ]:
        candidates.extend(re.findall(pattern, text, flags=re.I))

    clean: list[str] = []
    for candidate in candidates:
        candidate = html.unescape(str(candidate)).replace("\\/", "/")
        candidate = urljoin(page_url, candidate)
        if candidate.startswith("https://") and candidate not in clean:
            clean.append(candidate)

    return clean, title, description, text[:140000], bool(recipe_images)


def _page_relevance_score(meal: dict, page_url: str, title: str, description: str, body_preview: str, has_recipe_schema: bool) -> int:
    name_tokens = _tokens(str(meal.get("name") or ""))
    ingredient_tokens = set()
    for ingredient in _ingredients(meal, 4):
        ingredient_tokens |= _tokens(ingredient)

    page_text = f"{urlparse(page_url).path} {title} {description} {body_preview[:24000]}".lower()
    page_tokens = _tokens(page_text)

    if any(hint in page_text for hint in _BAD_PAGE_HINTS):
        return -100

    name_overlap = len(page_tokens & name_tokens)
    ingredient_overlap = len(page_tokens & ingredient_tokens)
    score = 6 * name_overlap + 3 * ingredient_overlap

    host = urlparse(page_url).netloc
    if _host_is_trusted(host):
        score += 5
    if has_recipe_schema:
        score += 8
    if "recipe" in page_text:
        score += 2

    if name_tokens and name_overlap == 0 and ingredient_overlap == 0:
        return -50
    return score


def _source_page_image(meal: dict) -> str:
    name = str(meal.get("name") or "").strip()
    ingredients = _ingredients(meal, 3)
    low = f"{name} {meal.get('description','')} {' '.join(map(str, meal.get('tags') or []))}".lower()

    queries: list[str] = []
    if "heart" in low and any(x in low for x in ("egg", "huevo")):
        queries.append('"heart shaped fried egg" recipe')
    if "romantic" in low:
        queries.append(f'"{name}" romantic recipe')
    queries.extend([
        f'"{name}" recipe',
        f"{name} {' '.join(ingredients[:2])} recipe",
        f"{' '.join(ingredients[:3])} recipe",
    ])

    best: tuple[int, str] = (-999, "")
    seen_pages: set[str] = set()
    for query in queries:
        for page in _search_result_pages(query):
            if page in seen_pages:
                continue
            seen_pages.add(page)
            candidates, title, description, body_preview, has_recipe_schema = _page_metadata(page)
            if not candidates:
                continue
            score = _page_relevance_score(meal, page, title, description, body_preview, has_recipe_schema)
            if score < 8:
                continue
            for candidate in candidates[:5]:
                if _valid_image_url(candidate):
                    if score > best[0]:
                        best = (score, candidate)
                    break

    return best[1] if best[0] >= 8 else ""


def _deterministic_food_fallback(meal: dict) -> str:
    """Reliable final fallback: always a food-related image instead of a blank card.

    Uses Unsplash's keyword endpoint only as a last resort. It is deliberately separated from
    cache trust: generated cards can display it, but old persisted fallback URLs are still
    considered replaceable on a future repair pass.
    """
    terms = [str(meal.get("name") or "").strip(), *_ingredients(meal, 2)]
    query = ",".join(re.sub(r"[^a-zA-Z0-9 ]+", " ", t).strip() for t in terms if t).strip(",")
    if not query:
        query = "meal,food"
    return f"https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=1200&q=82&sig={abs(hash(query)) % 100000}"


def resolve_meal_image(meal: dict, *, force: bool = False, gemini_client=None, gemini_model: str = "") -> str:
    # No Gemini is used for images. Keep legacy args only so older callers do not break.
    key = _cache_key(meal)
    cache = _load_cache()
    cached = str(cache.get(key) or "").strip()
    if not force and cached and _valid_image_url(cached):
        return cached

    chosen = _source_page_image(meal)
    if not chosen:
        chosen = _deterministic_food_fallback(meal)

    cache[key] = chosen
    _save_cache(cache)
    return chosen


def is_untrusted_generated_image(url: str) -> bool:
    value = (url or "").lower().strip()
    if not value:
        return True
    return any(host in value for host in ("source.unsplash.com", "placehold.co", "encrypted-tbn", "mm.bing.net"))
