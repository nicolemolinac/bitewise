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
    ("lamb", "lamm", "lammfleisch"),
    ("cod", "kabeljau", "dorsch"),
    ("trout", "forelle"),
    ("mackerel", "makrele"),
    ("leek", "porree", "lauch"),
    ("celery", "sellerie"),
    ("asparagus", "spargel"),
    ("cabbage", "kohl"),
    ("white cabbage", "weißkohl", "weisskohl"),
    ("red cabbage", "rotkohl"),
    ("kale", "grünkohl", "gruenkohl"),
    ("pumpkin", "kürbis", "kuerbis"),
    ("beetroot", "rote bete", "rote beete"),
    ("fennel", "fenchel"),
    ("radish", "radieschen"),
    ("spring onion", "scallion", "frühlingszwiebel", "fruehlingszwiebel"),
    ("green bean", "green beans", "grüne bohne", "grüne bohnen", "gruene bohne", "gruene bohnen"),
    ("pineapple", "ananas"),
    ("pear", "birne", "birnen"),
    ("peach", "pfirsich", "pfirsiche"),
    ("plum", "pflaume", "pflaumen"),
    ("melon", "melone", "melonen"),
    ("watermelon", "wassermelone", "wassermelonen"),
    ("yeast", "hefe"),
    ("cocoa", "kakao"),
    ("chocolate", "schokolade"),
    ("breadcrumbs", "bread crumbs", "paniermehl", "semmelbrösel", "semmelbroesel"),
    ("sesame", "sesam"),
    ("sesame oil", "sesamöl", "sesamoel"),
    ("oat milk", "hafermilch"),
    ("almond milk", "mandelmilch"),
    ("soy milk", "sojamilch"),
    ("cream cheese", "frischkäse", "frischkaese"),
    ("milk chocolate", "milchschokolade"),
    ("saffron", "safran"),
    ("parsley", "petersilie"),
    ("basil", "basilikum"),
    ("oregano", "oregano"),
    ("thyme", "thymian"),
    ("rosemary", "rosmarin"),
    ("chives", "schnittlauch"),
    ("dill", "dill"),
    ("ginger", "ingwer"),
    ("coriander", "cilantro", "koriander"),
    ("chili", "chilli", "chilischote", "chilischoten"),
    ("wrap", "wraps", "tortilla", "tortillas", "weizentortilla"),
    # Additional common German supermarket names for ingredients in real generated recipes.
    ("arborio rice", "arborio reis", "risottoreis", "risotto reis"),
    ("bagel", "bagel", "bagels"),
    ("balsamic vinegar", "balsamico", "balsamessig", "balsamicoessig"),
    ("black bean", "black beans", "schwarze bohne", "schwarze bohnen"),
    ("beef steak", "rindersteak", "rinder steaks", "rinderhüftsteak", "rinderhueftsteak"),
    ("chicken stock", "hühnerbrühe", "huehnerbruehe", "hühnerfond", "huehnerfond", "geflügelbrühe", "gefluegelbruehe"),
    ("vegetable stock", "gemüsebrühe", "gemuesebruehe", "gemüsefond", "gemuesefond"),
    ("goat cheese", "ziegenkäse", "ziegenkaese", "ziegenfrischkäse", "ziegenfrischkaese"),
    ("halloumi", "halloumi", "grillkäse", "grillkaese"),
    ("granola", "granola", "knuspermüsli", "knuspermuesli"),
    ("green curry paste", "grüne currypaste", "gruene currypaste", "thai curry paste grün", "thai curry paste gruen"),
    ("miso", "miso", "misopaste"),
    ("orzo", "orzo", "reisförmige nudeln", "reisfoermige nudeln"),
    ("passata", "passata", "passierte tomaten"),
    ("rocket", "rucola", "rauke"),
    ("red wine vinegar", "rotweinessig"),
    ("ricotta", "ricotta"),
    ("raisins", "rosinen"),
    ("tagliatelle", "tagliatelle", "bandnudeln"),
    ("flatbread", "fladenbrot", "pita", "pita brot"),
    ("white bean", "white beans", "weiße bohne", "weiße bohnen", "weisse bohne", "weisse bohnen"),
    ("pesto", "pesto", "basilikumpesto"),
    ("tomato passata", "passierte tomaten", "tomatenpassata"),

]


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower().strip())


_ALIAS_INDEX: dict[str, set[str]] = {}
_ALIAS_CANONICAL: dict[str, str] = {}
for group in _ALIAS_GROUPS:
    normalized = {_norm(x) for x in group if _norm(x)}
    canonical = _norm(group[0])
    for term in normalized:
        _ALIAS_INDEX.setdefault(term, set()).update(normalized)
        _ALIAS_CANONICAL.setdefault(term, canonical)


# Irregular English food plurals that cannot be normalized by removing a final "s".
_IRREGULAR_SINGULARS = {
    "leaves": "leaf",
    "loaves": "loaf",
    "halves": "half",
    "knives": "knife",
    # Uncountable ingredient names whose spelling ends in "ses".
    "molasses": "molasses",
}


def _singular_form(value: str) -> str:
    """Conservatively singularize common English plurals without corrupting nouns."""
    if value in _IRREGULAR_SINGULARS:
        return _IRREGULAR_SINGULARS[value]
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("oes") and len(value) > 4:
        return value[:-2]
    # Words ending in these sequences are commonly singular already:
    # hummus, couscous, asparagus, citrus, watercress, molasses.
    if value.endswith(("ss", "us", "is")):
        return value
    if value.endswith("s") and len(value) > 3:
        return value[:-1]
    return value


def canonical_ingredient(value: str) -> str:
    """Return a conservative canonical ingredient label for exact aliases."""
    needle = _norm(value)
    if not needle:
        return ""
    if needle in _ALIAS_CANONICAL:
        return _ALIAS_CANONICAL[needle]
    singular = _singular_form(needle)
    return _ALIAS_CANONICAL.get(singular, singular)


def ingredient_aliases(value: str) -> list[str]:
    """Return deterministic EN/DE search terms for an ingredient, longest first."""
    needle = _norm(value)
    if not needle:
        return []
    aliases = set(_ALIAS_INDEX.get(needle, {needle}))
    aliases.add(needle)
    # Conservative singular/plural fallback for recipe-side English terms.
    singular = _singular_form(needle)
    if singular != needle:
        aliases.add(singular)
    elif not needle.endswith(("s", "ss", "us", "is")):
        aliases.add(needle + "s")
    # If a generated ingredient contains a known phrase, inherit that group's
    # aliases. Match whole words and prefer the most specific phrase: generic
    # "chicken" must not broaden "chicken breast" to unrelated chicken cuts,
    # and "oil" must not broaden "olive oil" to every kind of cooking oil.
    matched = [
        known for known in _ALIAS_INDEX
        if re.search(rf"(?<!\w){re.escape(known)}(?!\w)", needle)
    ]
    specific = [
        known for known in matched
        if not any(
            known != other
            and re.search(rf"(?<!\w){re.escape(known)}(?!\w)", other)
            for other in matched
        )
    ]
    for known in specific:
        aliases.update(_ALIAS_INDEX[known])
    return sorted((x for x in aliases if x), key=lambda x: (-len(x), x))


def ingredient_matches_product(ingredient: str, product_text: str) -> bool:
    """Match a product title to an ingredient without broad substring collisions.

    The most specific known ingredient phrase in the product title wins. This
    prevents generic "oil" from matching olive oil, "milk" from matching
    coconut milk, and "pepper" from matching black pepper. Specific German
    compounds such as "Hähnchenbrustfilet" can match a specific phrase like
    "chicken breast", but not the broader "chicken".
    """
    needle = _norm(ingredient)
    text = _norm(product_text)
    if not needle or not text:
        return False

    aliases = set(ingredient_aliases(needle))
    if not aliases:
        return False

    matched_known = []
    for known in _ALIAS_INDEX:
        exact = re.search(rf"(?<!\w){re.escape(known)}(?!\w)", text)
        compact = known.replace(" ", "")
        # German product names often join a specific cut/type into one word.
        # Permit a suffix only for long, specific aliases, never generic words.
        compound = (
            len(compact) >= 10
            and re.search(rf"(?<!\w){re.escape(compact)}[a-zäöüß]+(?!\w)", text)
        )
        if exact or compound:
            matched_known.append(known)

    if matched_known:
        most_specific = max(matched_known, key=lambda term: (len(term), term))
        return most_specific in aliases

    # Unknown ingredients still get exact phrase matching in the source title.
    return any(
        re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)
        for alias in aliases
    )
