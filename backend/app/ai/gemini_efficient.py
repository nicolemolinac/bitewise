import json
import re

from .gemini import (
    DATA_FILE,
    MEALS,
    GeminiService as BaseGeminiService,
    _parse_json_array,
    _persist_generated,
)
from ..database import PantryItem, SessionLocal


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
            concepts.append({
                "id": concept_id[:100],
                "name": name[:120],
                "description": str(raw.get("description") or "")[:180],
                "time": int(raw.get("time") or 20),
                "difficulty": str(raw.get("difficulty") or "Easy")[:30],
                "cost": float(raw.get("cost") or 3.5),
                "calories": int(raw.get("calories") or 400),
                "meal_type": str(raw.get("meal_type") or "dinner").lower(),
                "cuisine": str(raw.get("cuisine") or "International")[:60],
                "tags": [str(x)[:40] for x in (raw.get("tags") or [])][:4],
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

    def expand_concept(self, concept: dict, context: str = "", appliances=None):
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if not self.client:
            raise RuntimeError("Gemini client could not be initialized")

        pantry, _ = _shopping_context()
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
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps,image

Rules:
- Keep the selected concept recognizable; do not replace it with another dish.
- ingredients: [[english_name,quantity,unit]], units only g|ml|unit|cloves.
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
        clean[0]["generation_model"] = used_model
        clean[0]["expanded_from_concept"] = str(concept.get("id") or "")
        return clean[0]
