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
    "trofie pasta": ("trofie pasta", "trofie", "trofie nudeln", "pasta trofie"),
    "fresh basil pesto": ("fresh basil pesto", "basil pesto", "basilikumpesto", "basilikum pesto", "pesto genovese", "pesto verde"),
    "pine nuts": ("pine nuts", "pinienkerne", "pinienkerne geschaelt", "pignoli"),
    "tomato": ("tomato", "tomatoes", "tomate", "tomaten", "rispentomaten", "strauchtomaten", "roma tomaten"),
    "cherry tomato": ("cherry tomato", "cherry tomatoes", "cocktailtomaten", "kirschtomaten", "mini tomaten", "cherrytomaten"),
    "chicken breast": ("chicken breast", "chicken breasts", "hahnchenbrust", "haehnchenbrust", "hahnchenbrustfilet", "haehnchenbrustfilet", "hahnchenfilets"),
    "ground beef": ("ground beef", "minced beef", "rinderhack", "rinderhackfleisch", "hackfleisch rind"),
    "salmon": ("salmon", "lachs", "lachsfilet", "frisches lachsfilet"),
    "flour": ("flour", "mehl", "weizenmehl", "type 405", "type 550"),
    "heavy cream": ("heavy cream", "whipping cream", "schlagsahne", "sahne", "suesse sahne", "koch sahne", "kochsahne"),
    "greek yogurt": ("greek yogurt", "greek yoghurt", "griechischer joghurt", "joghurt griechischer art", "griechischer sahnejoghurt"),
    "potato": ("potato", "potatoes", "kartoffel", "kartoffeln", "speisekartoffeln"),
    "mushroom": ("mushroom", "mushrooms", "champignon", "champignons", "braune champignons", "kulturpilze"),
    "bell pepper": ("bell pepper", "bell peppers", "paprika", "rote paprika", "gelbe paprika", "grune paprika", "spitzpaprika"),
    "cucumber": ("cucumber", "cucumbers", "gurke", "gurken", "salatgurke", "schlangengurke"),
    "lemon": ("lemon", "lemons", "zitrone", "zitronen", "bio zitronen"),
    "olive oil": ("olive oil", "olivenol", "natives olivenol", "extra natives olivenol", "olivenol extra vergine"),
    "soy sauce": ("soy sauce", "sojasauce", "sojasosse", "sojasosse", "tamari"),
    "tomato paste": ("tomato paste", "tomatenmark", "tomatenpaste", "tomatenmark doppelt konzentriert"),
    "chickpeas": ("chickpeas", "chickpea", "kichererbsen", "kichererbse", "kichererbsen aus der dose"),
    "lentils": ("lentils", "lentil", "linsen", "rote linsen", "berg linsen", "berglinsen", "belugalinsen"),
    "kidney beans": ("kidney beans", "kidney bean", "kidneybohnen", "kidney bohnen", "rote kidneybohnen"),
    "oats": ("oats", "oat flakes", "hafer", "haferflocken", "kernige haferflocken", "zarte haferflocken"),
    "banana": ("banana", "bananas", "banane", "bananen"),
    "baking powder": ("baking powder", "backpulver", "backtriebmittel"),
    "cornstarch": ("cornstarch", "corn starch", "speisestarke", "maisstarke", "maizena"),
    "coconut milk": ("coconut milk", "kokosmilch", "kokosnussmilch", "kokosmilch cremig"),
    "black olives": ("black olives", "schwarze oliven", "oliven schwarz", "olives noires"),
    "canned corn": ("canned corn", "mais aus der dose", "mais dose", "mais konserve", "zuckermais", "dosenmais", "mais konserviert"),
    "frozen sweet corn": ("frozen sweet corn", "tiefkuhl mais", "tiefkuhlmais", "tiefkuhlzuckermais", "mais tiefkuhl", "zuckermais tiefgekuhlt", "tiefgekuhlter zuckermais", "mais tiefgekuhlt", "tiefgekuhlter mais"),
    "fresh cilantro": ("fresh cilantro", "cilantro", "koriander", "frischer koriander", "koriandergrun", "korianderblatter", "korianderkraut"),
    "grated cheddar cheese": ("grated cheddar cheese", "cheddar gerieben", "geriebener cheddar", "cheddar geraspelt"),
    "hard boiled eggs": ("hard boiled eggs", "gekochte eier", "eier hart gekocht", "hartgekochte eier"),
    "hard taco shells": ("hard taco shells", "taco shells", "taco schalen", "taco shells knusprig", "taco schalen knusprig"),
    "hot dog buns": ("hot dog buns", "hotdog buns", "hot dog brotchen", "hotdog brotchen", "brioche hot dog buns"),
    "hot dog sausages": ("hot dog sausages", "hotdog wurstchen", "hot dog wurstchen", "wiener wurstchen", "frankfurter wurstchen"),
    "mayonnaise": ("mayonnaise", "mayonnaise", "salatmayonnaise", "delikatess mayonnaise"),
    "paprika powder": ("paprika powder", "paprikapulver", "edelsuß paprika", "edelsuess paprika"),
    "parmesan cheese": ("parmesan cheese", "parmesan", "parmigiano reggiano", "parmigiano", "parmesan gerieben"),
    "pre-cooked shredded chicken": ("pre cooked shredded chicken", "gegarte hahnchenbrust", "gegartes hahnchen", "hahnchenbrust gegart", "hahnchenstreifen gegart"),
    "shredded lettuce": ("shredded lettuce", "salatstreifen", "geschnittener eisbergsalat", "eisbergsalat geschnitten", "salatherzen geschnitten", "eisbergsalat"),
    "taco seasoning": ("taco seasoning", "taco gewurz", "taco gewurzmix", "gewurz fur tacos", "mexikanische gewurzmischung"),
    "tortillas": ("tortillas", "weizentortillas", "weizentortilla", "wraps", "tortilla wraps"),
    "vegetable oil": ("vegetable oil", "pflanzenol", "neutrales ol"),
    "garlic": ("garlic", "knoblauch", "knoblauchzehe", "knoblauchzehen"),
    "salt": ("salt", "salz", "speisesalz", "meersalz", "jodsalz"),
    "frozen french fries": ("frozen french fries", "pommes frites", "pommes", "tiefkuhl pommes", "tiefkuhlpommes", "backofen pommes", "kartoffelstabchen", "pommes tiefgekuhlt", "tiefgekuhlte pommes"),
    "fresh potato": ("fresh potato", "potato", "potatoes", "kartoffel", "kartoffeln", "speisekartoffeln"),
    "onion": ("onion", "onions", "zwiebel", "zwiebeln", "speisezwiebeln"),
}

_SUBSTITUTION_TERMS = {
    "vegetable oil": ("sunflower oil", "rapeseed oil", "sonnenblumenol", "rapsol", "ripsol"),
    "sunflower oil": ("vegetable oil", "rapeseed oil", "pflanzenol", "rapsol"),
    "frozen french fries": ("fresh potato", "potato", "potatoes", "kartoffeln", "speisekartoffeln"),
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
    "produce": ("onion", "onions", "garlic", "potato", "potatoes", "tomato", "tomatoes", "lettuce", "cilantro", "carrot", "carrots", "olive", "olives", "zwiebel", "zwiebeln", "knoblauch", "kartoffel", "kartoffeln"),
    "count": ("egg", "eggs", "eier", "tortilla", "tortillas", "shell", "shells", "bun", "buns", "wurstchen", "sausage", "sausages"),
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
    """Recall terms include AI-proposed alternatives; only curated equivalences can auto-match."""
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


def _form_compatible(form: str, title: str, ingredient: str = "") -> bool:
    form = normalize_text(form)
    ingredient_tokens = set(normalize_text(ingredient).split())
    fresh_produce_tokens = {"garlic", "onion", "potato", "tomato", "lettuce", "cilantro", "coriander", "carrot", "olive"}
    compound_product_terms = ("wurst", "fleisch", "fisch", "fleischersatz", "sauce", "saucen", "suppe", "brustfilet", "hahnchen", "chicken", "garnelen", "shrimp", "tempeh", "mettwurst", "pesto", "brot", "bread", "butter", "aufstrich")
    if ingredient_tokens & fresh_produce_tokens and any(token in title for token in compound_product_terms):
        return False
    if form == "fresh" and any(token in title for token in ("tiefkuhl", "frozen", "konserve", "dose", "getrocknet", "gemahlen", "gewurze", "gewurz", "spices", "seasonings")):
        return False
    if form in {"frozen", "tiefkuhl"}:
        if any(token in title for token in ("chips", "snack", "knabberartikel")):
            return False
        if any(token in title for token in ("frisch", "fresh", "konserve", "dose", "canned", "getrocknet", "dried", "obst gemuse", "fresh produce")):
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
    if form in {"pre cooked", "precooked"}:
        if any(token in title for token in ("roh", "raw")):
            return False
        if not any(token in title for token in ("gegart", "gekocht", "vorgegart", "cooked", "ready to eat", "verzehrfertig")):
            return False
    return True


def _category_compatible(ingredient: str, category: str, title: str, form: str = "") -> bool:
    """Reject keyword hits from unrelated REWE departments and prepared foods."""
    # REWE exposes display labels with German umlauts. Normalize those to the
    # ASCII transliteration used by the allow/deny lists (ä->ae, ö->oe, ü->ue).
    # normalize_text intentionally strips diacritics for product-name matching,
    # so use a category-specific normalization to avoid rejecting real departments.
    raw_category = str(category or "").casefold()
    raw_category = (raw_category.replace("ä", "ae").replace("ö", "oe")
                    .replace("ü", "ue").replace("ß", "ss"))
    category_key = normalize_text(raw_category)
    if not category_key:
        return True
    name = normalize_text(ingredient)
    title_key = normalize_text(title)
    category_key = category_key.replace(" ", "-")
    if category_key in {
        "drogerie-gesundheit", "tierbedarf", "kueche-haushalt",
        "haus-freizeit", "bonus", "getraenke-genussmittel",
        "kaffee-tee-kakao", "baby-kind",
    }:
        return False

    produce = {
        "garlic", "onion", "red onion", "potato", "potatoes", "tomato",
        "tomatoes", "lettuce", "shredded lettuce", "romaine lettuce",
        "cucumber", "bell pepper", "cherry tomato", "mushroom", "lemon",
        "carrot", "broccoli", "fresh cilantro",
        "mushrooms", "lemon", "lime", "zucchini", "avocado", "spring onion",
        "red cabbage", "strawberries", "blueberries", "banana", "parsley",
    }
    proteins = {
        "chicken breast", "pre cooked shredded chicken", "ground beef",
        "salmon", "salmon fillet", "bratwurst", "white fish fillet", "bacon",
    }
    dairy = {
        "feta cheese", "sour cream", "cheese slices", "butter", "mozzarella",
        "greek yogurt", "plain yogurt", "heavy cream", "cooking cream", "eggs",
        "grated cheddar cheese", "parmesan cheese", "firm tofu",
    }
    grains = {
        "rice", "risotto rice", "spaghetti", "pasta", "wheat flour",
        "rolled oats", "pizza dough", "burger buns", "soft tortillas",
        "tortillas", "trofie pasta", "flour", "oats", "cornstarch", "croutons",
    }
    spices = {
        "curry powder", "cumin", "paprika powder", "oregano",
        "baking powder", "taco seasoning", "salt", "pepper",
    }
    oils = {"vegetable oil", "olive oil", "sesame oil", "sunflower oil"}
    canned = {
        "black beans", "canned tuna", "canned corn", "canned chopped tomatoes",
        "black olives", "pickles",
    }
    sauces = {
        "tomato passata", "tomato paste", "fresh basil pesto", "mayonnaise", "soy sauce", "salsa",
        "caesar dressing", "vegetable stock", "coconut milk", "honey",
    }

    if name in produce:
        normalized_form = normalize_text(form)
        if normalized_form in {"frozen", "tiefkuhl"}:
            return category_key == "tiefkuehlkost"
        if normalized_form in {"canned", "konserve"}:
            return category_key in {"fertiggerichte-konserven", "obst-gemuese"}
        return category_key == "obst-gemuese" or (name == "fresh cilantro" and category_key == "frische-krauter")
    if name in proteins:
        prepared_terms = (
            "ofenbrot", "bolognese", "penne", "lasagne", "suppe",
            "sandwich", "pizza", "salat", "snack", "chips", "baby",
            "brei", "fertiggericht", "brotaufstrich", "fischburger",
        )
        if any(term in title_key for term in prepared_terms):
            return False
        allowed = {"fleisch-wurst-fisch", "fleisch"}
        if normalize_text(form) in {"frozen", "tiefkuhl"}:
            allowed.add("tiefkuehlkost")
        return category_key in allowed
    if name in dairy:
        return category_key == "kaese-eier-molkerei"
    if name in oils:
        return category_key == "oele-sossen-gewuerze"
    if name in spices:
        return category_key in {"oele-sossen-gewuerze", "kochen-backen"}
    if name in grains:
        return category_key in {"kochen-backen", "brot-cerealien-aufstriche"}
    if name in canned:
        return category_key in {"fertiggerichte-konserven", "obst-gemuese"}
    if name in sauces:
        allowed = {"oele-sossen-gewuerze", "fertiggerichte-konserven"}
        if name == "salsa":
            allowed.add("suesses-salziges")
        if name == "honey":
            allowed.update({"brot-cerealien-aufstriche", "kochen-backen"})
        return category_key in allowed
    return True


def _curated_cross_form_substitute(ingredient: str, term: str, title: str) -> bool:
    # Frozen fries -> raw potatoes is an intentional, recipe-adapted transition.
    # Do not let this exception turn potato chips/snacks into a substitute.
    if normalize_text(ingredient) != "frozen french fries":
        return False
    if normalize_text(term) not in {"fresh potato", "potato", "potatoes", "kartoffeln", "speisekartoffeln"}:
        return False
    return (
        any(token in title for token in ("kartoffel", "potato"))
        and not any(token in title for token in ("chips", "snack", "knabberartikel", "wedges", "croquette"))
    )


def ingredient_product_match_type(ingredient: str, product_text: str, intelligence: Any = None, product_category: str = "") -> str | None:
    title = normalize_text(product_text)
    if not title:
        return None
    profile = _profile_lookup(intelligence, ingredient)
    product_form = str(profile.get("form") or "")
    form_compatible = _form_compatible(
        product_form,
        title + " " + normalize_text(product_category),
        ingredient,
    )
    category_compatible = _category_compatible(
        ingredient, product_category, title, product_form
    )
    terms = ingredient_search_terms(ingredient, intelligence)
    if form_compatible and category_compatible and any(_contains_phrase(title, term) for term in terms):
        return "exact"
    substitutes = list(_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()))
    for term in substitutes:
        normalized = normalize_text(term)
        if normalized and _contains_phrase(title, normalized):
            if _curated_cross_form_substitute(ingredient, normalized, title):
                return "suggested_substitution"
            if form_compatible and category_compatible:
                return "substitute"
    proposed = profile.get("suggested_substitutions", [])
    if isinstance(proposed, str):
        proposed = [proposed]
    for term in proposed if isinstance(proposed, list) else []:
        normalized = normalize_text(term)
        if normalized and _contains_phrase(title, normalized) and form_compatible and category_compatible:
            return "suggested_substitution"
    return None


def ingredient_substitution_name(ingredient: str, product_text: str, intelligence: Any = None) -> str | None:
    title = normalize_text(product_text)
    substitutes = list(_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()))
    for term in sorted(substitutes, key=lambda value: -len(normalize_text(value))):
        normalized = normalize_text(term)
        if normalized and _contains_phrase(title, normalized):
            labels = {"rapsol": "rapeseed oil", "sonnenblumenol": "sunflower oil", "kartoffeln": "fresh potatoes", "speisekartoffeln": "fresh potatoes"}
            return labels.get(normalized, str(term))
    return None


def ingredient_suggested_substitution_name(ingredient: str, product_text: str, intelligence: Any = None) -> str | None:
    """Return an AI-proposed alternative only when its name is visible in the chosen product."""
    title = normalize_text(product_text)
    profile = _profile_lookup(intelligence, ingredient)
    proposed = profile.get("suggested_substitutions", [])
    if isinstance(proposed, str):
        proposed = [proposed]
    for term in sorted(proposed if isinstance(proposed, list) else [], key=lambda value: -len(normalize_text(value))):
        normalized = normalize_text(term)
        if normalized and _contains_phrase(title, normalized):
            return str(term)
    return None


def validate_ingredient_unit(ingredient: str, unit: str, intelligence: Any = None) -> dict:
    name = normalize_text(ingredient)
    normalized_unit = normalize_text(unit)
    family = next((key for key, hints in _FAMILY_HINTS.items()
                   if any(normalize_text(hint) in name.split() for hint in hints)), None)
    if family is None:
        return {"valid": True, "family": None, "reason": None}
    allowed = set(_UNIT_FAMILIES[family])
    profile = _profile_lookup(intelligence, ingredient)
    form = normalize_text(profile.get("form") or "")
    if family == "produce" and form == "powder":
        allowed = {"g", "kg", "ml", "l", "tsp", "tbsp", "pinch"}
    elif family == "produce" and form == "grated":
        allowed = {"g", "kg"}
    if normalized_unit in allowed:
        return {"valid": True, "family": family, "reason": None}
    return {
        "valid": False,
        "family": family,
        "reason": f"Unit '{unit}' is not valid for ingredient family '{family}'.",
    }


def _infer_ingredient_form(ingredient: str) -> str:
    name = normalize_text(ingredient)
    rules = (
        (("frozen", "tiefkuhl", "deep frozen"), "frozen"),
        (("canned", "tinned", "konserve", "dose"), "canned"),
        (("grated", "gerieben", "geraspelt"), "grated"),
        (("powder", "pulver", "ground"), "powder"),
        (("pre cooked", "precooked", "cooked", "gegart", "gekocht"), "pre_cooked"),
        (("dried", "getrocknet", "dry"), "dried"),
        (("fresh", "frisch"), "fresh"),
        (("soft", "weich"), "soft"),
        (("hard", "knusprig", "crunchy"), "hard"),
        (("oil", "ol"), "liquid"),
    )
    for tokens, form in rules:
        if any(_contains_phrase(name, token) for token in tokens):
            return form
    return "unspecified"


def normalize_recipe_intelligence(recipe: dict) -> dict:
    """Normalize AI metadata and create deterministic fallback profiles for omissions."""
    raw = recipe.get("ingredient_intelligence")
    rows_by_key = {}
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = [{"ingredient": key, **(value if isinstance(value, dict) else {})}
                for key, value in raw.items()]
    else:
        rows = []
    valid_ingredients = [
        (str(row[0]).strip(), str(row[2] if len(row) > 2 else "").strip())
        for row in recipe.get("ingredients", [])
        if isinstance(row, (list, tuple)) and row and str(row[0]).strip()
    ]
    valid_names = {normalize_text(name) for name, _ in valid_ingredients}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ingredient = str(row.get("ingredient") or "").strip()
        key = normalize_text(ingredient)
        if key and key in valid_names:
            rows_by_key[key] = row

    output = {}
    for ingredient, unit in valid_ingredients:
        key = normalize_text(ingredient)
        row = rows_by_key.get(key, {})
        aliases = row.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list):
            aliases = []
        aliases = list(aliases) + list(_BASE_TERMS.get(key, ()))
        substitutions = row.get("suggested_substitutions", row.get("allowed_substitutions", []))
        if isinstance(substitutions, str):
            substitutions = [substitutions]
        if not isinstance(substitutions, list):
            substitutions = []
        unit_key = normalize_text(unit)
        if unit_key in {"g", "kg"}:
            inferred_dimension = "mass"
        elif unit_key in {"ml", "l", "tsp", "tbsp"}:
            inferred_dimension = "volume"
        elif unit_key in {"unit", "piece", "cloves"}:
            inferred_dimension = "count"
        else:
            inferred_dimension = ""
        form = str(row.get("form") or "").strip()
        if not form or normalize_text(form) in {"unspecified", "unknown"}:
            form = _infer_ingredient_form(ingredient)
        output[key] = {
            "canonical": str(row.get("canonical") or ingredient).strip()[:100],
            "name_en": str(row.get("name_en") or ingredient).strip()[:100],
            "name_de": str(row.get("name_de") or "").strip()[:100],
            "name_es": str(row.get("name_es") or "").strip()[:100],
            "aliases": list(dict.fromkeys(
                str(value).strip()[:100] for value in aliases[:30]
                if isinstance(value, str) and value.strip()
            )),
            "form": form[:50],
            "culinary_role": str(row.get("culinary_role") or "").strip()[:80],
            "unit_dimension": str(row.get("unit_dimension") or inferred_dimension).strip()[:20],
            "suggested_substitutions": [
                str(value).strip()[:100] for value in substitutions[:8]
                if isinstance(value, str) and value.strip()
            ],
            "preparation": str(row.get("preparation") or "").strip()[:100],
        }
    return output
