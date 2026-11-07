import re
import unicodedata

# Deterministic, token-free English <-> German ingredient aliases for REWE matching.
# Keep canonical recipe ingredients in English; expand only at catalog-search time.
_ALIAS_GROUPS = [
    ("egg", "eggs", "ei", "eier"),
    ("chocolate", "schokolade", "schokoladen", "chocolate", "chocolates", "backschokolade", "kuvertüre", "kuvertuere", "schokotropfen", "schokodrops"),
    ("cocoa powder", "kakaopulver", "backkakao", "cocoa powder", "cacao powder"),
    ("milk", "milch", "vollmilch", "frischmilch"),
    ("butter", "butter", "markenbutter", "süßrahmbutter", "suessrahmbutter"),
    ("cheese", "käse", "kaese"),
    ("cream", "sahne", "schlagsahne", "kochcreme", "kochsahne"),
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
    ("pasta", "nudeln", "pasta", "fadennudeln", "spiralen", "maccaroni", "makkaroni"),
    ("tagliatelle", "tagliatelle", "bandnudeln"),
    ("pizza dough", "pizzateig"),
    ("linguine", "linguine"),
    ("tortellini", "tortellini"),
    ("penne", "penne"),
    ("lasagne sheets", "lasagneplatten", "lasagne platten", "lasagneblätter", "lasagneblaetter"),
    ("trofie pasta", "trofie"),
    ("fresh basil pesto", "basil pesto", "pesto alla genovese", "pesto genovese", "basilikum pesto", "basilikum-pesto"),
    ("ricotta", "ricotta"),
    ("basil", "basil", "basilikum"),
    ("oregano", "oregano"),
    ("thyme", "thyme", "thymian"),
    ("rosemary", "rosemary", "rosmarin"),
    ("parsley", "parsley", "petersilie"),
    ("chives", "schnittlauch"),
    ("ginger", "ginger", "ingwer"),
    ("dill", "dill"),
    ("sage", "salbei"),
    ("chili flakes", "chiliflocken", "chili flocken", "chiliflocke", "peperoncino"),
    ("chili powder", "chilipulver"),
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
    ("spring onion", "frühlingszwiebel", "fruehlingszwiebel", "frühlingszwiebeln", "fruehlingszwiebeln", "zwiebelgrün", "zwiebelgruen"),
    ("sesame seeds", "sesam", "sesamsamen", "sesamkörner", "sesamkoerner", "sesame seeds"),
    ("celery", "sellerie", "stangensellerie", "knollensellerie", "staudensellerie"),
    ("quinoa", "quinoa"),
    ("potato", "potatoes", "kartoffel", "kartoffeln"),
    ("sweet potato", "sweet potatoes", "süßkartoffel", "süßkartoffeln", "suesskartoffel", "suesskartoffeln"),
    ("tomato", "tomatoes", "tomate", "tomaten", "rispentomate", "rispentomaten"),
    ("cherry tomato", "cherry tomatoes", "cherrytomate", "cherrytomaten", "kirschtomate", "kirschtomaten", "cocktailtomate", "cocktailtomaten", "datteltomate", "datteltomaten"),
    ("cucumber", "gurke", "salatgurke"),
    ("onion", "onions", "zwiebel", "zwiebeln"),
    ("red onion", "rote zwiebel", "rote zwiebeln", "zwiebel rot", "zwiebeln rot", "rote speisezwiebel", "rote speisezwiebeln"),
    ("mustard", "senf", "senfkörner", "senfkoerner"),
    ("garlic", "knoblauch"),
    ("carrot", "carrots", "karotte", "karotten", "möhre", "möhren", "moehre", "moehren"),
    ("bell pepper", "pepper", "paprika"),
    ("zucchini", "courgette", "zucchini"),
    ("eggplant", "aubergine"),
    ("broccoli", "brokkoli"),
    ("cauliflower", "blumenkohl"),
    ("spinach", "spinat", "blattspinat"),
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
    ("paprika powder", "paprikapulver", "paprika edelsüß", "paprika edelsuess", "paprika süß", "paprika suess", "edelsüß paprika", "edelsuess paprika"),
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
    # Common REWE catalog compounds that were missing from the original vocabulary.
    ("salami", "salami", "ringsalami", "salami sticks", "salami-sticks"),
    ("caviar", "kaviar", "caviar"),
    ("oyster mushroom", "austernpilz", "austernpilze"),
    ("spinach", "babyspinat"),
    ("pineapple", "ananas"),
    ("kiwi", "kiwi", "kiwis", "kiwi gold"),
    ("kefir", "kefir"),
    ("ayran", "ayran"),
    ("grana padano", "grana padano"),
    ("gouda", "gouda", "goudakäse", "goudakaese"),
    ("cheddar", "cheddar", "cheddarkäse", "cheddarkaese"),
    ("cream cheese", "frischkäse", "frischkaese", "schmelzkäse", "schmelzkaese"),
    ("bulgur", "bulgur"),
    ("buckwheat", "buchweizen"),
    ("agave syrup", "agavendicksaft"),
    ("rapeseed oil", "rapsöl", "rapsoel", "rapsöl spray", "rapsoel spray"),
    ("coconut oil", "kokosöl", "kokosoel"),
    ("apple cider vinegar", "apfelessig"),
    ("salad greens", "microgreens", "micro green"),
    ("pasta", "buchstabennudeln", "müschelchen", "mueschelchen"),
    ("ham", "bauernschinken", "kochschinken", "serranoschinken", "schwarzwälder schinken"),
    ("turkey", "puten", "putenfilet", "puten filet", "putenfiletstreifen", "puten filetstreifen"),
    ("herring", "hering", "heringe", "bratheringe", "hering filets"),
    ("beetroot", "rote bete", "rote bete", "rote bete"),
    ("olive", "olive", "oliven", "oliven ohne stein"),
    ("gherkin", "cornichons", "gewürzgurken", "gewuerzgurken"),
    ("falafel", "falafel"),
    ("chia seeds", "chia samen", "chiasamen"),
    ("flaxseed oil", "leinöl", "leinoel"),
    ("sesame paste", "tahin", "tahini", "sesammus"),
    ("mayonnaise", "mayonnaise", "mayo", "mayoo"),
    ("spelt", "dinkel", "dinkelmehl"),
    ("tomato", "tomatenstückenatur", "tomatenstücke", "tomatenstuecke"),
    ("chicken", "hühneraufstrich", "huehneraufstrich"),
    ("sausage", "chorizo"),
    ("rapeseed oil", "albaöl", "albaoel", "bratöl", "bratoel", "backöl", "backoel"),
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


def canonical_ingredient_terms(product_name: str) -> list[str]:
    """Extract known canonical ingredient names from a real catalog product title.

    Product.ingredient in the imported REWE snapshot is often just a normalized
    copy of the SKU title, not a reliable ingredient taxonomy. This function
    derives only known ingredient concepts from the actual product name.
    """
    title = " " + _norm(product_name) + " "
    hits = []
    for group in _ALIAS_GROUPS:
        canonical = _norm(group[0])
        matched = [
            _norm(alias) for alias in group
            if (" " + _norm(alias) + " ") in title
        ]
        if matched:
            hits.append((max(len(term.split()) for term in matched), max(map(len, matched)), canonical))
    hits.sort(key=lambda item: (-item[0], -item[1], item[2]))
    selected = []
    for _words, _chars, canonical in hits:
        if canonical not in selected:
            selected.append(canonical)
    return selected


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


def ingredient_product_match_type(
    ingredient: str, product_name: str, category: str | None = None
) -> str | None:
    """Classify a catalog title as exact, culinary substitute, or no match.

    A title mentioning an ingredient is not enough: finished drinks, snacks and
    confectionery must not masquerade as cooking ingredients (e.g. ginger juice
    for fresh ginger or milk chocolate for milk).
    """
    title = _norm(product_name)
    if not title:
        return None
    padded_title = " " + title + " "
    exact_terms = ingredient_aliases(ingredient)
    needle = _norm(ingredient)
    category_key = _norm(category or "")

    baking_chocolate_markers = (
        " backschokolade ", " kuvertüre ", " kuvertuere ",
        " schokotropfen ", " schokodrops ", " kakaopulver ",
        " backkakao ", " cocoa powder ", " cacao powder ",
    )
    is_baking_chocolate = any(marker in padded_title for marker in baking_chocolate_markers)

    beverage_markers = (
        " saft ", " juice ", " limonade ", " getraenk ", " drink ",
        " cola ", " eistee ", " energy drink ", " smoothie ", " nektar ",
        " bier ", " wein ", " sekt ", " prosecco ", " wasser ",
    )
    title_is_beverage = (
        any(marker in padded_title for marker in beverage_markers)
        or (
            category_key in {"getraenke genussmittel", "kaffee tee kakao"}
            and not (needle == "chocolate" and is_baking_chocolate)
        )
    )
    request_is_beverage = any(
        marker.strip() in needle.split() for marker in beverage_markers
    ) or any(term in needle.split() for term in (
        "wine", "beer", "juice", "smoothie", "syrup", "coffee", "tea",
        "cocoa", "cacao", "sake", "mirin",
    ))
    # Keep explicit recipe liquids (e.g. white wine or orange juice) searchable,
    # but never substitute a drink that merely contains a fruit/herb word.
    if title_is_beverage and not request_is_beverage:
        return None

    finished_food_markers = (
        " bonbon ", " candy ", " praline ", " pralinen ",
        " schokoriegel ", " chocolate bar ", " candy bar ", " chips ", " cracker ",
        " crackers ", " keks ", " kekse ", " cookie ", " cookies ",
        " biscuit ", " biscuits ", " popcorn ", " kaugummi ", " chewing gum ",
        " jelly bean ", " waffel ", " wafers ", " tiramisu ", " pudding ",
        " mousse ", " dessert ", " ice cream ", " eiscreme ", " milchreis ",
        " cheesecake ", " käsekuchen ", " kaesekuchen ",
    )
    title_is_finished_food = (
        any(marker in padded_title for marker in finished_food_markers)
        or (
            any(term in title for term in (
                "schokolade", "schokoladen", "chocolate", "chocolates",
                "schokoriegel", "chocolate bar",
            ))
            and not is_baking_chocolate
        )
    )
    request_is_finished_food = any(
        marker.strip() in needle.split() for marker in finished_food_markers
    )
    if title_is_finished_food and not request_is_finished_food:
        return None

    # A snack mix or seasoned nut product is not an exact substitute for its
    # individual ingredient, even if the title contains that ingredient.
    if any(marker in padded_title for marker in (
        " nuss mix ", " nut mix ", " studentenfutter ", " trail mix ",
    )):
        return None

    # Paprika is ambiguous in German: in the spice aisle it usually means
    # ground paprika, not a fresh bell pepper.
    if needle == "bell pepper" and category_key == "oele sossen gewuerze":
        return None
    if needle == "bell pepper" and any(marker in padded_title for marker in (
        " paprika pulver ", " paprikapulver ", " paprika edelsuess ",
        " paprika edelsüß ", " paprika gewuerz ", " paprika gewürz ",
        " paprika spice ", " paprika powder ",
    )):
        return None

    # Honey-mustard sauces, dressings, pickles and prepared dishes contain
    # mustard as a flavor, not as a usable mustard condiment ingredient.
    if needle == "mustard" and (
        any(marker in padded_title for marker in (
            " honey mustard sauce ", " mustard sauce ", " senfsauce ",
            " senf sauce ", " senf dressing ", " senfgurken ",
            " senfgurke ", " senf dill sauce ", " honig senf sauce ",
            " senf eier ",
        ))
        or (
            any(term in padded_title for term in (" senf ", " mustard "))
            and any(marker in title for marker in (
                "schlemmerfilet", "filet", "fisch", "fish", "lachs",
                "salmon", "garnelen", "shrimp",
            ))
        )
    ):
        return None

    # Frozen Schlemmerfilet products are prepared fish portions. Their toppings
    # (broccoli, spinach, mustard, almonds, cheese) are not separate ingredients.
    if "schlemmerfilet" in title:
        return "substitute" if needle in {"fish", "fisch", "white fish"} else None

    # Descriptive claims are not ingredient evidence. In particular, sugar-free
    # drinks contain the word "sugar" but are not a source of sugar.
    if needle == "sugar" and any(marker in padded_title for marker in (
        " zero sugar ", " sugar free ", " sugar-free ", " zuckerfrei ",
        " ohne zucker ", " ohne zugesetzten zucker ", " no added sugar ",
    )):
        return None

    # Tomato sauces/pastes are useful substitutions, not exact fresh-tomato SKUs.
    if needle == "tomato" and any(marker in padded_title for marker in (
        " ketchup ", " passata ", " passierte tomaten ", " tomatenmark ",
        " tomato paste ", " tomatensauce ", " tomatensoße ", " tomatensosse ",
        " tomato sauce ",
    )):
        if " ketchup " in padded_title:
            return None
        return "substitute"

    if any((" " + _norm(term) + " ") in padded_title for term in exact_terms):
        return "exact"
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
