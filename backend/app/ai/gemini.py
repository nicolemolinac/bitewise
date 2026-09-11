import json
import os
import re
from pathlib import Path

try:
    from google import genai
except Exception:
    genai = None

from ..recipes.seed import MEALS

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "ai_meals.json"
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
FALLBACK_IMAGE = "https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=1200&q=85"


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "ai-meal"


def _sanitize_meal(raw: dict, index: int = 0) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    ingredients = []
    for item in raw.get("ingredients") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        ingredient = str(item[0]).strip().lower()
        if not ingredient:
            continue
        try:
            quantity = float(item[1])
        except Exception:
            continue
        unit = str(item[2] or "unit").strip().lower() or "unit"
        ingredients.append([ingredient, quantity, unit])
    if not ingredients:
        return None
    try:
        minutes = max(5, min(240, int(float(raw.get("time") or 30))))
    except Exception:
        minutes = 30
    try:
        cost = max(0.5, min(50, float(raw.get("cost") or 3.5)))
    except Exception:
        cost = 3.5
    meal_id = _slug(str(raw.get("id") or name))
    if not meal_id.startswith("ai-"):
        meal_id = f"ai-{meal_id}"
    return {
        "id": meal_id[:80],
        "name": name[:120],
        "description": str(raw.get("description") or "AI-generated meal idea.")[:280],
        "time": minutes,
        "difficulty": str(raw.get("difficulty") or "Easy")[:30],
        "cost": round(cost, 2),
        "cuisine": str(raw.get("cuisine") or "International")[:60],
        "tags": [str(tag)[:40] for tag in (raw.get("tags") or ["AI Generated"])][:8],
        "ingredients": ingredients[:20],
        "image": str(raw.get("image") or FALLBACK_IMAGE),
        "source": "gemini",
    }


def _load_persisted() -> None:
    if not DATA_FILE.exists():
        return
    try:
        stored = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    existing = {meal.get("id") for meal in MEALS}
    for index, raw in enumerate(stored if isinstance(stored, list) else []):
        meal = _sanitize_meal(raw, index)
        if meal and meal["id"] not in existing:
            MEALS.append(meal)
            existing.add(meal["id"])


def _persist_generated(generated: list[dict]) -> list[dict]:
    clean = []
    existing = {meal.get("id") for meal in MEALS}
    for index, raw in enumerate(generated):
        meal = _sanitize_meal(raw, index)
        if not meal:
            continue
        base = meal["id"]
        suffix = 2
        while meal["id"] in existing:
            old = next((m for m in MEALS if m.get("id") == meal["id"]), None)
            if old and old.get("name", "").lower() == meal["name"].lower():
                meal = None
                break
            meal["id"] = f"{base}-{suffix}"[:80]
            suffix += 1
        if not meal:
            continue
        MEALS.append(meal)
        existing.add(meal["id"])
        clean.append(meal)
    persisted = [meal for meal in MEALS if meal.get("source") == "gemini"]
    DATA_FILE.write_text(json.dumps(persisted, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


_load_persisted()


class GeminiService:
    def __init__(self):
        self.key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.client = genai.Client(api_key=self.key) if self.key and genai else None

    def generate_meals(self, prompt):
        if not self.client:
            return None
        instruction = (
            "Return ONLY a valid JSON array of 6 distinct meals. "
            "Each meal must have id,name,description,time,difficulty,cost,cuisine,tags,ingredients,image. "
            "ingredients must be arrays [normalized_english_ingredient,quantity,unit] using g, ml, unit or cloves. "
            "cost is estimated EUR per serving. Prefer realistic supermarket ingredients and visual, varied meals. "
            f"User request: {prompt}"
        )
        try:
            response = self.client.models.generate_content(model=self.model, contents=instruction)
            raw = response.text.strip().removeprefix("```json").removesuffix("```").strip()
            generated = json.loads(raw)
            if not isinstance(generated, list):
                return None
            return _persist_generated(generated)
        except Exception:
            return None
