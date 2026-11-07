import json
import math
import os
import re
from pathlib import Path

try:
    from google import genai
except Exception:
    genai = None

from ..catalog.intelligence import CLASSIFIER_VERSION, classify_product
from ..database import PantryItem, Product, ProductIntelligence, SessionLocal, UserEvent
from ..recommendations.engine import build_preference_profile
from ..ingredient_aliases import canonical_ingredient_terms, ingredient_product_match_type
from ..recipes.seed import MEALS

DATA_FILE = Path(os.getenv("BITEWISE_AI_MEALS_PATH") or Path(__file__).resolve().parents[2] / "data" / "ai_meals.json").expanduser().resolve()
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
FALLBACK_IMAGE = ""
FREE_GEMINI_MODEL = "gemini-3.1-flash-lite"


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "ai-meal"


def _sanitize_steps(value):
    steps = []
    if not isinstance(value, (list, tuple)):
        return steps
    for raw in value[:20]:
        if isinstance(raw, str):
            text, minutes = raw.strip(), None
        elif isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("step") or "").strip()
            try:
                minutes = int(raw.get("minutes")) if raw.get("minutes") is not None else None
                if minutes is not None and not 0 <= minutes <= 240:
                    minutes = None
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
    raw_ingredients = raw.get("ingredients")
    if not isinstance(raw_ingredients, (list, tuple)):
        return None
    unit_aliases = {
        "g": "g", "gram": "g", "grams": "g",
        "ml": "ml", "milliliter": "ml", "milliliters": "ml",
        "unit": "unit", "units": "unit", "piece": "unit", "pieces": "unit", "pc": "unit",
        "clove": "cloves", "cloves": "cloves",
    }
    for item in raw_ingredients[:40]:
        if isinstance(item, dict):
            ingredient = str(item.get("ingredient") or item.get("name") or "").strip().lower()
            quantity = item.get("quantity")
            raw_unit = item.get("unit") or "unit"
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            ingredient = str(item[0]).strip().lower()
            quantity = item[1]
            raw_unit = item[2] or "unit"
        else:
            continue
        if not ingredient:
            continue
        try:
            quantity = float(quantity)
        except (TypeError, ValueError, OverflowError):
            continue
        unit = unit_aliases.get(str(raw_unit).strip().lower())
        if not math.isfinite(quantity) or quantity <= 0 or unit is None:
            continue
        ingredients.append([ingredient[:100], quantity, unit])
    if not ingredients:
        return None

    try:
        raw_minutes = float(raw.get("time") or 30)
        minutes = max(5, min(240, int(raw_minutes))) if math.isfinite(raw_minutes) else 30
    except (TypeError, ValueError, OverflowError):
        minutes = 30
    try:
        raw_cost = float(raw.get("cost") or 3.5)
        cost = max(.5, min(50, raw_cost)) if math.isfinite(raw_cost) else 3.5
    except (TypeError, ValueError, OverflowError):
        cost = 3.5
    try:
        raw_calories = float(raw.get("calories") or 500)
        calories = max(50, min(1800, int(raw_calories))) if math.isfinite(raw_calories) else 500
    except (TypeError, ValueError, OverflowError):
        calories = 500

    meal_type = str(raw.get("meal_type") or "dinner").strip().lower()
    if meal_type not in {"breakfast", "lunch", "dinner", "dessert", "snack"}:
        meal_type = "dinner"
    raw_tags = raw.get("tags")
    tags = [str(tag)[:40] for tag in raw_tags[:8] if str(tag).strip()] if isinstance(raw_tags, (list, tuple)) else ["AI Generated"]
    meal_id = _slug(str(raw.get("id") or name))
    meal_id = meal_id if meal_id.startswith("ai-") else f"ai-{meal_id}"
    return {
        "id": meal_id[:80],
        "name": name[:120],
        "description": str(raw.get("description") or "AI-generated meal idea.")[:280],
        "time": minutes,
        "difficulty": str(raw.get("difficulty") or "Easy")[:30],
        "cost": round(cost, 2),
        "cost_basis": "ai_estimate_per_serving",
        "calories": calories,
        "nutrition_basis": "ai_estimate_unverified",
        "meal_type": meal_type,
        "cuisine": str(raw.get("cuisine") or "International")[:60],
        "tags": tags,
        "ingredients": ingredients[:20],
        "steps": _sanitize_steps(raw.get("steps")),
        "image": str(raw.get("image") or FALLBACK_IMAGE),
        "source": "gemini",
    }


def _load_persisted() -> None:
    if not DATA_FILE.exists(): return
    try: stored = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception: return
    existing = {meal.get("id") for meal in MEALS}
    for index, raw in enumerate(stored if isinstance(stored, list) else []):
        meal = _sanitize_meal(raw, index)
        if meal and meal["id"] not in existing: MEALS.append(meal); existing.add(meal["id"])


def _persist_generated(generated: list[dict]) -> list[dict]:
    clean = []; existing = {meal.get("id") for meal in MEALS}
    for index, raw in enumerate(generated):
        meal = _sanitize_meal(raw, index)
        if not meal: continue
        base = meal["id"]; suffix = 2
        while meal["id"] in existing:
            old = next((m for m in MEALS if m.get("id") == meal["id"]), None)
            if old and old.get("name", "").lower() == meal["name"].lower(): meal = None; break
            meal["id"] = f"{base}-{suffix}"[:80]; suffix += 1
        if not meal: continue
        MEALS.append(meal); existing.add(meal["id"]); clean.append(meal)
    DATA_FILE.write_text(json.dumps([meal for meal in MEALS if meal.get("source") == "gemini"], ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


def _shopping_context():
    """Build a compact, real catalog context without sending the SKU database to Gemini."""
    db = SessionLocal()
    try:
        pantry = [
            f"{p.ingredient} ({p.quantity:g} {p.unit})"
            for p in db.query(PantryItem).filter(PantryItem.quantity > 0).limit(40).all()
        ]
        # Scan the local catalog, but retain only a few representative products per
        # culinary role. The full SKU set never leaves the database.
        query = (
            db.query(Product, ProductIntelligence)
            .outerjoin(ProductIntelligence, ProductIntelligence.product_id == Product.id)
            .filter(
                Product.supermarket == "REWE",
                Product.price.isnot(None),
                Product.price > 0,
                Product.availability.notin_(("unavailable", "out_of_stock", "not_available", "discontinued")),
            )
            .order_by(Product.id.asc())
            .yield_per(500)
        )
        grouped = {}
        excluded = ("toiletten", "kalklöser", "urinstein", "slipeinlagen", "kreide",
                    "hundefutter", "katzenfutter", "tierbedarf", "wc aktiv")
        for product, intelligence in query:
            title = (product.name_original or product.name_normalized or "").strip()
            if not title or any(term in title.lower() for term in excluded):
                continue
            profile = (
                intelligence
                if intelligence and intelligence.classifier_version == CLASSIFIER_VERSION
                else classify_product({
                    "name_original": product.name_original,
                    "name_normalized": product.name_normalized,
                    "translated_name": product.translated_name,
                    "brand": product.brand,
                    "category": product.category,
                })
            )
            if (profile.product_type in {"non_food", "beverage", "snack"}
                    or profile.culinary_role in {"soup", "salad", "dessert"}):
                continue
            canonical_terms = canonical_ingredient_terms(title)
            if not profile.is_complete_meal:
                if not canonical_terms:
                    continue
                if not any(
                    ingredient_product_match_type(term, title, product.category)
                    for term in canonical_terms
                ):
                    continue
            role = profile.culinary_role
            if role not in {"protein", "dairy", "vegetable", "starch", "sauce",
                            "complete_meal", "ingredient"}:
                continue
            if role not in grouped:
                grouped[role] = []
            if len(grouped[role]) >= 4:
                continue
            pack = ""
            if product.package_size and product.package_unit:
                pack = f" ({product.package_size:g} {product.package_unit})"
            grouped[role].append(title + pack)
        catalog = [f"{role}: " + "; ".join(items) for role, items in grouped.items() if items]
        catalog = catalog[:9]

        events = db.query(UserEvent).all()
        preferences = build_preference_profile(events, MEALS)
        favorite_cuisines = sorted(
            ((key, value) for key, value in preferences["cuisines"].items() if value > 0),
            key=lambda item: item[1], reverse=True
        )[:3]
        favorite_tags = sorted(
            ((key, value) for key, value in preferences["tags"].items() if value > 0),
            key=lambda item: item[1], reverse=True
        )[:5]
        preference_context = []
        if favorite_cuisines:
            preference_context.append("Positive cuisine signals: " + ", ".join(k for k, _ in favorite_cuisines))
        if favorite_tags:
            preference_context.append("Positive food/style signals: " + ", ".join(k for k, _ in favorite_tags))
        return pantry, catalog, preference_context
    finally:
        db.close()


def _parse_json_array(text: str):
    raw = (text or "").strip()
    if not raw: raise ValueError("Gemini returned an empty text response")
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I); raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list): return parsed
    except Exception: pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "[": continue
        try: parsed, _ = decoder.raw_decode(raw[index:])
        except Exception: continue
        if isinstance(parsed, list): return parsed
    raise ValueError(f"Gemini response did not contain a valid JSON array. Preview: {raw[:240]}")


_load_persisted()


class GeminiService:
    def __init__(self):
        self.key = os.getenv("GEMINI_API_KEY")
        # Hard-locked to the currently free-tier text/multimodal model so an old local .env
        # cannot accidentally switch Bitewise back to a paid model.
        self.model = FREE_GEMINI_MODEL
        self.client = genai.Client(api_key=self.key) if self.key and genai else None

    def _generate_once(self, instruction: str):
        return self.client.models.generate_content(model=self.model, contents=instruction), self.model

    def generate_meals(self, prompt):
        if not self.key: raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if genai is None: raise RuntimeError("google-genai is not installed in the backend environment")
        if not self.client: raise RuntimeError("Gemini client could not be initialized")
        pantry, catalog, preference_context = _shopping_context()
        instruction = f"""
You are Bitewise, a food decision engine for a person in Berlin who wants attractive food with minimum cooking effort.
Return ONLY a valid JSON array of 8 distinct meal ideas. Be concise to minimize free-tier token use.
User request: {prompt}
PANTRY: {', '.join(pantry) if pantry else 'none confirmed'}
REAL REWE CATALOG EXAMPLES BY CULINARY ROLE (not a complete inventory; stock is not confirmed): {' | '.join(catalog) if catalog else 'catalog unavailable'}\nLEARNED USER PREFERENCES: {'; '.join(preference_context) if preference_context else 'not enough feedback yet'}
Rules:
- Respect cuisine, meal type, cheap/quick/fancy/healthy/high-protein constraints literally.
- Your primary job is creative culinary ideation: invent attractive, varied meal concepts that answer the request. The catalog informs feasibility but must never limit you to only listed products.
- Prefer pantry ingredients first when the user asks to use them. Otherwise use actual REWE examples when they genuinely fit; never force irrelevant products.
- Catalog examples are listings, not proof of live stock. Never claim availability.
- Optimize for taste, convenience, effort, cleanup and the user's learned preferences.
- Each object: id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps,image.
- meal_type is breakfast/lunch/dinner/dessert/snack.
- ingredients: [normalized_english_ingredient, quantity, unit] using g/ml/unit/cloves.
- steps: 3-7 short objects like {{"text":"Boil pasta","minutes":10}}.
- image MUST be an empty string. Bitewise resolves images separately with zero Gemini calls.
- Make meals visually appealing and meaningfully different.
""".strip()
        response, used_model = self._generate_once(instruction)
        generated = _parse_json_array(response.text or ""); clean = _persist_generated(generated)
        if not clean: raise RuntimeError("Gemini returned meals, but none passed Bitewise validation.")
        for meal in clean: meal["generation_model"] = used_model
        return clean
