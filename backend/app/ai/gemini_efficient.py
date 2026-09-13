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

_REPAIR_DONE = False


def repair_persisted_ai_images(gemini_client=None, gemini_model: str = "") -> int:
    """Repair old missing/untrusted meal images with zero Gemini calls."""
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
            resolved = resolve_meal_image(raw)
            if resolved and resolved != raw.get("image"):
                raw["image"] = resolved
                changed += 1
        if meal_id:
            by_id[meal_id] = raw

    if changed:
        DATA_FILE.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        for meal in MEALS:
            if meal.get("source") != "gemini":
                continue
            raw = by_id.get(str(meal.get("id") or ""))
            if raw:
                meal["image"] = raw.get("image")
    return changed


class GeminiService(BaseGeminiService):
    """Free-tier-first: one Gemini recipe call; image lookup uses ordinary web requests only."""

    def __init__(self):
        global _REPAIR_DONE
        super().__init__()
        if not _REPAIR_DONE:
            repair_persisted_ai_images()
            _REPAIR_DONE = True

    def generate_meals(self, prompt):
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")
        if not self.client:
            raise RuntimeError("Gemini client could not be initialized")

        pantry, catalog = _shopping_context()
        pantry_context = ", ".join(pantry[:30]) if pantry else "none"
        catalog_context = "; ".join(catalog[:25]) if catalog else "none"
        instruction = f"""You are Bitewise, a premium visual food ideation engine. Create 8 distinct meal ideas for the user's exact request.

USER REQUEST — HIGHEST PRIORITY:
{prompt}

Pantry: {pantry_context}
Cheap REWE examples: {catalog_context}

Interpret the request semantically, not as a loose category search.
Every returned idea must visibly and meaningfully satisfy the specific intent. Occasion/aesthetic words are hard constraints.
If the user asks for something simple, keep execution genuinely easy while preserving the requested concept.
Do not use generic filler just to reach eight results.
Give each meal a concrete, searchable name describing what appears on the plate.
Prefer pantry/REWE items when sensible, but relevance outranks forcing catalog ingredients.

Return ONLY a compact JSON array. Each object needs exactly:
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps
Rules:
- meal_type: breakfast|lunch|dinner|dessert|snack
- ingredients: [[english_name,quantity,unit]], units only g|ml|unit|cloves
- steps: 3-6 concise objects {{"text":"...","minutes":N}}
- Keep descriptions concise but specific.
- DO NOT return image URLs or image descriptions.
""".strip()

        # Exactly one Gemini request per recipe-generation action.
        response, used_model = self._generate_once(instruction)
        generated = _parse_json_array(response.text or "")

        # Zero-token image resolution: cached Google Images scrape, then Wikimedia fallback.
        for raw in generated:
            if isinstance(raw, dict):
                raw["image"] = resolve_meal_image(raw)

        clean = _persist_generated(generated)
        if not clean:
            raise RuntimeError("Gemini returned meals, but none passed Bitewise validation.")
        for meal in clean:
            meal["generation_model"] = used_model
            meal["generation_prompt"] = str(prompt)[:500]
        return clean
