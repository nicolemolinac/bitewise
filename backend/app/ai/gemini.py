import json
import os
import re
import time
from pathlib import Path

try:
    from google import genai
except Exception:
    genai = None

from ..database import PantryItem, Product, SessionLocal
from ..recipes.seed import MEALS

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "ai_meals.json"
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
FALLBACK_IMAGE = "https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=1200&q=85"


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "ai-meal"


def _sanitize_steps(value):
    steps = []
    for raw in value or []:
        if isinstance(raw, str):
            text = raw.strip()
            minutes = None
        elif isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("step") or "").strip()
            try:
                minutes = int(raw.get("minutes")) if raw.get("minutes") is not None else None
            except Exception:
                minutes = None
        else:
            continue
        if text:
            steps.append({"text": text[:240], "minutes": minutes})
    return steps[:10]


def _sanitize_meal(raw: dict, index: int = 0) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    ingredients = []
    for item in raw.get("ingredients") or []:
        if isinstance(item, dict):
            ingredient = str(item.get("ingredient") or item.get("name") or "").strip().lower()
            quantity = item.get("quantity")
            unit = str(item.get("unit") or "unit").strip().lower() or "unit"
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            ingredient = str(item[0]).strip().lower()
            quantity = item[1]
            unit = str(item[2] or "unit").strip().lower() or "unit"
        else:
            continue
        if not ingredient:
            continue
        try:
            quantity = float(quantity)
        except Exception:
            continue
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
    try:
        calories = max(50, min(1800, int(float(raw.get("calories") or 500))))
    except Exception:
        calories = 500
    meal_type = str(raw.get("meal_type") or "dinner").strip().lower()
    if meal_type not in {"breakfast", "lunch", "dinner", "dessert", "snack"}:
        meal_type = "dinner"
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
        "calories": calories,
        "meal_type": meal_type,
        "cuisine": str(raw.get("cuisine") or "International")[:60],
        "tags": [str(tag)[:40] for tag in (raw.get("tags") or ["AI Generated"])][:8],
        "ingredients": ingredients[:20],
        "steps": _sanitize_steps(raw.get("steps")),
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


def _shopping_context():
    db = SessionLocal()
    try:
        pantry = [f"{p.ingredient} ({p.quantity:g} {p.unit})" for p in db.query(PantryItem).filter(PantryItem.quantity > 0).limit(60).all()]
        products = (
            db.query(Product)
            .filter(Product.price.isnot(None))
            .order_by(Product.price.asc())
            .limit(180)
            .all()
        )
        catalog = []
        seen = set()
        for p in products:
            key = (p.ingredient or p.name_normalized or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            label = p.name_original or p.ingredient
            catalog.append(f"{label} €{p.price:.2f}")
            if len(catalog) >= 100:
                break
        return pantry, catalog
    finally:
        db.close()


def _parse_json_array(text: str):
    """Parse the first valid JSON array from Gemini text, tolerating fences/explanatory text."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Gemini returned an empty text response")
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "[":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw[index:])
        except Exception:
            continue
        if isinstance(parsed, list):
            return parsed
    raise ValueError(f"Gemini response did not contain a valid JSON array. Preview: {raw[:240]}")


def _retryable_gemini_error(exc: Exception) -> bool:
    """Only retry transient capacity/rate-limit failures, never bad prompts/keys/model IDs."""
    code = getattr(exc, "code", None)
    status_code = getattr(exc, "status_code", None)
    text = str(exc).lower()
    return (
        code in {429, 500, 503, 504}
        or status_code in {429, 500, 503, 504}
        or "unavailable" in text
        or "high demand" in text
        or "resource_exhausted" in text
        or "too many requests" in text
    )


_load_persisted()


class GeminiService:
    def __init__(self):
        self.key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
        configured_fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.6-flash")
        self.models = []
        for model in [self.model, *configured_fallbacks.split(",")]:
            model = model.strip()
            if model and model not in self.models:
                self.models.append(model)
        self.client = genai.Client(api_key=self.key) if self.key and genai else None

    def _generate_with_resilience(self, instruction: str):
        attempts_per_model = max(1, min(4, int(os.getenv("GEMINI_RETRIES_PER_MODEL", "2") or 2)))
        last_error = None
        for model_index, model in enumerate(self.models):
            for attempt in range(attempts_per_model):
                try:
                    return self.client.models.generate_content(model=model, contents=instruction), model
                except Exception as exc:
                    last_error = exc
                    if not _retryable_gemini_error(exc):
                        raise
                    final_attempt_for_model = attempt == attempts_per_model - 1
                    if not final_attempt_for_model:
                        time.sleep(min(4.0, 1.0 * (2 ** attempt)))
            # A transiently overloaded model should not block Bitewise: immediately
            # continue to the next stable Flash model after its short retry window.
            if model_index < len(self.models) - 1:
                continue
        raise RuntimeError(
            f"All Gemini models are temporarily unavailable after retries. Last error: {str(last_error)[:240]}"
        )

    def generate_meals(self, prompt):
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if genai is None:
            raise RuntimeError("google-genai is not installed in the backend environment")
        if not self.client:
            raise RuntimeError("Gemini client could not be initialized")

        pantry, catalog = _shopping_context()
        instruction = f"""
You are Bitewise, a premium food decision engine for a person in Berlin who wants attractive food with minimum cooking effort.
Return ONLY a valid JSON array of 8 distinct meal ideas.

User request: {prompt}

PANTRY AVAILABLE NOW:
{', '.join(pantry) if pantry else 'No confirmed pantry items.'}

LOW-PRICE / AVAILABLE REWE CATALOG EXAMPLES:
{'; '.join(catalog) if catalog else 'Catalog unavailable; use normal German-supermarket ingredients.'}

Rules:
- Respect the request literally: cuisine, meal type, cheap/quick/fancy/healthy/high-protein constraints must actually match.
- Prefer ingredients that appear in pantry or REWE context when sensible; never create bizarre combinations just to use them.
- Optimize for low effort and few dishes. If the request names appliances (air fryer, oven, microwave, stovetop), choose the easiest suitable method.
- Include breakfast/lunch/dinner/dessert/snack only when appropriate to the request.
- Each meal object MUST contain: id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps,image.
- meal_type is exactly one of breakfast,lunch,dinner,dessert,snack.
- calories is a realistic approximate kcal per serving.
- ingredients is an array of [normalized_english_ingredient, quantity, unit] using g, ml, unit or cloves.
- steps is 3-7 very short objects like {{"text":"Boil pasta in salted water","minutes":10}}. Make instructions idiot-proof, concrete, and concise.
- cost is estimated EUR per serving.
- image must be a plausible public HTTPS food-image URL when known; otherwise use an empty string.
- Make meals visually appealing and meaningfully different from each other.
""".strip()

        response, used_model = self._generate_with_resilience(instruction)
        generated = _parse_json_array(response.text or "")
        clean = _persist_generated(generated)
        if not clean:
            raise RuntimeError("Gemini returned meals, but none passed Bitewise validation. Check the backend log for the response shape.")
        for meal in clean:
            meal["generation_model"] = used_model
        return clean
