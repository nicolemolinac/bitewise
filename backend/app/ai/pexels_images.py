import os
from typing import Any

import requests

PEXELS_ENDPOINT = "https://api.pexels.com/v1/search"


def _query(meal: dict[str, Any]) -> str:
    name = str(meal.get("name") or "").strip()
    tags = " ".join(str(x) for x in (meal.get("tags") or [])[:3])
    meal_type = str(meal.get("meal_type") or "").strip()
    parts = [name, tags, meal_type, "food"]
    return " ".join(x for x in parts if x).strip()


def search_pexels_image(meal: dict[str, Any]) -> dict[str, str]:
    """Return one representative Pexels photo for a meal, or empty fields.

    Uses only the free Pexels search API. No retries, no paid fallback.
    """
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return {"image": "", "image_page": "", "photographer": ""}

    query = _query(meal)
    if not query:
        return {"image": "", "image_page": "", "photographer": ""}

    try:
        r = requests.get(
            PEXELS_ENDPOINT,
            headers={"Authorization": key},
            params={"query": query, "per_page": 5, "orientation": "landscape", "locale": "en-US"},
            timeout=8,
        )
        r.raise_for_status()
        photos = r.json().get("photos") or []
    except Exception:
        return {"image": "", "image_page": "", "photographer": ""}

    for photo in photos:
        src = photo.get("src") or {}
        image = str(src.get("large") or src.get("medium") or src.get("original") or "").strip()
        if not image.startswith("https://"):
            continue
        return {
            "image": image,
            "image_page": str(photo.get("url") or ""),
            "photographer": str(photo.get("photographer") or ""),
        }
    return {"image": "", "image_page": "", "photographer": ""}
