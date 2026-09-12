import re

# Deterministic, token-free English <-> German ingredient aliases for REWE matching.
# Keep canonical recipe ingredients in English; expand only at catalog-search time.
_ALIAS_GROUPS = [
    ("egg", "eggs", "ei", "eier"),
    ("milk", "milch", "vollmilch", "frischmilch"),
    ("butter", "butter"),
    ("cheese", "käse", "kaese"),
    ("cream", "sahne", "schlagsahne", "kochcreme"),
    ("yogurt", "yoghurt", "joghurt"),
    ("greek yogurt", "greek yoghurt", "griechischer joghurt", "griechischer yoghurt"),
    ("quark", "quark", "speisequark"),
    ("mozzarella", "mozzarella"),
    ("parmesan", "parmesan", "parmigiano"),
    ("feta", "feta", "hirtenkäse", "hirtenkaese"),
    ("chicken", "hähnchen", "haehnchen", "huhn", "hühner", "huehner"),
    ("chicken breast", "hähnchenbrust", "haehnchenbrust"),
    ("beef", "rind", "rindfleisch"),
    ("ground beef", "minced beef", "rinderhack", "hackfleisch", "rinderhackfleisch"),
    ("pork", "schwein", "schweinefleisch"),
    ("salmon", "lachs"),
    ("tuna", "thunfisch"),
    ("shrimp", "prawn", "garnele", "garnelen"),
    ("tofu", "tofu"),
    ("bread", "brot"),
    ("toast", "toast", "toastbrot"),
    ("flour", "mehl", "weizenmehl"),
    ("oats", "oat", "haferflocken", "hafer"),
    ("rice", "reis"),
    ("pasta", "nudeln", "pasta"),
    ("spaghetti", "spaghetti"),
    ("noodles", "nudeln"),
    ("couscous", "couscous"),
    ("quinoa", "quinoa"),
    ("potato", "potatoes", "kartoffel", "kartoffeln"),
    ("sweet potato", "sweet potatoes", "süßkartoffel", "süßkartoffeln", "suesskartoffel", "suesskartoffeln"),
    ("tomato", "tomatoes", "tomate", "tomaten"),
    ("cherry tomato", "cherry tomatoes", "cherrytomate", "cherrytomaten"),
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
    ("salt", "salz"),
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
    return re.sub(r"\s+", " ", (value or "").lower().strip())


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
    # If a generated ingredient contains a known phrase, inherit that group's aliases.
    for known, group in _ALIAS_INDEX.items():
        if known in needle or needle in known:
            aliases.update(group)
    return sorted((x for x in aliases if x), key=lambda x: (-len(x), x))
