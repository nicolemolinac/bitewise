import json
import math
import re

from .gemini import (
    DATA_FILE,
    MEALS,
    GeminiService as BaseGeminiService,
    _parse_json_array,
    _persist_generated,
)
from ..database import PantryItem, Product, ProductIntelligence, SessionLocal, UserEvent
from ..catalog.intelligence import CLASSIFIER_VERSION, classify_product
from ..recommendations.engine import build_preference_profile
from ..ingredient_aliases import canonical_ingredient_terms, ingredient_product_match_type


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


def _taste_context() -> str:
    """Compact preference signals from existing user feedback; no model training/call."""
    db = SessionLocal()
    try:
        profile = build_preference_profile(db.query(UserEvent).all(), MEALS)
        cuisines = sorted(
            ((key, value) for key, value in profile["cuisines"].items() if value > 0),
            key=lambda item: item[1], reverse=True
        )[:3]
        tags = sorted(
            ((key, value) for key, value in profile["tags"].items() if value > 0),
            key=lambda item: item[1], reverse=True
        )[:5]
        parts = []
        if cuisines:
            parts.append("cuisines: " + ", ".join(key for key, _ in cuisines))
        if tags:
            parts.append("food styles: " + ", ".join(key for key, _ in tags))
        return "; ".join(parts) if parts else "not enough feedback yet"
    finally:
        db.close()


def _catalog_context(query: str = "", limit: int = 60, max_chars: int = 1600, include_intelligence: bool = False):
    """Return a compact list of canonical ingredients backed by priced REWE products.

    The complete catalog stays in SQLite. We validate each candidate ingredient
    against the actual product title locally and send only distinct ingredient
    labels to Gemini. Unknown stock is allowed; explicitly unavailable products
    and products without a positive price are excluded.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(Product, ProductIntelligence)
            .outerjoin(ProductIntelligence, ProductIntelligence.product_id == Product.id)
            .filter(
                Product.supermarket == "REWE",
                Product.price.isnot(None),
                Product.price > 0,
            )
            .yield_per(500)
        )
        coverage = {}
        intelligence_groups = {}
        excluded = {"unavailable", "out_of_stock", "not_available", "discontinued"}
        for product, stored_profile in rows:
            if str(product.availability or "unknown").strip().lower() in excluded:
                continue
            title = " ".join(
                str(value or "")
                for value in (product.name_original, product.name_normalized, product.translated_name)
            )
            # Product.ingredient is not canonical in this import: it can be a
            # normalized copy of the full SKU title. Derive known terms from title.
            canonical_terms = canonical_ingredient_terms(title)
            if not canonical_terms:
                continue

            profile = (
                stored_profile
                if stored_profile and stored_profile.classifier_version == CLASSIFIER_VERSION
                else classify_product({
                    "name_original": product.name_original,
                    "name_normalized": product.name_normalized,
                    "translated_name": product.translated_name,
                    "brand": product.brand,
                    "category": product.category,
                })
            )
            product_type = profile.product_type
            preparation = profile.preparation_state
            storage = profile.storage_type
            complete_meal = profile.is_complete_meal

            # Finished drinks, snacks and non-food SKUs are not ingredient signals.
            if (product_type in {"non_food", "beverage", "snack"}
                    or profile.culinary_role in {"soup", "salad", "dessert"}):
                continue

            if complete_meal:
                group = "complete ready meals"
            elif product_type == "prepared_component":
                group = "prepared components"
            elif storage == "frozen":
                group = "frozen shortcuts"
            else:
                group = None
            if group:
                labels = intelligence_groups.setdefault(group, set())
                for ingredient in canonical_terms:
                    if len(labels) >= 5:
                        break
                    if len(ingredient) <= 48:
                        labels.add(ingredient)

            # Complete dishes are useful as optional convenience ideas, not as
            # ingredient signals for a homemade recipe.
            if complete_meal:
                continue
            for ingredient in canonical_terms:
                match_type = ingredient_product_match_type(ingredient, title, product.category)
                if not match_type:
                    continue
                stats = coverage.setdefault(ingredient, {"exact": 0, "substitute": 0})
                stats[match_type] += 1

        intelligence_context = "; ".join(
            f"{group}: {', '.join(sorted(labels))}"
            for group, labels in sorted(intelligence_groups.items()) if labels
        ) or "No classified convenience products found in the current REWE catalog snapshot."

        if not coverage:
            ingredient_context = "No verified priced REWE ingredient matches in the current catalog snapshot."
            return (ingredient_context, intelligence_context) if include_intelligence else ingredient_context

        query_text = re.sub(r"[^a-z0-9äöüß]+", " ", str(query or "").lower())
        query_tokens = {token for token in query_text.split() if len(token) > 2}

        def rank(item):
            ingredient, stats = item
            tokens = set(ingredient.split())
            phrase_match = 1 if ingredient and ingredient in query_text else 0
            overlap = len(tokens & query_tokens)
            total = stats["exact"] + stats["substitute"]
            return (-phrase_match, -overlap, -stats["exact"], -total, ingredient)

        # Bound both ingredient count and prompt characters. A count-only cap can
        # still produce a large prompt when the catalog contains verbose labels.
        max_items = max(1, min(int(limit), 60))
        char_budget = max(120, min(int(max_chars), 2000))
        selected = []
        used_chars = 0
        for ingredient, _stats in sorted(coverage.items(), key=rank):
            # Canonical keys should be short ingredient names, not pasted product titles.
            if len(ingredient) > 64:
                continue
            extra = len(ingredient) + (2 if selected else 0)
            if used_chars + extra > char_budget:
                continue
            selected.append(ingredient)
            used_chars += extra
            if len(selected) >= max_items:
                break
        ingredient_context = ", ".join(selected)
        return (ingredient_context, intelligence_context) if include_intelligence else ingredient_context
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
        # Local full-catalog retrieval, compressed to canonical ingredient names.
        # Gemini still invents the concepts; these signals only improve feasibility.
        catalog_context, product_intelligence_context = _catalog_context(
            user_request, limit=60, max_chars=1600, include_intelligence=True
        )
        taste_context = _taste_context()

        instruction = f"""You are Bitewise's visual discovery editor. Think like a strong Pinterest board curator, not a novelty recipe generator.

PRIMARY USER SEARCH (this controls the result set):
{user_request}

SECONDARY CONTEXT ONLY — never let this override the search:
Pantry hints: {pantry_context}
REWE catalog ingredient signals (generic names only; not proof of live stock): {catalog_context}
REWE Product Intelligence convenience signals (secondary only; not guaranteed stock): {product_intelligence_context}
Learned taste signals from previous feedback: {taste_context}

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
- Use real catalog ingredient signals when they genuinely suit the dish, but do not restrict ideas to the list or force a match.
- Product Intelligence may inspire optional convenience routes, but complete ready meals are never recipe ingredients and must not dominate a homemade-food search.
- Convenience signals must never narrow the creative range or override the user's explicit dish and search intent.
- The user's explicit search intent and culinary quality always outrank catalog coverage and historical preferences.
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
                "cost_basis": "ai_estimate_per_serving",
                "calories": _safe_number(raw.get("calories"), 400, 50, 1800, integer=True),
                "nutrition_basis": "ai_estimate_unverified",
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
        catalog_ingredients, product_intelligence_context = _catalog_context(
            f"{name} {description} {context or concept.get('discovery_prompt') or ''}",
            include_intelligence=True,
        )

        instruction = f"""Create ONE complete Bitewise recipe for the selected meal concept.

SELECTED CONCEPT: {name}
CONCEPT DESCRIPTION: {description}
MEAL TYPE: {meal_type}
ORIGINAL DISCOVERY CONTEXT: {context or concept.get('discovery_prompt') or 'none'}
{cooking_preferences_instruction(appliances)}
PANTRY: {', '.join(pantry[:30]) if pantry else 'none'}
REWE CATALOG INGREDIENTS: {catalog_ingredients}
REWE PRODUCT INTELLIGENCE CONVENIENCE SIGNALS: {product_intelligence_context}
The REWE list contains canonical ingredient names that have at least one title-validated, positively priced REWE catalog product. It is a compact summary, not the full product database. Catalog prices and stock are snapshots, not live checkout guarantees.

CATALOG-AWARE RECIPE RULES:
- Prefer suitable core ingredients from the REWE catalog list so the recipe can be matched and costed reliably.
- Use the listed canonical ingredient names where they accurately describe the food (for example, "salmon", not a vague phrase such as "fish").
- When choosing a listed ingredient, use its canonical label exactly in the ingredients array (for example, use "salmon" rather than "salmon fillet"); describe the cut or preparation in the cooking steps instead.
- Pantry ingredients may be used even when they are not in the REWE list.
- Normal small pantry staples such as salt, pepper, water and modest seasoning may be included even if not listed.
- Avoid specialty or obscure ingredients that are not listed when a familiar listed ingredient works just as well.
- Treat complete ready meals as optional no-cook alternatives only when the user's request explicitly favors ready-made food; never use a complete meal as an ingredient in a homemade recipe.
- Treat prepared components and frozen shortcuts as optional convenience choices when they genuinely fit the dish and save effort; do not force them.
- Do not force a bad substitution or damage the selected dish merely to increase catalog coverage.
- Keep every ingredient needed for a good recipe; never omit an ingredient just to make the basket look complete.
- Do not claim that a product is currently in stock or invent a price. Bitewise checks every generated ingredient against the full local catalog after generation.

Return ONLY a JSON array containing exactly one object with:
id,name,description,time,difficulty,cost,calories,meal_type,cuisine,tags,ingredients,steps,image

Rules:
- Keep the selected concept recognizable; do not replace it with another dish.
- ingredients: [[english_name,quantity,unit]], units only g|ml|unit|cloves.
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
        clean[0]["generation_model"] = used_model
        clean[0]["expanded_from_concept"] = str(concept.get("id") or "")
        return clean[0]
