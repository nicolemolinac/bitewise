import re
import unicodedata

# Deterministic, token-free English <-> German ingredient aliases for REWE matching.
# Keep canonical recipe ingredients in English; expand only at catalog-search time.
_ALIAS_GROUPS = [
    ("egg", "eggs", "ei", "eier"),
    ("milk", "milch", "vollmilch", "frischmilch"),
    ("butter", "butter"),
    ("cheese", "käse", "kaese"),
    ("cream", "sahne", "schlagsahne", "kochcreme"),
    ("yogurt", "yoghurt", "joghurt"),
    ("greek yogurt", "greek yoghurt", "griechischer joghurt", "griechischer yoghurt", "joghurt griechischer art", "joghurt nach griechischer art", "griechischer art"),
    ("quark", "quark", "speisequark"),
    ("mozzarella", "mozzarella"),
    ("parmesan", "parmesan", "parmigiano", "parmigiano reggiano"),
    ("feta", "feta", "hirtenkäse", "hirtenkaese"),
    ("chicken", "hähnchen", "haehnchen", "huhn", "hühner", "huehner"),
    ("chicken breast", "hähnchenbrust", "haehnchenbrust", "hähnchenbrustfilet", "haehnchenbrustfilet", "hähnchenbrustfilets"),
    ("beef", "rind", "rindfleisch"),
    ("ground beef", "minced beef", "rinderhack", "hackfleisch", "rinderhackfleisch"),
    ("pork", "schwein", "schweinefleisch"),
    ("salmon", "lachs", "lachsfilet", "lachsfilets"),
    ("tuna", "thunfisch"),
    ("shrimp", "prawn", "garnele", "garnelen"),
    ("tofu", "tofu"),
    ("bread", "brot"),
    ("toast", "toast", "toastbrot"),
    ("flour", "mehl", "weizenmehl"),
    ("oats", "oat", "haferflocken", "hafer"),
    ("rice", "reis", "langkornreis", "basmatireis", "jasminreis", "vollkornreis", "naturreis"),
    ("pasta", "nudeln", "pasta"),
    ("trofie pasta", "trofie"),
    ("fresh basil pesto", "basil pesto", "pesto alla genovese", "pesto genovese", "basilikum pesto", "basilikum-pesto"),
    ("ricotta", "ricotta"),
    ("basil", "basil", "basilikum"),
    ("oregano", "oregano"),
    ("thyme", "thyme", "thymian"),
    ("rosemary", "rosemary", "rosmarin"),
    ("parsley", "parsley", "petersilie"),
    ("chives", "schnittlauch"),
    ("dill", "dill"),
    ("sage", "salbei"),
    ("chili flakes", "chiliflocken", "chiliflocke", "peperoncino"),
    ("chili powder", "chil pulver", "chilipulver"),
    ("nutmeg", "muskat", "muskatnuss"),
    ("italian seasoning", "italienische kräuter", "italienische kraeuter"),
    ("vegetable broth", "vegetable stock", "gemüsebrühe", "gemuesebruehe", "gemüse bouillon", "gemuesebouillon"),
    ("chicken broth", "chicken stock", "hühnerbrühe", "huehnerbruehe", "hühner bouillon"),
    ("beef broth", "rinderbrühe", "rinderbouillon"),
    ("white wine", "weißwein", "weisswein"),
    ("red wine", "rotwein"),
    ("lemon zest", "zitronenschale", "bio zitronenschale"),
    ("tomato passata", "passata", "passierte tomaten"),
    ("breadcrumbs", "semmelbrösel", "semmelbroesel", "paniermehl"),
    ("balsamic vinegar", "balsamico", "balsamico essig"),
    ("pine nuts", "pinienkerne", "pinienkerne natur"),
    ("spaghetti", "spaghetti"),
    ("noodles", "nudeln"),
    ("couscous", "couscous"),
    ("quinoa", "quinoa"),
    ("potato", "potatoes", "kartoffel", "kartoffeln"),
    ("sweet potato", "sweet potatoes", "süßkartoffel", "süßkartoffeln", "suesskartoffel", "suesskartoffeln"),
    ("tomato", "tomatoes", "tomate", "tomaten", "rispentomate", "rispentomaten"),
    ("cherry tomato", "cherry tomatoes", "cherrytomate", "cherrytomaten", "kirschtomate", "kirschtomaten", "cocktailtomate", "cocktailtomaten", "datteltomate", "datteltomaten"),
    ("cucumber", "gurke", "salatgurke"),
    ("onion", "onions", "zwiebel", "zwiebeln"),
    ("red onion", "rote zwiebel", "rote zwiebeln"),
    ("garlic", "knoblauch"),
    ("carrot", "carrots", "karotte", "karotten", "möhre", "möhren", "moehre", "moehren"),
    ("bell pepper", "pepper", "paprika"),
    ("zucchini", "courgette", "zucchini"),
    ("eggplant", "aubergine"),
    ("broccoli", "brokkoli"),
    ("cauliflower", "blumenkohl"),
    ("spinach", "spinat"),
    ("lettuce", "salat", "kopfsalat"),
    ("mushroom", "mushrooms", "pilz", "pilze", "champignon", "champignons"),
    ("avocado", "avocado"),
    ("banana", "bananas", "banane", "bananen"),
    ("apple", "apples", "apfel", "äpfel", "aepfel"),
    ("lemon", "lemons", "zitrone", "zitronen"),
    ("lime", "limes", "limette", "limetten"),
    ("orange", "oranges", "orange", "orangen"),
    ("strawberry", "strawberries", "erdbeere", "erdbeeren"),
    ("blueberry", "blueberries", "heidelbeere", "heidelbeeren", "blaubeere", "blaubeeren"),
    ("raspberry", "raspberries", "himbeere", "himbeeren"),
    ("grape", "grapes", "traube", "trauben"),
    ("peanut butter", "erdnussbutter", "erdnussmus"),
    ("peanut", "peanuts", "erdnuss", "erdnüsse", "erdnuesse"),
    ("almond", "almonds", "mandel", "mandeln"),
    ("walnut", "walnuts", "walnuss", "walnüsse", "walnuesse"),
    ("olive oil", "olivenöl", "olivenoel"),
    ("oil", "öl", "oel"),
    ("vinegar", "essig"),
    ("soy sauce", "sojasauce", "soja sauce"),
    ("tomato sauce", "tomatensauce"),
    ("tomato paste", "tomatenmark"),
    ("coconut milk", "kokosmilch"),
    ("honey", "honig"),
    ("maple syrup", "ahornsirup"),
    ("sugar", "zucker"),
    ("brown sugar", "brauner zucker", "rohrzucker"),
    ("salt", "salz", "speisesalz", "meersalz", "jodsalz", "table salt"),
    ("black pepper", "schwarzer pfeffer", "pfeffer"),
    ("paprika powder", "paprikapulver"),
    ("cinnamon", "zimt"),
    ("vanilla", "vanille"),
    ("baking powder", "backpulver"),
    ("baking soda", "natron"),
    ("cornstarch", "speisestärke", "speisestaerke", "maisstärke", "maisstaerke"),
    ("chickpea", "chickpeas", "kichererbse", "kichererbsen"),
    ("bean", "beans", "bohne", "bohnen"),
    ("kidney beans", "kidneybohnen", "kidney bohnen"),
    ("lentil", "lentils", "linse", "linsen"),
    ("corn", "sweetcorn", "mais"),
    ("peas", "pea", "erbse", "erbsen"),
    ("ham", "schinken"),
    ("bacon", "speck", "bacon"),
    ("sausage", "sausages", "wurst", "würstchen", "wuerstchen"),
    ("turkey", "pute", "putenfleisch"),
    ("wrap", "wraps", "tortilla", "tortillas", "weizentortilla"),
]


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFC", str(value or "").lower())
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_ALIAS_INDEX: dict[str, set[str]] = {}
for group in _ALIAS_GROUPS:
    normalized = {_norm(x) for x in group if _norm(x)}
    for term in normalized:
        _ALIAS_INDEX.setdefault(term, set()).update(normalized)


def ingredient_aliases(value: str) -> list[str]:
    """Return deterministic EN/DE search terms for an ingredient, longest first."""
    needle = _norm(value)
    if not needle:
        return []
    aliases = set(_ALIAS_INDEX.get(needle, {needle}))
    aliases.add(needle)
    # Lightweight singular/plural fallback for recipe-side English terms.
    if needle.endswith("ies") and len(needle) > 4:
        aliases.add(needle[:-3] + "y")
    elif needle.endswith("s") and len(needle) > 3:
        aliases.add(needle[:-1])
    else:
        aliases.add(needle + "s")
    return sorted((x for x in aliases if x), key=lambda x: (-len(x), x))


def ingredient_name_matches(ingredient: str, product_name: str) -> bool:
    """Require a complete compatible ingredient phrase in the actual product title."""
    title = _norm(product_name)
    if not title:
        return False
    padded_title = " " + title + " "
    for alias in ingredient_aliases(ingredient):
        padded_alias = " " + _norm(alias) + " "
        if padded_alias in padded_title:
            return True
    return False


# Explicit culinary substitutions are separate from exact aliases. They are surfaced
# as substitutions in the basket instead of being silently presented as exact matches.
_SUBSTITUTION_GROUPS = {
    "trofie pasta": ("fusilli", "penne", "farfalle", "rigatoni", "casarecce", "orecchiette", "short pasta"),
    "parmesan": ("grana padano",),
    "pine nuts": ("sunflower seeds", "sonnenblumenkerne", "pumpkin seeds", "kürbiskerne"),
    "heavy cream": ("schlagsahne", "sahne", "kochcreme"),
    "sour cream": ("schmand", "saure sahne", "crème fraîche"),
    "buttermilk": ("buttermilch",),
    "ricotta": ("frischkäse", "hüttenkäse"),
    "shallot": ("rote zwiebel", "zwiebel"),
    "red wine vinegar": ("balsamico", "rotweinessig"),
    "white wine vinegar": ("weißweinessig", "weissweinessig"),
    "panko": ("semmelbrösel", "paniermehl"),
    "cilantro": ("koriander", "petersilie"),
    "coriander leaves": ("koriander",),
    "arugula": ("rucola",),
    "rocket": ("rucola",),
    "crème fraîche": ("schmand", "saure sahne"),
    "mascarpone": ("frischkäse",),
    "brown rice": ("naturreis", "vollkornreis"),
    "vegetable stock": ("gemüsebrühe", "gemuesebruehe"),
    "chicken stock": ("hühnerbrühe", "huehnerbruehe"),
    "greek yogurt": ("skyr", "protein joghurt"),
}


def ingredient_search_terms(value: str) -> list[str]:
    """Exact aliases plus a small curated set of substitution search terms."""
    needle = _norm(value)
    terms = set(ingredient_aliases(value))
    for canonical, substitutes in _SUBSTITUTION_GROUPS.items():
        if needle == _norm(canonical):
            terms.update(_norm(term) for term in substitutes)
    return sorted((term for term in terms if term), key=lambda term: (-len(term), term))


def ingredient_product_match_type(ingredient: str, product_name: str) -> str | None:
    """Classify a catalog title as exact, culinary substitute, or no match."""
    title = _norm(product_name)
    if not title:
        return None
    padded_title = " " + title + " "
    exact_terms = ingredient_aliases(ingredient)
    if any((" " + _norm(term) + " ") in padded_title for term in exact_terms):
        return "exact"
    needle = _norm(ingredient)
    for canonical, substitutes in _SUBSTITUTION_GROUPS.items():
        if needle == _norm(canonical):
            if any((" " + _norm(term) + " ") in padded_title for term in substitutes):
                return "substitute"
    return None


def ingredient_substitution_name(ingredient: str, product_name: str) -> str | None:
    """Return the specific curated replacement phrase present in a product title."""
    title = " " + _norm(product_name) + " "
    needle = _norm(ingredient)
    for canonical, substitutes in _SUBSTITUTION_GROUPS.items():
        if needle != _norm(canonical):
            continue
        for substitute in sorted(substitutes, key=lambda value: -len(_norm(value))):
            if (" " + _norm(substitute) + " ") in title:
                labels = {
                    "sonnenblumenkerne": "sunflower seeds",
                    "kürbiskerne": "pumpkin seeds",
                }
                return labels.get(_norm(substitute), substitute)
    return None
