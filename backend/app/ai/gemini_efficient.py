import json
import re

from .gemini import (
    DATA_FILE,
    MEALS,
    GeminiService as BaseGeminiService,
    _parse_json_array,
    _persist_generated,
    _shopping_context,
)

_REPAIR_DONE = False


def repair_persisted_ai_images(gemini_client=None, gemini_model: str = "") -> int:
    """Image repair is intentionally disabled during startup.

    Meal discovery must stay instant and must never block on external image providers.
    Images are resolved lazily by the frontend/backend image endpoint after concepts render.
    """
    return 0


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value or "meal"


class GeminiService(BaseGeminiService):
    """Two-stage free-first flow: cheap concepts first, full recipe only after selection."""

    def __init__(self):
        global _REPAIR_DONE
        super().__init__()
        _REPAIR_DONE = True

    def generate_meals(self, prompt):
        """Generate lightweight discovery concepts only. Never wait for external image lookup."""
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if not self.client:
            raise RuntimeError("Gemini client could not be initialized")

        pantry, catalog = _shopping_context()
        pantry_context = ", ".join(pantry[:12]) if pantry else "none"
        catalog_context = "; ".join(catalog[:10]) if catalog else "none"
        instruction = f"""You are Bitewise, a visual meal discovery engine.
Create 12 distinct meal CONCEPTS for the user's exact request. This is browsing only: DO NOT generate a recipe, ingredient quantities, or cooking steps.

USER REQUEST — HIGHEST PRIORITY:
{prompt}

Pantry hints: {pantry_context}
Cheap REWE hints: {catalog_context}

Return ONLY a compact JSON array. Each object needs exactly:
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags

Rules:
- Occasion/aesthetic words are hard constraints.
- Keep description under 12 words.
- time is estimated total minutes; cost is estimated EUR per serving.
- meal_type: breakfast|lunch|dinner|dessert|snack.
- tags: max 4 short strings.
- No image URLs.
- No ingredients. No steps. No method. No recipe text.
- Make all 12 ideas meaningfully different.
""".strip()

        response, used_model = self._generate_once(instruction)
        generated = _parse_json_array(response.text or "")
        concepts = []
        seen = set()
        for index, raw in enumerate(generated[:12]):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            concept_id = f"concept-{_slug(str(raw.get('id') or name))}-{index+1}"
            if concept_id in seen:
                continue
            seen.add(concept_id)
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
                "image": "",
                "ingredients": [],
                "steps": [],
                "is_concept": True,
                "generation_model": used_model,
                "discovery_prompt": str(prompt)[:700],
            })
        if not concepts:
            raise RuntimeError("Gemini returned no usable meal concepts.")
        return concepts

    def expand_concept(self, concept: dict, context: str = ""):
        """Generate and persist one complete recipe only after the user selects a concept."""
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if not self.client:
            raise RuntimeError("Gemini client could not be initialized")

        pantry, catalog = _shopping_context()
        name = str(concept.get("name") or "").strip()
        if not name:
            raise ValueError("Concept name is required")
        description = str(concept.get("description") or "").strip()
        meal_type = str(concept.get("meal_type") or "dinner")

        instruction = f"""Create ONE complete Bitewise recipe for the meal concept the user selected.

SELECTED CONCEPT: {name}
CONCEPT DESCRIPTION: {description}
MEAL TYPE: {meal_type}
ORIGINAL DISCOVERY CONTEXT: {context or concept.get('discovery_prompt') or 'none'}
PANTRY: {', '.join(pantry[:30]) if pantry else 'none'}
CHEAP REWE EXAMPLES: {'; '.join(catalog[:25]) if catalog else 'none'}

Return ONLY a JSON array containing exactly one object with:
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps

Rules:
- Keep the selected concept recognizable; do not replace it with another dish.
- ingredients: [[english_name,quantity,unit]], units only g|ml|unit|cloves.
- steps: 3-6 concise objects {{"text":"...","minutes":N}}.
- Optimize for low effort and minimal cleanup.
- Do not return an image URL.
""".strip()

        response, used_model = self._generate_once(instruction)
        generated = _parse_json_array(response.text or "")
        if not generated:
            raise RuntimeError("Gemini returned no recipe for the selected concept.")
        raw = generated[0]
        raw["image"] = ""
        clean = _persist_generated([raw])
        if not clean:
            existing = next((m for m in MEALS if str(m.get("name", "")).lower() == name.lower()), None)
            if existing:
                return existing
            raise RuntimeError("Generated recipe did not pass Bitewise validation.")
        clean[0]["generation_model"] = used_model
        clean[0]["expanded_from_concept"] = str(concept.get("id") or "")
        return clean[0]
