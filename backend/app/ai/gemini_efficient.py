import json
import math
import re
import time

from .gemini import (
    DATA_FILE,
    MEALS,
    GeminiService as BaseGeminiService,
    _parse_json_array,
    _persist_generated,
)
from ..database import PantryItem, SessionLocal
from ..ingredient_intelligence import normalize_recipe_intelligence


_ALLOWED_APPLIANCES = ("air fryer", "microwave", "stovetop", "oven")
_DEFAULT_APPLIANCES = ("air fryer", "microwave", "stovetop")


def cooking_preferences_instruction(appliances=None) -> str:
    """Build deterministic, testable cooking-method guidance in user priority order."""
    supplied = appliances if isinstance(appliances, (list, tuple)) else []
    selected = []
    for value in supplied:
        name = str(value or "").strip().lower()
        if name in _ALLOWED_APPLIANCES and name not in selected:
            selected.append(name)
    if not selected:
        selected = list(_DEFAULT_APPLIANCES)
    priorities = ", ".join(f"{index + 1}. {name}" for index, name in enumerate(selected))
    return f"""KITCHEN EQUIPMENT — USER PRIORITY ORDER:
{priorities}
- Prefer the first suitable selected appliance; use later options as fallbacks.
- Optimize for very little hands-on work, very few steps and minimal washing-up. Aim for no more than 10 minutes of active preparation and one main appliance/container whenever practical.
- Prefer air-fryer and microwave combinations when selected. Use the microwave for suitable tasks such as steaming vegetables, heating or cooking suitable grains/potatoes in a microwave-safe container; use the air fryer for crisping and cooking suitable proteins/vegetables.
- Use a pan/stovetop or oven only when it makes the dish substantially easier, safer or better. Do not add a pan just out of habit.
- Consider affordable supermarket frozen, pre-cut or ready-to-cook ingredients when they genuinely save work and are likely to be good value. Do not assume convenience products are always cheaper; avoid expensive premium convenience foods and do not invent prices or specific stock.
- Keep recipes simple, affordable and realistic for an ordinary German supermarket shop.
- Give practical appliance-specific steps with realistic temperatures, wattage where useful and cooking times. Never recommend microwaving raw poultry or other unsafe shortcuts; follow safe cooking and package instructions.""".strip()

_REPAIR_DONE = False


def repair_persisted_ai_images(gemini_client=None, gemini_model: str = "") -> int:
    """Startup image repair stays disabled so discovery never blocks."""
    return 0


def _pantry_context() -> list[str]:
    """Fetch only pantry hints; catalog matching belongs to the local optimizer."""
    db = SessionLocal()
    try:
        return [
            f"{row.ingredient} ({row.quantity:g} {row.unit})"
            for row in db.query(PantryItem).filter(PantryItem.quantity > 0).limit(40).all()
        ]
    finally:
        db.close()


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "meal"


def _safe_number(value, default, minimum, maximum, integer=False):
    try:
        number = float(value)
        if not math.isfinite(number):
            return default
        number = max(minimum, min(maximum, number))
        return int(number) if integer else number
    except (TypeError, ValueError, OverflowError):
        return default


def _clean_image_url(value: str) -> str:
    value = str(value or "").strip()
    return value if value.startswith("https://") else ""


def _base_user_request(prompt: str) -> str:
    """Strip frontend implementation hints so Gemini ranks the actual human request first."""
    text = str(prompt or "").strip()
    for marker in (
        ". Meal type:",
        ". Available appliances:",
        ". User portion factor",
        ". Prefer the easiest method",
    ):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    return text or str(prompt or "").strip()


class GeminiService(BaseGeminiService):
    """One free-tier Gemini call returns browseable, mainstream meal concepts."""

    def __init__(self):
        global _REPAIR_DONE
        super().__init__()
        _REPAIR_DONE = True

    def generate_meals(self, prompt):
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if not self.client:
            raise RuntimeError("Gemini client could not be initialized")

        user_request = _base_user_request(prompt)
        pantry = _pantry_context()
        pantry_context = ", ".join(pantry[:8]) if pantry else "none"

        instruction = f"""You are Bitewise's visual discovery editor. Think like a strong Pinterest board curator, not a novelty recipe generator.

PRIMARY USER SEARCH (this controls the result set):
{user_request}

SECONDARY CONTEXT ONLY — never let this override the search:
Pantry hints: {pantry_context}

AVAILABILITY RULE:
- Choose familiar ingredients normally sold by mainstream German supermarkets such as REWE.
- Do not name brands, SKUs, exact package sizes, or invent product availability/prices.
- Use generic ingredient names; Bitewise will match them to its live REWE catalog after selection.

Return ONLY a compact JSON array of 10 meal concepts. Each object needs exactly:
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,image

QUALITY RULES:
- First ask: what would a normal person expect to see after searching this exact phrase on Pinterest or Google Images?
- Return recognizable, appetizing, mainstream dishes that strongly match that expectation.
- Do NOT invent quirky fusion dishes, vague concepts, novelty pantry combinations, or restaurant-menu wording.
- Use familiar food names. Prefer concepts people can instantly picture.
- The full search intent is mandatory. If the search says romantic + breakfast + simple, EVERY result must visibly satisfy all three.
- For occasion/aesthetic searches, encode the aesthetic in the FOOD itself: heart-shaped toast or pancakes, strawberries/berries, croissants, waffles, eggs on toast, yogurt parfait, breakfast board/tray, fruit, cocoa/coffee. Do not just add words like elegant, cozy, sunrise, indulgent to an unrelated dish.
- Avoid beverages as standalone meal cards unless the user explicitly asks for drinks.
- Avoid pasta, salads, savory lunch/dinner dishes, or odd pantry hacks for a breakfast search unless explicitly requested.
- Keep descriptions concrete and under 12 words.
- time is realistic total minutes; cost is rough EUR per serving.
- meal_type: breakfast|lunch|dinner|dessert|snack.
- tags: max 4 useful strings.
- image: direct HTTPS food photo URL only if you are highly confident it is real and matches; otherwise empty string.
- No ingredients, steps, methods, or recipe text.
- Make results distinct but all clearly relevant. Rank the most obvious/best matches first.

Example quality bar for search "simple romantic breakfast":
heart-shaped French toast with strawberries; strawberry ricotta toast; croissants with berries and chocolate; heart-shaped fried eggs on toast; berry yogurt parfait for two; mini pancakes with strawberries; waffles with raspberries; breakfast board with croissants, fruit and jam; cinnamon rolls with berries; avocado toast with heart-shaped egg.
These are examples of specificity and relevance, not a fixed list.
""".strip()

        response, used_model = self._generate_once(instruction)
        generated = _parse_json_array(response.text or "")
        concepts = []
        seen_names = set()
        for index, raw in enumerate(generated[:10]):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            normalized_name = name.lower()
            if not name or normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            concept_id = f"concept-{_slug(str(raw.get('id') or name))}-{index+1}"
            raw_tags = raw.get("tags")
            tags = [
                str(tag).strip()[:40]
                for tag in raw_tags[:4]
                if str(tag).strip()
            ] if isinstance(raw_tags, (list, tuple)) else []
            meal_type = str(raw.get("meal_type") or "dinner").strip().lower()
            if meal_type not in {"breakfast", "lunch", "dinner", "dessert", "snack"}:
                meal_type = "dinner"
            concepts.append({
                "id": concept_id[:100],
                "name": name[:120],
                "description": str(raw.get("description") or "")[:180],
                "time": _safe_number(raw.get("time"), 20, 5, 240, integer=True),
                "difficulty": str(raw.get("difficulty") or "Easy")[:30],
                "cost": round(_safe_number(raw.get("cost"), 3.5, 0.5, 50), 2),
                "calories": _safe_number(raw.get("calories"), 400, 50, 1800, integer=True),
                "meal_type": meal_type,
                "cuisine": str(raw.get("cuisine") or "International")[:60],
                "tags": tags,
                "image": _clean_image_url(raw.get("image")),
                "ingredients": [],
                "steps": [],
                "is_concept": True,
                "generation_model": used_model,
                "discovery_prompt": user_request[:700],
            })
        if not concepts:
            raise RuntimeError("Gemini returned no usable meal concepts.")
        return concepts

    def _generate_once(self, instruction: str):
        """Retry transient Gemini capacity/rate-limit failures without changing the prompt."""
        retryable_codes = {429, 500, 502, 503, 504}
        for attempt in range(3):
            try:
                return super()._generate_once(instruction)
            except Exception as exc:
                raw_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                try:
                    code = int(raw_code)
                except (TypeError, ValueError):
                    code = None
                message = str(exc).lower()
                transient_message = any(token in message for token in (
                    "429", "500", "502", "503", "504", "unavailable",
                    "resource_exhausted", "resource exhausted", "too many requests",
                    "rate limit", "high demand", "overloaded",
                ))
                if attempt == 2 or (code not in retryable_codes and not transient_message):
                    raise
                # Short bounded backoff: 1s, then 2s. Never retry validation/auth errors.
                time.sleep(2 ** attempt)

    def expand_concept(self, concept: dict, context: str = "", appliances=None):
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if not self.client:
            raise RuntimeError("Gemini client could not be initialized")

        pantry = _pantry_context()
        name = str(concept.get("name") or "").strip()
        if not name:
            raise ValueError("Concept name is required")
        description = str(concept.get("description") or "").strip()
        meal_type = str(concept.get("meal_type") or "dinner")
        image = _clean_image_url(concept.get("image"))

        instruction = f"""Create ONE complete Bitewise recipe for the selected meal concept.

SELECTED CONCEPT: {name}
CONCEPT DESCRIPTION: {description}
MEAL TYPE: {meal_type}
ORIGINAL DISCOVERY CONTEXT: {context or concept.get('discovery_prompt') or 'none'}
{cooking_preferences_instruction(appliances)}
PANTRY: {', '.join(pantry[:30]) if pantry else 'none'}
SUPERMARKET AVAILABILITY: Use ordinary ingredients commonly sold by German supermarkets such as REWE. Do not specify brands, SKUs, package sizes, or prices; Bitewise will match the ingredients to its current catalog after generation.

Return ONLY a JSON array containing exactly one object with:
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps,image,ingredient_intelligence

Rules:
- Keep the selected concept recognizable; do not replace it with another dish.
- ingredients: [[english_name,quantity,unit]], units only g|ml|unit|cloves|tsp|tbsp. Choose physically sensible units (oil must never use cloves; spices use g or tsp; countable produce may use unit/cloves).
- ingredient_intelligence: an object keyed by the exact english_name in ingredients. For EVERY ingredient include canonical, name_en, name_de, name_es, aliases (up to 8 useful German/English retail names), form (fresh|frozen|canned|dried|grated|pre_cooked|whole|liquid|powder|soft|hard|unspecified), culinary_role, unit_dimension (mass|volume|count), allowed_substitutions (up to 3 genuinely usable options; empty if none), preparation. Keep translations concise and realistic for German supermarkets. Preserve requested forms: frozen is not fresh; grated is not block; canned is not frozen.
- Every ingredient quantity MUST represent exactly 2 servings. Bitewise scales quantities after generation.
- steps: 3-6 concise objects {{"text":"...","minutes":N}}.
- Optimize for low effort and minimal cleanup, following the selected kitchen-equipment priority above.
- Prefer affordable frozen or pre-cut ingredients when they reduce preparation without making the meal unnecessarily expensive.
- Use generic, unambiguous ingredient names (e.g. "chicken breast", "Greek yogurt", "cherry tomatoes").
- Prefer ingredients commonly available at REWE, but never claim a specific product or price is available.
- image must be exactly this existing URL if non-empty: {image}
""".strip()

        response, used_model = self._generate_once(instruction)
        generated = _parse_json_array(response.text or "")
        if not generated:
            raise RuntimeError("Gemini returned no recipe for the selected concept.")
        raw = generated[0]
        raw["image"] = image or _clean_image_url(raw.get("image"))
        clean = _persist_generated([raw])
        if not clean:
            existing = next((m for m in MEALS if str(m.get("name", "")).lower() == name.lower()), None)
            if existing:
                return existing
            raise RuntimeError("Generated recipe did not pass Bitewise validation.")
        clean[0]["ingredient_intelligence"] = normalize_recipe_intelligence({
            "ingredients": clean[0].get("ingredients", []),
            "ingredient_intelligence": raw.get("ingredient_intelligence"),
        })
        clean[0]["generation_model"] = used_model
        clean[0]["expanded_from_concept"] = str(concept.get("id") or "")
        return clean[0]
