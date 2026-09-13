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


def repair_persisted_ai_images(gemini_client=None, gemini_model: str = "gemini-3.8-flash") -> int:
    """Repair old missing/untrusted meal images once a grounded Gemini client is available."""
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
            resolved = resolve_meal_image(
                raw,
                gemini_client=gemini_client,
                gemini_model=gemini_model,
            )
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
    """Token-lean meal generation; grounded Gemini search is used only for unresolved photos."""

    def __init__(self):
        global _REPAIR_DONE
        super().__init__()
        # Repair legacy AI images only once per backend process, after the Gemini client exists.
        # Existing valid image-cache hits are free; Gemini Search is only used for unresolved meals.
        if not _REPAIR_DONE and self.client:
            repair_persisted_ai_images(self.client, self.model)
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
Before choosing dishes, silently identify all explicit and implicit intent dimensions in the request, including:
- meal type and cuisine
- occasion or mood (for example romantic, date-night, cozy, birthday, picnic, brunch)
- visual/aesthetic intent (for example cute, heart-shaped, elegant, colorful, restaurant-like)
- effort level and simplicity
- budget, health, protein or speed constraints
- named ingredients or appliances

CRITICAL RELEVANCE RULES:
- Every returned idea must visibly and meaningfully satisfy the specific intent, not merely belong to the same meal category.
- Occasion/aesthetic words are hard constraints, not optional flavor text.
- Example: for "romantic breakfast simple", do NOT fill the list with generic croissants or ordinary toast. Prefer ideas such as heart-shaped eggs/toast, strawberry-heart pancakes, berry yogurt arranged for two, heart-cut French toast, rose/berry breakfast plates, or similarly obvious romantic presentation that is still simple.
- If the user asks for something "simple", keep execution genuinely easy while preserving the requested concept.
- Do not use generic filler just to reach eight results. If necessary, vary presentation, base ingredient, cooking method, or sweet/savory direction while staying on-theme.
- Give each meal a concrete, searchable name that describes what the user would actually see on the plate. This name is later used to find a matching real food photo.
- The description must state the visual hook or why it matches the requested occasion/mood.
- Prefer pantry/REWE items when sensible, but relevance to the user's request outranks forcing catalog ingredients.

Return ONLY a compact JSON array. Each object needs exactly:
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps
Rules:
- meal_type: breakfast|lunch|dinner|dessert|snack
- ingredients: [[english_name,quantity,unit]], units only g|ml|unit|cloves
- steps: 3-6 concise objects {{"text":"...","minutes":N}}
- tags should include the important intent words when relevant, e.g. Romantic, Cute, Date Breakfast, Quick.
- Keep descriptions concise but specific.
- DO NOT return image URLs or image descriptions in this recipe-generation call.
""".strip()

        response, used_model = self._generate_with_resilience(instruction)
        generated = _parse_json_array(response.text or "")

        # Image resolution is separate so the recipe response stays small. The resolver uses the
        # specific generated dish name/ingredients, which keeps the photo aligned with the user's
        # request instead of falling back to generic breakfast/dinner imagery.
        for raw in generated:
            if isinstance(raw, dict):
                raw["image"] = resolve_meal_image(
                    raw,
                    gemini_client=self.client,
                    gemini_model=used_model,
                )

        clean = _persist_generated(generated)
        if not clean:
            raise RuntimeError("Gemini returned meals, but none passed Bitewise validation.")
        for meal in clean:
            meal["generation_model"] = used_model
            meal["generation_prompt"] = str(prompt)[:500]
        return clean
