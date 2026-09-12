import json

from .gemini import (
    DATA_FILE,
    MEALS,
    GeminiService as BaseGeminiService,
    _parse_json_array,
    _persist_generated,
    _shopping_context,
)
from .image_resolver import is_untrusted_generated_image, resolve_meal_image


def repair_persisted_ai_images() -> int:
    """Replace old unverified Gemini/Unsplash images without regenerating recipes."""
    if not DATA_FILE.exists():
        return 0
    try:
        stored = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(stored, list):
        return 0

    changed = 0
    by_id = {}
    for raw in stored:
        if not isinstance(raw, dict):
            continue
        meal_id = str(raw.get("id") or "")
        if is_untrusted_generated_image(str(raw.get("image") or "")):
            raw["image"] = resolve_meal_image(raw)
            changed += 1
        if meal_id:
            by_id[meal_id] = raw

    if changed:
        DATA_FILE.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        # The legacy loader has already copied persisted recipes into the in-memory catalog.
        # Keep those objects aligned so the fix is visible immediately after backend restart.
        for meal in MEALS:
            if meal.get("source") != "gemini":
                continue
            raw = by_id.get(str(meal.get("id") or ""))
            if raw:
                meal["image"] = raw.get("image")
    return changed


class GeminiService(BaseGeminiService):
    """Token-lean meal generation with image search handled outside the LLM."""

    def generate_meals(self, prompt):
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if not self.client:
            raise RuntimeError("Gemini client could not be initialized")

        pantry, catalog = _shopping_context()
        # Keep model context deliberately small. Images are resolved separately for zero LLM tokens.
        pantry_context = ", ".join(pantry[:30]) if pantry else "none"
        catalog_context = "; ".join(catalog[:25]) if catalog else "none"
        instruction = f"""You are Bitewise. Create 8 distinct, attractive, low-effort meal ideas for this request:
{prompt}

Pantry: {pantry_context}
Cheap REWE examples: {catalog_context}

Return ONLY a compact JSON array. Each object needs exactly:
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps
Rules:
- meal_type: breakfast|lunch|dinner|dessert|snack
- ingredients: [[english_name,quantity,unit]], units only g|ml|unit|cloves
- steps: 3-6 concise objects {{"text":"...","minutes":N}}
- Respect the request literally; prefer pantry/REWE items when sensible.
- Keep descriptions and tags short.
- DO NOT return image URLs, image prompts, or image descriptions. Bitewise resolves photos separately.
""".strip()

        response, used_model = self._generate_with_resilience(instruction)
        generated = _parse_json_array(response.text or "")

        # Resolve real photos outside Gemini: no extra model tokens and permanently cached.
        for raw in generated:
            if isinstance(raw, dict):
                raw["image"] = resolve_meal_image(raw)

        clean = _persist_generated(generated)
        if not clean:
            raise RuntimeError("Gemini returned meals, but none passed Bitewise validation.")
        for meal in clean:
            meal["generation_model"] = used_model
        return clean


# Repair old AI recipes once at backend import/restart. The image resolver caches results,
# so subsequent restarts do not repeat successful searches.
repair_persisted_ai_images()
