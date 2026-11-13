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
    "bell pepper": ("bell pepper", "paprika", "rote paprika", "gelbe paprika", "grune paprika", "spitzpaprika"),
    "red onion": ("red onion", "rote zwiebel", "rote speisezwiebel", "rote zwiebeln", "zwiebel rot", "zwiebeln rot"),
    "red cabbage": ("red cabbage", "rotkohl", "rotkraut", "blaukraut"),
    "romaine lettuce": ("romaine lettuce", "romanasalat", "romersalat", "romana salat", "romer salat", "romana salatherzen", "romanasalatherzen", "romana herzen", "romana salat herzen"),
    "white fish fillet": ("white fish fillet", "seelachsfilet", "alaska seelachsfilet", "kabeljaufilet", "pollack fillet"),
    "frozen peas": ("frozen peas", "erbsen", "tiefkuhlerbsen", "tiefkuhl erbsen", "erbsen tiefgekuhlt", "tk erbsen"),
    "chicken breast": ("chicken breast", "hahnchenbrust", "haehnchenbrust", "hahnchenbrustfilet", "haehnchenbrustfilet", "hahnchen brustfilet", "haehnchen brustfilet"),
    "olive oil": ("olive oil", "olivenol", "natives olivenol", "extra natives olivenol"),
    "sesame oil": ("sesame oil", "sesamol", "gerostetes sesamol"),
    "soft tortillas": ("soft tortillas", "weizentortillas", "weizentortilla", "weizen tortillas", "weizen tortilla", "tortilla wraps", "wraps"),
    "firm tofu": ("firm tofu", "naturtofu", "tofu natur", "fester tofu"),
    "curry powder": ("curry powder", "currypulver", "curry pulver", "curry gewurz", "curry gewurzmischung", "curry paste", "currypaste", "madras curry paste"),
    "cumin": ("cumin", "kreuzkummel", "kreuzkuemmel", "kreuz kummel"),
    "vegetable stock": ("vegetable stock", "gemusebruhe", "gemuesebruehe", "gemuse bruhe", "bruhwurfel gemuse", "bruhwuerfel gemuse", "bruhwurfel"),
    "cooking cream": ("cooking cream", "kochcreme", "kochsahne", "sahne zum kochen"),
    "burger buns": ("burger buns", "burger bun", "brioche burger buns", "brioche buns", "hamburger brotchen", "hamburgerbrotchen", "hamburgerbroetchen", "burger brotchen", "burgerbrotchen", "burgerbroetchen", "sesam brotchen", "sesambrötchen", "sesambroetchen", "brötchen", "broetchen"),
    "caesar dressing": ("caesar dressing", "caesar salat dressing", "caesar sauce", "salatdressing caesar"),
    "croutons": ("croutons", "brotcroutons", "croûtons"),
    "canned chopped tomatoes": ("canned chopped tomatoes", "stuckige tomaten", "tomaten stuecke", "tomaten in stuecken"),
    "risotto rice": ("risotto rice", "risottoreis", "risotto reis", "arborio reis", "carnaroli reis"),
    "rolled oats": ("rolled oats", "haferflocken", "kernige haferflocken"),
    "black olives": ("black olives", "schwarze oliven", "oliven schwarz", "olives noires"),
    "canned corn": ("canned corn", "mais aus der dose", "mais dose", "mais konserve", "zuckermais", "dosenmais", "mais konserviert"),
    "frozen sweet corn": ("frozen sweet corn", "tiefkuhl mais", "tiefkuhlmais", "tiefkuhlzuckermais", "mais tiefkuhl", "zuckermais tiefgekuhlt", "tiefgekuhlter zuckermais", "mais tiefgekuhlt", "tiefgekuhlter mais"),
    "fresh cilantro": ("fresh cilantro", "cilantro", "koriander", "frischer koriander", "koriandergrun", "korianderblatter", "korianderkraut"),
    "grated cheddar cheese": ("grated cheddar cheese", "cheddar gerieben", "geriebener cheddar", "cheddar geraspelt", "gouda gerieben", "geriebener gouda", "emmentaler gerieben", "geriebener emmentaler", "gratinkäse", "gratinkaese"),
    "hard boiled eggs": ("hard boiled eggs", "gekochte eier", "eier hart gekocht", "hartgekochte eier"),
    "hard taco shells": ("hard taco shells", "taco shells", "taco schalen", "taco shells knusprig", "taco schalen knusprig"),
    "hot dog buns": ("hot dog buns", "hotdog buns", "hot dog brotchen", "hotdog brotchen", "brioche hot dog buns"),
    "hot dog sausages": ("hot dog sausages", "hotdog wurstchen", "hot dog wurstchen", "wiener wurstchen", "frankfurter wurstchen"),
    "mayonnaise": ("mayonnaise", "mayonnaise", "salatmayonnaise", "delikatess mayonnaise"),
    "paprika powder": ("paprika powder", "paprikapulver", "edelsuß paprika", "edelsuess paprika", "paprika edelsuss"),
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

# These can be useful in a recipe, but are not equivalent enough to
# auto-select. They are retrieved only as explicit user-review suggestions.
_REVIEW_ONLY_SUBSTITUTION_TERMS = {
    "curry powder": ("curry paste", "currypaste", "garam masala", "madras curry paste"),
}


_SUBSTITUTION_TERMS = {
    "vegetable oil": ("sunflower oil", "rapeseed oil", "sonnenblumenol", "rapsol", "ripsol"),
    "sunflower oil": ("vegetable oil", "rapeseed oil", "pflanzenol", "rapsol"),
    "frozen french fries": ("fresh potato", "potato", "potatoes", "kartoffeln", "speisekartoffeln"),
    "parmesan cheese": ("grana padano", "grana padano gerieben"),
    "grated cheddar cheese": ("grated gouda", "geriebener gouda", "gouda gerieben", "emmentaler gerieben", "geriebener emmentaler", "gratinkäse"),
    "fresh cilantro": ("coriander leaves", "koriandergrun"),
    # Slaw can use fresh white cabbage when red cabbage is not stocked.
    "red cabbage": ("white cabbage", "weisskohl", "spitzkohl"),
    # A plain bread roll can stand in for a burger bun when the catalog has no labelled bun.
    "burger buns": ("bread rolls", "brötchen", "weizenbrötchen", "kaiserbrötchen", "sesambrötchen"),
}

_RETAIL_QUERY_VARIANTS = {
    "olivenol": ("olivenöl", "natives olivenöl", "extra natives olivenöl"),
    "rapsol": ("rapsöl",),
    "sonnenblumenol": ("sonnenblumenöl",),
    "sesamol": ("sesamöl",),
    "gemusebruhe": ("gemüsebrühe", "gemüse brühe"),
    "bruhwurfel": ("brühwürfel",),
    "hahnchenbrust": ("hähnchenbrust", "hähnchenbrustfilet", "hähnchen brustfilet"),
    "haehnchenbrust": ("hähnchenbrust", "hähnchenbrustfilet", "hähnchen brustfilet"),
    "kreuzkummel": ("kreuzkümmel",),
    "stuckige tomaten": ("stückige tomaten",),
    "brotchen": ("brötchen",),
    "romersalat": ("römersalat",),
    "croutons": ("croûtons",),
    "zwiebel rot": ("zwiebel rot", "zwiebeln rot"),
    "paprika edelsuss": ("paprika edelsüß",),
}


_PROPOSED_SUBSTITUTION_SYNONYMS = {
    "rapeseed oil": ("rapsol", "rapsoel", "canola oil", "rapeseed oil"),
    "sunflower oil": ("sonnenblumenol", "sonnenblumenoel", "sunflower oil"),
    "olive oil": ("olivenol", "olivenoel", "olive oil"),
    "fresh potatoes": ("speisekartoffeln", "kartoffeln", "fresh potatoes"),
    "coriander leaves": ("koriandergrun", "korianderblatter", "coriander leaves"),
}


def _proposed_term_visible(title: str, term: str) -> bool:
    normalized = normalize_text(term)
    if normalized and _contains_phrase(title, normalized):
        return True
    synonyms = _PROPOSED_SUBSTITUTION_SYNONYMS.get(normalized, ())
    return any(_contains_phrase(title, normalize_text(value)) for value in synonyms)

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
    "spice": ("salt", "black pepper", "peppercorn", "paprika", "paprika powder", "cumin", "cinnamon", "spice", "seasoning", "gewürz", "gewürzmischung", "salz", "pfeffer"),
    "produce": ("bell pepper", "red onion", "pepper", "paprika", "onion", "onions", "garlic", "potato", "potatoes", "tomato", "tomatoes", "lettuce", "cilantro", "carrot", "carrots", "olive", "olives", "zwiebel", "zwiebeln", "knoblauch", "kartoffel", "kartoffeln"),
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
    options = profile.get("substitution_options", [])
    if isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue
            option_terms = [option.get("name"), option.get("name_de")]
            aliases = option.get("aliases", [])
            if isinstance(aliases, list):
                option_terms.extend(aliases)
            for option_term in option_terms:
                normalized_option_term = normalize_text(option_term)
                if normalized_option_term:
                    terms.add(normalized_option_term)
                    terms.update(
                        normalize_text(value)
                        for value in _PROPOSED_SUBSTITUTION_SYNONYMS.get(normalized_option_term, ())
                    )
    terms.update(normalize_text(term) for term in _SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()))
    # Retrieve review-only alternatives too, but keep them out of the
    # auto-match path in ingredient_product_match_type().
    terms.update(
        normalize_text(term)
        for term in _REVIEW_ONLY_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ())
    )
    # REWE product titles preserve German umlauts while matcher text is normalized.
    # Keep both spellings for SQL retrieval; strict matching still normalizes titles.
    retrieval_terms = set(terms)
    for term in terms:
        retrieval_terms.update(_RETAIL_QUERY_VARIANTS.get(term, ()))
    return sorted((term for term in retrieval_terms if len(normalize_text(term)) >= 2),
                  key=lambda term: (-len(normalize_text(term)), term))


def _contains_phrase(title: str, phrase: str) -> bool:
    return bool(phrase and (" " + phrase + " ") in (" " + title + " "))


def _form_compatible(form: str, title: str, ingredient: str = "") -> bool:
    form = normalize_text(form)
    # Recipe generators sometimes return descriptive form labels rather than
    # the compact canonical values. Normalize those labels before enforcing
    # form constraints so "soft tortillas" and "grated cheese" are understood.
    if any(term in form for term in ("soft tortilla", "soft wrap", "weizen tortilla")):
        form = "soft"
    elif any(term in form for term in ("grated", "gerieben", "shredded cheese")):
        form = "grated"
    elif any(term in form for term in ("frozen", "tiefkuhl")):
        form = "frozen"
    elif any(term in form for term in ("fresh", "frisch")):
        form = "fresh"
    elif any(term in form for term in ("powder", "pulver", "ground spice")):
        form = "powder"
    ingredient_tokens = set(normalize_text(ingredient).split())
    fresh_produce_tokens = {"garlic", "onion", "potato", "tomato", "lettuce", "cilantro", "coriander", "carrot", "olive"}
    compound_product_terms = ("wurst", "fleisch", "fisch", "fleischersatz", "sauce", "saucen", "suppe", "brustfilet", "hahnchen", "chicken", "garnelen", "shrimp", "tempeh", "mettwurst", "pesto", "brot", "bread", "butter", "aufstrich")
    if ingredient_tokens & fresh_produce_tokens and any(token in title for token in compound_product_terms):
        return False
    if form == "fresh" and any(token in title for token in ("tiefkuhl", "frozen", "konserve", "dose", "getrocknet", "gemahlen", "gewurze", "gewurz", "spices", "seasonings")):
        return False
    if form in {"frozen", "tiefkuhl"}:
        frozen_markers = ("tiefkuhl", "tiefkuehl", "tiefgefroren", "frozen", " tk ")
        if not any(token in " " + title + " " for token in frozen_markers):
            return False
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
    category_key = normalize_text(category)
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
        "cucumber", "bell pepper", "carrot", "broccoli", "fresh cilantro",
        "mushrooms", "lemon", "lime", "zucchini", "avocado", "spring onion",
        "red cabbage", "strawberries", "blueberries", "banana", "parsley",
    }
    proteins = {
        "chicken breast", "pre cooked shredded chicken", "ground beef",
        "salmon fillet", "bratwurst", "white fish fillet", "bacon",
    }
    dairy = {
        "feta cheese", "sour cream", "cheese slices", "butter", "mozzarella",
        "greek yogurt", "plain yogurt", "cooking cream", "eggs",
        "grated cheddar cheese", "parmesan cheese",
    }
    grains = {
        "rice", "risotto rice", "spaghetti", "pasta", "wheat flour",
        "rolled oats", "pizza dough", "burger buns", "soft tortillas",
        "tortillas", "croutons",
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
        "tomato passata", "mayonnaise", "soy sauce", "salsa",
        "caesar dressing", "vegetable stock", "coconut milk",
    }

    if name == "honey" and any(term in title_key for term in ("senf", "mustard", "dressing", "sauce")):
        return False
    if name == "butter" and any(term in title_key for term in ("peanut", "erdnuss", "mandel", "brotaufstrich", "aufstrich")):
        return False
    if name in {"pasta", "spaghetti"} and any(term in title_key for term in ("udon", "ramen", "glasnudel", "reisnudel", "instant nudel", "mie nudel")):
        return False
    if name == "bell pepper" and any(term in title_key for term in ("pulver", "powder", "chips", "wurst", "lyoner")):
        return False

    # REWE's imported aisle metadata sometimes places wraps and croutons in
    # the convenience-food/oil-and-sauce aisles. Strong product-title evidence
    # should win over those known aisle misclassifications.
    if name in {"soft tortillas", "tortillas"} and any(
        term in title_key for term in ("wrap", "tortilla")
    ) and category_key in {"fertiggerichte-konserven", "brot-cerealien-aufstriche", "kochen-backen"}:
        return True
    if name == "croutons" and any(
        term in title_key for term in ("crouton", "cro ton", "brotwurfel gerostet")
    ) and category_key in {"oele-sossen-gewuerze", "fertiggerichte-konserven"}:
        return True
    if name == "curry powder" and any(
        term in title_key for term in ("curry paste", "currypaste")
    ) and category_key in {"oele-sossen-gewuerze", "fertiggerichte-konserven"}:
        return True
    if name == "burger buns" and any(
        term in title_key for term in ("hamburgerbrotchen", "burgerbrotchen", "burger bun")
    ) and category_key in {"brot-cerealien-aufstriche", "kochen-backen", "fertiggerichte-konserven"}:
        return True

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
            "aufschnitt", "burger patty",
        )
        if any(term in title_key for term in prepared_terms):
            return False
        # Chicken/Hähnchen/Brustfilet are positive ingredient evidence, not
        # prepared-food markers. Only cooked/prepared chicken is excluded here.
        if name == "chicken breast" and any(term in title_key for term in ("gegart", "gekocht", "gebraten", "cooked", "roasted")):
            return False
        allowed = {"fleisch-wurst-fisch", "fleisch"}
        if normalize_text(form) in {"frozen", "tiefkuhl"}:
            allowed.add("tiefkuehlkost")
        return category_key in allowed
    if name == "firm tofu":
        return category_key in {
            "fleisch-wurst-fisch", "fertiggerichte-konserven",
            "kaese-eier-molkerei", "obst-gemuese",
        }
    if name in dairy:
        return category_key == "kaese-eier-molkerei"
    if name in oils:
        return category_key == "oele-sossen-gewuerze"
    if name in spices:
        return category_key in {"oele-sossen-gewuerze", "kochen-backen"}
    if name in grains:
        return (
            category_key in {"kochen-backen", "brot-cerealien-aufstriche"}
            or (name == "rice" and category_key == "rice")
        )
    if name in canned:
        return category_key in {"fertiggerichte-konserven", "obst-gemuese"}
    if name == "honey":
        # Honey must be a jar of honey, not a honey-flavoured prepared food.
        return category_key in {"brot-cerealien-aufstriche", "kochen-backen"}
    if name in sauces:
        allowed = {"oele-sossen-gewuerze", "fertiggerichte-konserven"}
        if name == "salsa":
            allowed.add("suesses-salziges")
        return category_key in allowed
    return True


def _curated_cross_form_substitute(ingredient: str, term: str, title: str) -> bool:
    # Frozen fries -> raw potatoes is an intentional, recipe-adapted transition.
    # Do not let this exception turn potato chips/snacks into a substitute.
    normalized_ingredient = normalize_text(ingredient)
    if normalized_ingredient == "curry powder":
        return (
            normalize_text(term) in {"curry paste", "currypaste", "madras curry paste"}
            and any(token in title for token in ("curry paste", "currypaste"))
            and not any(token in title for token in ("ketchup", "sauce", "suppe", "fertiggericht"))
        )
    if normalized_ingredient == "burger buns":
        # A Kaiser roll is a close, unsweetened round roll and can safely stand
        # in for a burger bun. Other generic rolls and bread mixes stay review-only.
        if (
            normalize_text(term) == normalize_text("kaiserbrötchen")
            and "kaiserbrotchen" in title
        ):
            return False
        bread_mix = any(token in title for token in (
            "proteinmehl", "brotbackmischung", "brotchen backmischung", "brot teig",
        ))
        bread_roll = (
            normalize_text(term) in {
                normalize_text(value) for value in (
                    "bread rolls", "brötchen", "weizenbrötchen",
                    "kaiserbrötchen", "sesambrötchen",
                )
            }
            and any(token in title for token in (
                "brotchen", "bread roll", "bread rolls", "kaisersemmel", "semmel",
            ))
            and not any(token in title for token in (
                "süß", "suess", "rosinen", "schoko", "croissant",
                "hot dog", "hotdog",
            ))
        )
        return bread_mix or bread_roll
    if normalized_ingredient != "frozen french fries":
        return False
    if normalize_text(term) not in {"fresh potato", "potato", "potatoes", "kartoffeln", "speisekartoffeln"}:
        return False
    return (
        any(token in title for token in ("kartoffel", "potato"))
        and not any(token in title for token in ("chips", "snack", "knabberartikel", "wedges", "croquette"))
    )


def _ingredient_specific_exclusions(ingredient: str, title: str) -> bool:
    """Reject known lexical traps before aliases/categories can create false positives."""
    name = normalize_text(ingredient)
    t = normalize_text(title)
    exclusions = {
        "butter": ("peanut butter", "erdnussbutter", "mandelmus", "nuss nougat", "brotaufstrich", "aufstrich", "butterkeks", "butterwaffel"),
        "honey": ("honig senf", "honigsenf", "honig senfsauce", "honig senf sauce", "honig dressing", "honey peppers", "honey pepper", "honig pfeffer", "honig paprika", "honey roasted", "honig gerostet", "honig nuss", "honignuss", "honey nut", "muesli", "musli", "granola", "knusper", "cereal", "riegel"),
        "pasta": ("udon", "ramen", "glasnudeln", "reisnudeln", "instant nudeln", "instant noodles", "mie nudeln", "buchstaben nudeln", "suppennudeln", "suppen nudeln", "faden nudeln"),
        "spaghetti": ("udon", "ramen", "glasnudeln", "reisnudeln", "instant nudeln", "mie nudeln", "buchstaben nudeln", "suppennudeln", "suppen nudeln", "faden nudeln"),
        "bell pepper": ("paprikapulver", "paprika pulver", "paprika chips", "paprika lyoner", "paprika wurst"),
        "red onion": ("red onion chips", "rote zwiebel chips", "zwiebel chips"),
        "chicken breast": ("hahnchen wurst", "haehnchen wurst", "hahnchen aufschnitt", "haehnchen aufschnitt", "brotaufstrich", "gepokelt", "gebacken", "gerauchert", "hauchzart", "delikatess", "paprika", "mariniert", "marinade", "gegrillt", "gewurzt", "gewurzmischung", "joghurt", "knoblauch", "curry", "brandenburg", "bernard matthews", "gutfried", "herta", "finesse", "wiltmann", "filetstucke", "filetstuecke", "hahnchenbrust natur", "haehnchenbrust natur", "hahnchenbrust mit curry"),
        "olive oil": ("olivenol dusche", "olivenol creme", "olivenol shampoo", "olivenol nachtcreme"),
        "vegetable oil": ("olivenol", "massageol", "pflegeol", "haarol", "mayonnaise", "mayo", "salatcreme", "dressing", "sauce", "spray", "spruhol"),
        "white fish fillet": ("fischmus", "seelachs mus", "fischburger", "fischstabchen", "surimi", "fischzubereitung", "paniert", "backteig"),
        "salsa": ("mais rollchen", "mais roellchen", "snack", "chips"),
        "lettuce": ("crispy mix", "salat mix", "salatmischung", "salatmix", "bluten salat", "blutensalat", "baby leaf", "babyleaf", "salat bouquet", "wildkrauter salat", "wildkrautersalat", "feiner salat", "der feine salat"),
    }
    return any(_contains_phrase(t, normalize_text(term)) for term in exclusions.get(name, ()))

def ingredient_product_match_type(ingredient: str, product_text: str, intelligence: Any = None, product_category: str = "") -> str | None:
    title = normalize_text(product_text)
    if not title or _ingredient_specific_exclusions(ingredient, title):
        return None
    # Frozen plain white-fish fillets are a legitimate review-only alternative
    # to fresh fillets; do not silently change the recipe's thawing/preparation.
    if (
        normalize_text(ingredient) == "white fish fillet"
        and normalize_text(product_category) == "tiefkuehlkost"
        and any(term in title for term in ("seelachsfilet", "kabeljaufilet", "pollack fillet"))
        and not any(term in title for term in (
            "paella", "pfanne", "fertiggericht", "fish burger", "fischburger",
            "brotaufstrich", "salat", "suppe", "sauce", "paniert", "backteig",
        ))
    ):
        return "suggested_substitution"
    if normalize_text(ingredient) in {"lettuce", "romaine lettuce", "shredded lettuce"}:
        lettuce_identity_terms = (
            "eisbergsalat", "kopfsalat", "romersalat", "romana", "romaine",
            "salatherzen", "lettuce", "iceberg lettuce", "eisberg salat",
        )
        if "salat" in title and not any(term in title for term in lettuce_identity_terms):
            return None
    profile = _profile_lookup(intelligence, ingredient)
    product_form = str(profile.get("form") or "")
    # Enforce a final retail-aisle guard for fresh produce. Some imported REWE
    # rows contain raw-looking names such as "Rotkohl" while actually belonging
    # to the prepared/canned aisle; title overlap alone must never make them
    # exact fresh-ingredient matches.
    fresh_produce_names = {
        "garlic", "onion", "red onion", "potato", "potatoes", "tomato",
        "tomatoes", "lettuce", "shredded lettuce", "romaine lettuce",
        "cucumber", "bell pepper", "carrot", "broccoli", "fresh cilantro",
        "mushrooms", "lemon", "lime", "zucchini", "avocado", "spring onion",
        "red cabbage", "strawberries", "blueberries", "banana", "parsley",
    }
    category_key = normalize_text(product_category).replace(" ", "-")
    if (
        normalize_text(ingredient) in fresh_produce_names
        and normalize_text(product_form) == "fresh"
        and category_key not in {"obst-gemuese", "frische-krauter"}
    ):
        return None
    form_compatible = _form_compatible(
        product_form,
        title + " " + normalize_text(product_category),
        ingredient,
    )
    category_compatible = _category_compatible(
        ingredient, product_category, title, product_form
    )
    terms = ingredient_search_terms(ingredient, intelligence)
    substitution_only_terms = {
        normalize_text(value)
        for value in (
            *(_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ())),
            *(_REVIEW_ONLY_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ())),
        )
    }
    exact_hit = form_compatible and category_compatible and any(
        _contains_phrase(title, term) for term in terms
        if normalize_text(term) not in substitution_only_terms
    )
    if exact_hit:
        return "exact"
    # Curated equivalents remain substitutions even when the recipe-side AI
    # repeats them in its alias list; metadata must not silently upgrade them.
    substitutes = list(_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()))
    for term in substitutes:
        normalized = normalize_text(term)
        if normalized and _contains_phrase(title, normalized):
            if _curated_cross_form_substitute(ingredient, normalized, title) and category_compatible:
                return "suggested_substitution"
            if form_compatible and category_compatible:
                return "substitute"
    proposed = profile.get("suggested_substitutions", [])
    if isinstance(proposed, str):
        proposed = [proposed]
    options = profile.get("substitution_options", [])
    if isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue
            option_terms = [option.get("name"), option.get("name_de")]
            aliases = option.get("aliases", [])
            if isinstance(aliases, list):
                option_terms.extend(aliases)
            matched_option_term = next(
                (str(term).strip() for term in option_terms
                 if term and _proposed_term_visible(title, str(term))),
                "",
            )
            if not matched_option_term or not category_compatible:
                continue
            safe_option = (
                option.get("safe_to_auto_apply") is True
                and option.get("role_preserved") is True
                and float(option.get("confidence") or 0) >= 0.85
            )
            # A declared transformation may cross the requested retail form
            # (e.g. frozen fries -> fresh potatoes) only when it includes an
            # executable preparation adjustment. Without it, retain form strictness.
            transformation_ready = bool(str(option.get("preparation_adjustment") or "").strip())
            if not form_compatible and not (safe_option and transformation_ready):
                continue
            # Other proposed options remain visible for user review.
            if safe_option and (form_compatible or transformation_ready):
                return "substitute"
            return "suggested_substitution"
    for term in _REVIEW_ONLY_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()):
        normalized = normalize_text(term)
        if not normalized or not _contains_phrase(title, normalized) or not category_compatible:
            continue
        if form_compatible or _curated_cross_form_substitute(ingredient, normalized, title):
            return "suggested_substitution"
    for term in proposed if isinstance(proposed, list) else []:
        normalized = normalize_text(term)
        if normalized and _proposed_term_visible(title, normalized) and form_compatible and category_compatible:
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
    options = profile.get("substitution_options", [])
    if isinstance(options, list):
        for option in sorted((value for value in options if isinstance(value, dict)),
                             key=lambda value: -len(normalize_text(value.get("name")))):
            term = str(option.get("name") or "")
            option_terms = [term, option.get("name_de")]
            aliases = option.get("aliases", [])
            if isinstance(aliases, list):
                option_terms.extend(aliases)
            if term and any(value and _proposed_term_visible(title, str(value)) for value in option_terms):
                return term
    for term in sorted(proposed if isinstance(proposed, list) else [], key=lambda value: -len(normalize_text(value))):
        normalized = normalize_text(term)
        if normalized and _proposed_term_visible(title, normalized):
            return str(term)
    for term in sorted(
        _REVIEW_ONLY_SUBSTITUTION_TERMS.get(normalize_text(ingredient), ()),
        key=lambda value: -len(normalize_text(value)),
    ):
        normalized = normalize_text(term)
        if normalized and _contains_phrase(title, normalized):
            return str(term)
    return None


def validate_ingredient_unit(ingredient: str, unit: str, intelligence: Any = None) -> dict:
    name = normalize_text(ingredient)
    normalized_unit = normalize_text(unit)
    if name in {"bell pepper", "red pepper", "green pepper", "yellow pepper", "sweet pepper", "paprika"}:
        family = "produce"
    else:
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
        # Structured options carry the reasoning needed to adapt a recipe, not
        # merely a synonym to match against a product title.
        raw_options = row.get("substitution_options", [])
        if isinstance(raw_options, dict):
            raw_options = [raw_options]
        if not isinstance(raw_options, list):
            raw_options = []
        substitution_options = []
        for option in raw_options[:8]:
            if not isinstance(option, dict):
                continue
            option_name = str(option.get("name") or option.get("ingredient") or "").strip()[:100]
            if not option_name:
                continue
            option_name_de = str(option.get("name_de") or "").strip()[:100]
            option_aliases = option.get("aliases", [])
            if isinstance(option_aliases, str):
                option_aliases = [option_aliases]
            if not isinstance(option_aliases, list):
                option_aliases = []
            try:
                ratio = float(option.get("quantity_ratio", 1) or 1)
            except (TypeError, ValueError):
                ratio = 1
            if not 0.1 <= ratio <= 5:
                continue
            try:
                confidence = float(option.get("confidence", 0) or 0)
            except (TypeError, ValueError):
                confidence = 0
            substitution_options.append({
                "name": option_name,
                "name_de": option_name_de,
                "aliases": [str(value).strip()[:100] for value in option_aliases[:6]
                            if isinstance(value, str) and value.strip()],
                "quantity_ratio": ratio,
                "confidence": max(0, min(1, confidence)),
                "role_preserved": option.get("role_preserved") is True,
                "safe_to_auto_apply": option.get("safe_to_auto_apply") is True,
                "preparation_adjustment": str(option.get("preparation_adjustment") or "")[:700],
                "reason": str(option.get("reason") or "")[:240],
            })
            substitutions.append(option_name)
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
            "suggested_substitutions": list(dict.fromkeys(
                str(value).strip()[:100] for value in substitutions[:8]
                if isinstance(value, str) and value.strip()
            )),
            "substitution_options": substitution_options,
            "preparation": str(row.get("preparation") or "").strip()[:100],
        }
    return output
