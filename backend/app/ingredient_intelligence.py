"""Low-cost ingredient intelligence for recipe-to-REWE matching.

Recipe-side intent is generated once with the recipe and cached in recipe history.
All shopping-time normalization, retrieval hints and validation are deterministic.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold().replace("ß", "ss"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Small, high-confidence cross-language vocabulary. This is a seed ontology,
# not the full catalog: recipe-side AI metadata expands it per ingredient.
_BASE_TERMS = {
    "black olives": ("black olives", "schwarze oliven", "oliven schwarz", "olives noires"),
    "canned corn": ("canned corn", "mais aus der dose", "mais dose", "mais konserve", "zuckermais"),
    "frozen sweet corn": ("frozen sweet corn", "tiefkuhl mais", "tiefkuhlmais", "tiefkuhlzuckermais", "mais tiefkuhl"),
    "fresh cilantro": ("fresh cilantro", "cilantro", "koriander", "frischer koriander", "koriandergrun"),
    "grated cheddar cheese": ("grated cheddar cheese", "cheddar gerieben", "geriebener cheddar", "cheddar geraspelt"),
    "hard boiled eggs": ("hard boiled eggs", "gekochte eier", "eier hart gekocht", "hartgekochte eier"),
    "hard taco shells": ("hard taco shells", "taco shells", "taco schalen", "taco shells knusprig", "taco schalen knusprig"),
    "hot dog buns": ("hot dog buns", "hotdog buns", "hot dog brotchen", "hotdog brotchen", "brioche hot dog buns"),
    "hot dog sausages": ("hot dog sausages", "hotdog wurstchen", "hot dog wurstchen", "wiener wurstchen", "frankfurter wurstchen"),
    "mayonnaise": ("mayonnaise", "mayonnaise", "salatmayonnaise", "delikatess mayonnaise"),
    "paprika powder": ("paprika powder", "paprikapulver", "edelsuß paprika", "edelsuess paprika"),
    "parmesan cheese": ("parmesan cheese", "parmesan", "parmigiano reggiano", "parmigiano", "parmesan gerieben"),
    "pre-cooked shredded chicken": ("pre cooked shredded chicken", "gegarte hahnchenbrust", "gegartes hahnchen", "hahnchenbrust gegart", "hahnchenstreifen gegart"),
    "shredded lettuce": ("shredded lettuce", "salatstreifen", "geschnittener eisbergsalat", "eisbergsalat geschnitten", "salatherzen geschnitten"),
    "taco seasoning": ("taco seasoning", "taco gewurz", "taco gewurzmix", "gewurz fur tacos", "mexikanische gewurzmischung"),
    "tortillas": ("tortillas", "weizentortillas", "weizentortilla", "wraps", "tortilla wraps"),
    "vegetable oil": ("vegetable oil", "pflanzenol", "neutrales ol"),
    "garlic": ("garlic", "knoblauch", "knoblauchzehe", "knoblauchzehen"),
    "salt": ("salt", "salz", "speisesalz", "meersalz", "jodsalz"),
    "frozen french fries": ("frozen french fries", "pommes frites", "pommes", "tiefkuhl pommes", "tiefkuhlpommes", "backofen pommes", "kartoffelstabchen"),
    "fresh potato": ("fresh potato", "potato", "potatoes", "kartoffel", "kartoffeln", "speisekartoffeln"),
    "onion": ("onion", "onions", "zwiebel", "zwiebeln", "speisezwiebeln"),
}

_SUBSTITUTION_TERMS = {
    "vegetable oil": ("sunflower oil", "rapeseed oil", "sonnenblumenol", "rapsol", "ripsol"),
    "sunflower oil": ("vegetable oil", "rapeseed oil", "pflanzenol", "rapsol"),
    "frozen french fries": ("fresh potato", "potato", "kartoffeln", "speisekartoffeln"),
    "parmesan cheese": ("grana padano", "grana padano gerieben"),
    "fresh cilantro": ("coriander leaves", "koriandergrun"),
}

# Ingredient-family unit expectations. Unknown families remain permissive.
_UNIT_FAMILIES = {
    "oil": {"ml", "l", "tbsp", "tsp"},
    "liquid": {"ml", "l", "g", "kg", "tbsp", "tsp", "cup"},
    "spice": {"g", "kg", "ml", "l", "tsp", "tbsp", "pinch"},
    "produce": {"g", "kg", "piece", "unit", "cloves"},
    "count": {"piece", "unit"},
}
_FAMILY_HINTS = {
    "oil": ("oil", "pflanzenol", "sonnenblumenol", "rapsol", "olivenol"),
    "liquid": ("milk", "cream", "sauce", "vinegar", "stock", "juice", "sahne", "milch", "essig", "brühe"),
    "spice": ("salt", "pepper", "paprika", "cumin", "cinnamon", "spice", "seasoning", "gewürz", "gewürzmischung", "salz", "pfeffer"),
    "produce": ("onion", "garlic", "potato", "tomato", "lettuce", "cilantro", "carrot", "zwiebel", "knoblauch", "kartoffel"),
}


def _profile_lookup(intelligence: Any, ingredient: str) -> dict:
    if not isinstance(intelligence, dict):
        return {}
    if any(field in intelligence for field in ("canonical", "name_en", "name_de", "form", "aliases")):
        return intelligence
    key = normalize_text(ingredient)
    direct = intelligence.get(ingredient) or intelligence.get(key)
    if isinstance(direct, dict):
        return direct
    for raw_key, value in intelligence.items():
        if normalize_text(raw_key) == key and isinstance(value, dict):
            return value
    return {}


def ingredient_search_terms(ingredient: str, intelligence: Any = None) -> list[str]:
    profile = _profile_lookup(intelligence, ingredient)
    terms = {normalize_text(ingredient)}
    terms.update(normalize_text(term) for term in _BASE_TERMS.get(normalize_text(ingredient), ()))
    for field in ("canonical", "name_en", "name_de", "name_es"):
        value = profile.get(field)
        if isinstance(value, str):
            terms.add(normalize_text(value))
    for field in ("aliases", "search_terms", "translations"):
        values = profile.get(field, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            terms.update(normalize_text(value) for value in values if isinstance(value, str))
    return sorted((term for term in terms if len(term) >= 2), key=lambda term: (-len(term), term))


def ingredient_candidate_search_terms(ingredient: str, intelligence: Any = None) -> list[str]:
    """Recall terms include curated/AI-approved substitutes; matching still labels them separately."""
    terms = set(ingredient_search_terms(ingredient, intelligence))
    profile = _profile_lookup(intelligence, ingredient)
    substitutes = profile.get("suggested_substitutions", profile.get("allowed_substitutions", []))
    if isinstance(substitutes, str):
        substitutes = [substitutes]
    terms.update(normalize_text(term) for term in substitutes if isinstance(term, str))
    terms.update(normalize_text(term) for term in _SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()))
    return sorted((term for term in terms if len(term) >= 2), key=lambda term: (-len(term), term))


def _contains_phrase(title: str, phrase: str) -> bool:
    return bool(phrase and (" " + phrase + " ") in (" " + title + " "))


def _form_compatible(form: str, title: str) -> bool:
    form = normalize_text(form)
    if form == "fresh" and any(token in title for token in ("tiefkuhl", "frozen", "konserve", "dose", "getrocknet", "gemahlen", "gewurze", "gewurz", "spices", "seasonings")):
        return False
    if form in {"canned", "konserve"} and any(token in title for token in ("tiefkuhl", "frozen", "frisch", "fresh")):
        return False
    if form in {"grated", "gerieben"} and not any(token in title for token in ("gerieben", "geraspelt", "grated")):
        return False
    if form == "soft" and any(token in title for token in ("chips", "nacho", "hard shell", "taco shell", "knusprig", "crunchy", "snack", "knabberartikel", "salzig", "salted", "gesalzen")):
        return False
    if form == "hard" and not any(token in title for token in ("shell", "schale", "knusprig", "crunchy", "hard taco")):
        return False
    if form in {"powder", "pulver"} and not any(token in title for token in ("pulver", "powder", "gemahlen")):
        return False
    if form in {"pre cooked", "precooked"} and any(token in title for token in ("roh", "raw")):
        return False
    return True


def ingredient_product_match_type(ingredient: str, product_text: str, intelligence: Any = None, product_category: str = "") -> str | None:
    title = normalize_text(product_text)
    if not title:
        return None
    profile = _profile_lookup(intelligence, ingredient)
    if not _form_compatible(str(profile.get("form") or ""), title + " " + normalize_text(product_category)):
        return None
    terms = ingredient_search_terms(ingredient, intelligence)
    if any(_contains_phrase(title, term) for term in terms):
        return "exact"
    substitutes = list(_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()))
    for term in substitutes:
        normalized = normalize_text(term)
        if normalized and _contains_phrase(title, normalized):
            return "substitute"
    return None


def ingredient_substitution_name(ingredient: str, product_text: str, intelligence: Any = None) -> str | None:
    title = normalize_text(product_text)
    profile = _profile_lookup(intelligence, ingredient)
    substitutes = profile.get("allowed_substitutions", [])
    if isinstance(substitutes, str):
        substitutes = [substitutes]
    substitutes = list(substitutes) + list(_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()))
    for term in sorted(substitutes, key=lambda value: -len(normalize_text(value))):
        normalized = normalize_text(term)
        if normalized and _contains_phrase(title, normalized):
            labels = {"rapsol": "rapeseed oil", "sonnenblumenol": "sunflower oil", "kartoffeln": "fresh potatoes", "speisekartoffeln": "fresh potatoes"}
            return labels.get(normalized, str(term))
    return None


def validate_ingredient_unit(ingredient: str, unit: str) -> dict:
    name = normalize_text(ingredient)
    normalized_unit = normalize_text(unit)
    family = next((key for key, hints in _FAMILY_HINTS.items()
                   if any(normalize_text(hint) in name.split() for hint in hints)), None)
    if family is None:
        return {"valid": True, "family": None, "reason": None}
    allowed = _UNIT_FAMILIES[family]
    if normalized_unit in allowed:
        return {"valid": True, "family": family, "reason": None}
    return {
        "valid": False,
        "family": family,
        "reason": f"Unit '{unit}' is not valid for ingredient family '{family}'.",
    }


def normalize_recipe_intelligence(recipe: dict) -> dict:
    """Validate and normalize optional AI metadata without making another model call."""
    raw = recipe.get("ingredient_intelligence")
    output = {}
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = [{"ingredient": key, **(value if isinstance(value, dict) else {})}
                for key, value in raw.items()]
    else:
        rows = []
    valid_names = {normalize_text(row[0]) for row in recipe.get("ingredients", [])
                   if isinstance(row, (list, tuple)) and row}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ingredient = str(row.get("ingredient") or "").strip()
        key = normalize_text(ingredient)
        if not key or key not in valid_names:
            continue
        aliases = row.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list):
            aliases = []
        substitutions = row.get("suggested_substitutions", row.get("allowed_substitutions", []))
        if isinstance(substitutions, str):
            substitutions = [substitutions]
        if not isinstance(substitutions, list):
            substitutions = []
        output[key] = {
            "canonical": str(row.get("canonical") or ingredient).strip()[:100],
            "name_en": str(row.get("name_en") or ingredient).strip()[:100],
            "name_de": str(row.get("name_de") or "").strip()[:100],
            "name_es": str(row.get("name_es") or "").strip()[:100],
            "aliases": [str(value).strip()[:100] for value in aliases[:20]
                        if isinstance(value, str) and value.strip()],
            "form": str(row.get("form") or "unspecified").strip()[:50],
            "culinary_role": str(row.get("culinary_role") or "").strip()[:80],
            "unit_dimension": str(row.get("unit_dimension") or "").strip()[:20],
            "suggested_substitutions": [
                str(value).strip()[:100] for value in substitutions[:8]
                if isinstance(value, str) and value.strip()
            ],
            "preparation": str(row.get("preparation") or "").strip()[:100],
        }
    return output
