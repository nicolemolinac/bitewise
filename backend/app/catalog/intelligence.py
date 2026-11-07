"""Deterministic product intelligence for the REWE catalog.

This layer classifies catalog products once into a stable culinary vocabulary.
It deliberately does not scrape, call an LLM, or infer nutrition facts.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from ..ingredient_aliases import canonical_ingredient_terms

CLASSIFIER_VERSION = "1.22.0"

@dataclass(frozen=True)
class ProductProfile:
    product_type: str
    culinary_role: str
    dish_families: tuple[str, ...]
    preparation_state: str
    storage_type: str
    convenience_level: int
    is_complete_meal: bool
    confidence: float
    evidence: tuple[str, ...]
    classifier_version: str = CLASSIFIER_VERSION

    def as_dict(self) -> dict:
        value = asdict(self)
        value["dish_families"] = list(self.dish_families)
        value["evidence"] = list(self.evidence)
        return value

def _text(product: dict) -> str:
    # Keep aisle/category metadata separate from product-name evidence.
    # Otherwise a category such as "fertiggerichte-konserven" makes every canned
    # tomato/passata look like a complete meal.
    return " ".join(str(product.get(k) or "") for k in
                    ("name_original", "name_normalized", "translated_name", "brand")).lower()

def classify_product(product: dict) -> ProductProfile:
    """Classify a product by culinary function, not merely supermarket aisle."""
    name = _text(product)
    category = str(product.get("category") or "").lower()
    evidence: list[str] = []
    families: list[str] = []
    product_type, role = "ingredient", "ingredient"
    prep, storage, convenience = "unknown", "unknown", 1
    complete = False
    confidence = 0.58

    frozen = any(x in category or x in name for x in ("tiefkühl", "tiefkuehl", "frozen", "tk-"))
    chilled = any(x in category for x in ("molkerei", "fleisch", "wurst", "käse")) or any(
        x in name for x in ("gekühlt", "frisch", "refrigerated"))
    storage = "frozen" if frozen else ("chilled" if chilled else "ambient")

    # Keep non-food aisles out of culinary matching entirely. These products
    # remain in the catalog for shopping data, but can never become ingredients.
    non_food_categories = {
        "baby-kind", "drogerie-gesundheit", "haus-freizeit",
        "kueche-haushalt", "tierbedarf", "bonus",
    }
    non_food_markers = (
        "windel", "shampoo", "zahnpasta", "toilettenpapier", "katzenstreu",
        "hundefutter", "katzenfutter", "vogelfutter", "waschmittel",
        "spülmittel", "spuelmittel", "wc-reiniger", "badreiniger",
        "waschpulver", "weichspüler", "weichspueler",
    )
    if category in non_food_categories or any(marker in name for marker in non_food_markers):
        return ProductProfile(
            product_type="non_food", culinary_role="non_food",
            dish_families=(), preparation_state="not_applicable",
            storage_type=storage, convenience_level=1, is_complete_meal=False,
            confidence=0.99, evidence=("non-culinary-category-or-title",),
        )

    # Branded recipe-mix sachets and seasoning/topping blends are not the
    # meat, vegetables or complete dishes named in their marketing titles.
    if (
        any(marker in name for marker in (
            "knorr fix", "maggi fix", "maggi food travel fix",
            "ostmann let's do", "ostmann lets do",
            "würzmischung", "wuerzmischung", "gewürzmischung", "gewuerzmischung",
            "würz-mix", "wuerz-mix", "seasoning mix",
        ))
        or ("knorr" in name and "fix" in name)
        or ("maggi" in name and "fix" in name)
    ):
        return ProductProfile(
            product_type="prepared_component", culinary_role="seasoning_mix",
            dish_families=(), preparation_state="ready_to_use",
            storage_type=storage, convenience_level=3, is_complete_meal=False,
            confidence=0.98, evidence=("branded-recipe-mix-or-seasoning",),
        )

    # Bar/bite products are snacks regardless of which REWE aisle they are
    # placed in; their flavor words (e.g. chocolate, almond, cream) are not raw
    # ingredient evidence.
    packaged_snack_markers = (
        "protein bar", "proteinriegel", "protein riegel", "candy bar",
        "energy bar", "snack bar", "müsliriegel", "muesliriegel",
        "oat bar", "fruchtriegel", "fruit bar", "nussriegel",
        "protein bites", "protein bite", "protein balls",
    )
    if any(marker in name for marker in packaged_snack_markers):
        return ProductProfile(
            product_type="snack", culinary_role="snack",
            dish_families=(), preparation_state="ready_to_eat",
            storage_type=storage, convenience_level=1, is_complete_meal=False,
            confidence=0.97, evidence=("packaged-snack-bar-or-bites",),
        )

    # Dairy-aisle beverages should not leak fruit/flavor words into ingredient context.
    dairy_beverage_markers = (
        " ayran ", " kefir ", " drink ", " shake ", " milchshake ",
        " milchmix ", " fruchtbuttermilch ", " iced coffee ",
    )
    if category == "kaese-eier-molkerei" and any(marker in f" {name} " for marker in dairy_beverage_markers):
        return ProductProfile(
            product_type="beverage", culinary_role="beverage",
            dish_families=(), preparation_state="ready_to_drink",
            storage_type=storage, convenience_level=1, is_complete_meal=False,
            confidence=0.94, evidence=("dairy-aisle-beverage",),
        )

    # Drinks and snack foods are edible products, but not interchangeable with
    # raw recipe ingredients merely because a flavor word appears in the title.
    if category == "getraenke-genussmittel" and not any(term in name for term in (
        "wein", "bier", "sake", "mirin",
    )):
        return ProductProfile(
            product_type="beverage", culinary_role="beverage",
            dish_families=(), preparation_state="ready_to_drink",
            storage_type=storage, convenience_level=1, is_complete_meal=False,
            confidence=0.96, evidence=("beverage-aisle-product",),
        )

    if category == "kaffee-tee-kakao" and not any(term in name for term in (
        "backkakao", "kakaopulver", "cocoa powder", "kaffeepulver",
        "espresso pulver", "instant espresso powder",
    )):
        return ProductProfile(
            product_type="beverage", culinary_role="beverage",
            dish_families=(), preparation_state="ready_to_drink_or_brew",
            storage_type=storage, convenience_level=1, is_complete_meal=False,
            confidence=0.94, evidence=("coffee-tea-beverage-product",),
        )

    snack_ingredient_markers = (
        "erdnüsse", "erdnuesse", "mandeln", "walnüsse", "walnuesse",
        "cashewkerne", "pinienkerne", "sonnenblumenkerne", "kürbiskerne",
        "kuerbiskerne", "chiasamen", "chia samen", "backkakao", "kakaopulver",
        "kuvertüre", "kuvertuere", "backschokolade", "schokotropfen",
        "schokodrops", "trockenfrüchte", "trockenfruechte", "rosinen",
        "datteln",
    )
    if category == "suesses-salziges" and not any(term in name for term in snack_ingredient_markers):
        return ProductProfile(
            product_type="snack", culinary_role="snack",
            dish_families=(), preparation_state="ready_to_eat",
            storage_type=storage, convenience_level=1, is_complete_meal=False,
            confidence=0.94, evidence=("snack-confectionery-aisle",),
        )

    # Ready-to-eat desserts and puddings must not satisfy base ingredient searches
    # such as rice, milk, cream, vanilla or fruit.
    if (category == "tiefkuehlkost" and re.search(r"\beis\b", name)) or any(term in name for term in (
        "milchreis", "rice pudding", "reis pudding", "pudding", "dessert",
        "mousse", "eiscreme", "ice cream", "custard", "grießpudding",
        "griesspudding", "sahnepudding", "milchdessert", "kuchen",
        "cake", "cheesecake", "käsekuchen", "kaesekuchen", "brownie",
        "brownies", "sorbet", "gelato", "cookie dough", "protein dessert",
        "protein pudding", "protein mousse", "high protein chocolate",
        "chocolate & topping", "dessert cup",
        "high protein chocolate", "chocolate & topping", "chocolate topping",
        "protein dessert", "protein mousse", "tiramisu", "panna cotta",
        "creme brulee", "crème brûlée", "trifle",
    )) or re.search(r"\btorte\b", name):
        product_type, role, prep, convenience = (
            "prepared_component", "dessert", "ready_to_eat", 4)
        confidence = 0.92
        evidence.append("prepared-dessert-product")

    # Filled Maultaschen are ready-to-cook pasta components, not raw meat,
    # onion or spinach ingredients even when their filling names are in the title.
    if "maultaschen" in name:
        product_type, role, prep, convenience = (
            "prepared_component", "filled_pasta", "ready_to_cook", 4)
        confidence = 0.9
        evidence.append("prepared-filled-pasta")

    # Ready-to-cook filled dumplings and rice snacks are prepared proteins,
    # not raw chicken/meat ingredients despite protein words in their names.
    if any(term in name for term in (
        "gyoza", "mandu", "dumpling", "onigiri",
    )):
        product_type, role, prep, convenience = (
            "prepared_component", "protein", "ready_to_cook", 4)
        confidence = 0.92
        evidence.append("prepared-filled-dumpling-or-rice-snack")

    # Cured, smoked and deli-style meats are ready-to-eat protein components,
    # not raw meat cuts for an exact ingredient match.
    processed_meat_markers = (
        "geräuchert", "geraeuchert", "gepökelt", "gepoekelt",
        "luftgetrocknet", "rohschinken", "prosciutto", "salami",
        "leberwurst", "teewurst", "jagdwurst", "fleischwurst",
        "bierschinken", "schinken", "speck",
    )
    if category == "fleisch-wurst-fisch" and any(marker in name for marker in processed_meat_markers) and not any(
        marker in name for marker in ("bifi", "salami sticks", "salami-sticks", "meat stick", "fleischsnack", "jerky", "knacker", "snack")
    ):
        product_type, role, prep, convenience = (
            "prepared_component", "protein", "ready_to_eat", 4)
        confidence = 0.9
        evidence.append("cured-or-deli-protein-component")

    # Meat sticks and branded snack sausages are snacks, not recipe meat.
    if any(term in name for term in (
        "bifi", "salami sticks", "salami-sticks", "snack salami", "meat stick",
        "fleischsnack", "jerky",
    )):
        product_type, role, prep, convenience = (
            "snack", "snack", "ready_to_eat", 1)
        confidence = 0.95
        evidence.append("meat-snack-product")

    # Prepared soups and salads are shortcut foods, never raw ingredient matches.
    # They are kept distinct from full meals because they can also be sides/components.
    if any(term in name for term in ("suppe", "soup", "cremesuppe", "creamy soup")):
        product_type, role, prep, convenience = (
            "prepared_component", "soup", "ready_to_heat", 4)
        confidence = 0.9
        evidence.append("prepared-soup-product")
    elif any(term in name for term in (
        "nudelsalat", "nudel salat", "kartoffelsalat", "kartoffel salat",
        "eiersalat", "thunfischsalat", "tuna salad", "pasta salad", "bulgursalat", "couscoussalat", "reissalat", "salatschale wakame",
        "krautsalat", "kraut salat",
        "salat mit", "salad with",
    )):
        product_type, role, prep, convenience = (
            "prepared_component", "salad", "ready_to_eat", 4)
        confidence = 0.88
        evidence.append("prepared-salad-product")
    elif any(term in name for term in (
        "chicken nuggets", "hähnchen nuggets", "hahnchen nuggets",
        "fischstäbchen", "fischstaebchen", "fish sticks", "fish nuggets",
        "schnitzel", "frikadelle", "hackbällchen", "hackbaellchen",
        "burger patties", "burger patty", "burger-patty",
    )) or (
        "burger" in name and category == "tiefkuehlkost"
        and not any(term in name for term in ("sauce", "soße", "sosse", "brötchen", "broetchen", "bun", "gurken"))
    ):
        product_type, role, prep, convenience = (
            "prepared_component", "protein", "ready_to_cook_or_heat", 4)
        confidence = 0.9
        evidence.append("prepared-protein-shortcut")

    # Frozen/ready potato sides (fries, wedges, rösti) are shortcuts, not
    # interchangeable with raw potatoes in recipe ingredient matching.
    if any(term in name for term in (
        "pommes frites", "french fries", "potato wedges", "kartoffel wedges",
        "rösti", "rosti", "bratkartoffeln",
    )) and not any(term in name for term in (
        "fix", "gewürz", "gewuerz", "sauce", "soße", "sosse",
        "seasoning", "fruchtgummi",
    )):
        product_type, role, prep, convenience = (
            "prepared_component", "potato_side", "ready_to_heat", 4)
        confidence = 0.92
        evidence.append("prepared-potato-side")

    # Canned/prepared cabbage sides are convenience components, not raw vegetables.
    prepared_cabbage = any(term in name for term in ("rotkohl", "rotkraut", "sauerkraut")) and (
        category == "fertiggerichte-konserven"
        or any(term in name for term in ("tafelfertig", "fix & fertig", "apfelrotkohl", "apfel rotkohl"))
    )
    if prepared_cabbage:
        product_type, role, prep, convenience = (
            "prepared_component", "vegetable", "ready_to_heat", 4)
        confidence = 0.92
        evidence.append("prepared-cabbage-side")

    # Full meals must be recognized before individual components such as pasta or sauce.
    meal_markers = (
        "fertiggericht", "fertigmenü", "fertig menu", "ready meal", "microwave meal",
        "foodmaker", "youcook", "rice bowl", "reis bowl", "bowl mit ", "spaghetti bolognese", "lasagne", "lasagna",
        "pizza ", "curry mit reis", "reisgericht", "nudelgericht", "pasta bolognese", "mahlzeit",
        "chili con carne", "quiche", "ramen", "cup noodles", "asia noodles",
        "instant noodles", "instant ramen", "noodle cup", "tteokbokki", "oyakata",
        "schnitzel mit",
        "eintopf", "stew", "paella", "risotto", "rindergulasch",
        "schweinegulasch", "gulaschgericht", "fertigmahlzeit",
        "kartoffelauflauf", "potato casserole", "bami goreng", "nasi goreng",
        "hühnerfrikassee", "huehnerfrikassee", "frikassee", "gulaschtopf",
        "5 minuten terrine",
    )
    dry_lasagne_sheets = any(term in name for term in ("lasagneplatten", "lasagne platten", "lasagne blätter", "lasagneblaetter"))
    # "Bowl" alone is not proof of a complete meal: REWE also lists toppings,
    # crunchy garnishes and sauces with "bowl" in their title.
    bowl_topping = "bowl topping" in name or "topping bowl" in name
    if bowl_topping and product_type == "ingredient":
        product_type, role, prep, convenience = (
            "prepared_component", "topping", "ready_to_use", 3)
        confidence = 0.9
        evidence.append("prepared-bowl-topping")
    pizza_component = any(term in name for term in (
        "pizzateig", "pizza teig", "pizzagewürz", "pizzagewuerz",
        "pizza gewürz", "pizza gewuerz", "pizzasauce", "pizza sauce",
        "pizza soße", "pizza sosse", "pizzakäse", "pizzakaese",
    ))
    ramen_noodles = any(term in name for term in ("ramen nudeln", "ramen noodles", "ramen noodle"))
    meal_hit = None if dry_lasagne_sheets or bowl_topping or pizza_component or ramen_noodles else next(
        (term for term in meal_markers if term in name), None
    )
    # The REWE aisle also contains canned ingredients and sauces; category alone
    # is not enough evidence that a product is a complete meal.
    category_meal = (
        "fertiggerichte" in category
        and not (bowl_topping or dry_lasagne_sheets or pizza_component or ramen_noodles)
        and any(
            term in name for term in (
                "gericht", "menü", "menu", "bolognese", "lasagne", "lasagna",
                "curry", "pizza", "rice bowl", "reis bowl", "bowl mit ",
            )
        )
    ) or (
        category in {"fertiggerichte-konserven", "tiefkuehlkost"}
        and any(term in name for term in (
            "gulasch", "ravioli", "rinderrouladen", "kohlrouladen",
        ))
    )
    # Frozen skillet meals and composed dishes are complete convenience meals;
    # plain vegetable mixes and individual protein patties remain components.
    frozen_skillet_marker = False
    if frozen and "pfanne" in name and any(term in name for term in (
        "hähnchen", "huhn", "hack", "fisch", "meeresfrüchte", "meeresfruchte",
        "curry", "reis", "nudel", "spätzle", "spaetzle", "gnocchi", "tortellini",
        "bolognese", "paella",
    )):
        frozen_skillet_marker = True
    if frozen_skillet_marker and not meal_hit:
        meal_hit = "composed-frozen-skillet-meal"
    frozen_composed_meal = frozen and (
        any(term in name for term in (
            "bolognese", "red curry", "rotes curry", "hähnchen curry",
            "huhn curry", "paella", "risotto",
        ))
        or (
            any(term in name for term in ("tortellini", "ravioli", "tagliatelle"))
            and any(term in name for term in (
                "käse sahne", "kaese sahne", "käse-sahne", "kaese-sahne",
                "sahnesauce", "sahnesosse",
                "mit blubb", "pilz pfanne", "champignon",
            ))
        )
    ) and not any(term in name for term in (
        "sauce", "soße", "sosse", "gewürz", "gewuerz", "paste",
    ))
    if frozen_composed_meal and not meal_hit:
        meal_hit = "composed-frozen-main-dish"
    if meal_hit or category_meal:
        product_type, role, prep, convenience, complete = (
            "ready_meal", "complete_meal", "ready_to_heat", 5, True)
        confidence = 0.9 if meal_hit else 0.76
        evidence.append(f"complete-meal:{meal_hit or 'catalog-category'}")
        if any(x in name for x in ("lasagne", "lasagna")):
            families.append("lasagna")
        if any(x in name for x in ("bolognese",)):
            families.append("pasta_bolognese")
        if any(x in name for x in ("pasta", "nudel", "ravioli", "tortellini")):
            families.append("pasta")
        if "pizza" in name:
            families.append("pizza")
        if any(term in name for term in ("rice bowl", "reis bowl", "bowl mit ")):
            families.append("bowl")
        if frozen:
            prep = "ready_to_heat"
    else:
        # Preserve high-confidence prepared-food roles assigned above. Generic
        # token rules (e.g. "tomato" in tomato soup) must not overwrite them.
        if product_type == "prepared_component" and role in {"soup", "salad", "dessert", "protein", "potato_side", "filled_pasta", "vegetable", "topping"}:
            pass
        elif product_type == "snack" and role == "snack":
            pass
        # Components are useful shortcuts, but are not complete meals.
        elif any(term in name for term in ("suppe", "soup", "cremesuppe", "cremesoup")):
            product_type, role, prep, convenience = "prepared_component", "soup", "ready_to_heat", 4
            confidence = 0.9
            evidence.append("prepared-soup")
        elif any(term in name for term in (
            "nudelsalat", "kartoffelsalat", "krautsalat", "reissalat",
            "thunfischsalat", "fleischsalat", "eiersalat",
        )):
            product_type, role, prep, convenience = "prepared_component", "salad", "ready_to_eat", 4
            confidence = 0.9
            evidence.append("prepared-salad")
        elif "nugget" in name:
            product_type, role, prep, convenience = "prepared_component", "protein", "ready_to_bake", 4
            confidence = 0.9
            evidence.append("prepared-protein-nuggets")
        elif dry_lasagne_sheets:
            product_type, role, prep, convenience = "ingredient", "starch", "dry", 1
            confidence = 0.94
            evidence.append("dry-lasagne-sheets")
            families.append("lasagna")
        elif any(x in name for x in (
            "passata", "passierte tomaten", "pesto", "tomatensauce", "tomatensosse",
            "sugo", "cooking sauce", "gewürzpaste", "gewuerzpaste",
            "würzpaste", "wuerzpaste", "currypaste", "curry paste",
            "sambal oelek", "miso paste", "pizza sauce", "pizzasauce",
            "teriyaki sauce", "teriyakisauce", "remoulade", "hollandaise",
            "mango chutney", "chili sauce", "ketchup", "soy sauce", "sojasauce", "fish sauce",
        )):
            product_type, role, prep, convenience = "prepared_component", "sauce", "ready_to_use", 4
            confidence = 0.94
            evidence.append("sauce-component")
            families.extend(["pasta", "sauce_based"])
        elif any(x in name for x in ("hähnchen-filetstreifen gebraten", "hähnchenbrust gebraten",
                                     "chicken strips cooked", "gegart", "vorgegart")):
            product_type, role, prep, convenience = "prepared_component", "protein", "ready_to_eat", 4
            confidence = 0.88
            evidence.append("cooked-protein-component")
        elif any(x in name for x in ("nudeln", "pasta", "spaghetti", "penne", "fusilli", "trofie", "tagliatelle", "linguine", "tortellini", "ravioli", "farfalle", "rigatoni", "orzo", "maccheroni", "orecchiette")):
            product_type, role, prep, convenience = "ingredient", "starch", "dry", 1
            confidence = 0.91
            evidence.append("dry-pasta-ingredient")
            families.append("pasta")
        elif any(x in name for x in ("reis", "rice")):
            product_type, role = "ingredient", "starch"
            prep = "ready_to_heat" if any(x in name for x in ("vorgegart", "express", "beutel")) else "dry"
            convenience = 3 if prep == "ready_to_heat" else 1
            confidence = 0.84
            evidence.append("rice-staple")
            families.append("rice_bowl")
        elif any(x in name for x in ("pizzateig", "pizza dough")):
            product_type, role, prep, convenience = "ingredient", "dough", "ready_to_bake", 2
            confidence = 0.88
            evidence.append("pizza-dough")
            families.append("pizza")
        elif any(x in name for x in ("gemüsebrühe", "gemuesebruehe", "hühnerbrühe", "huehnerbruehe", "bouillon", "stock cube", "brühwürfel")):
            product_type, role, prep, convenience = "prepared_component", "broth", "ready_to_use", 3
            confidence = 0.86
            evidence.append("cooking-broth")
        elif any(x in name for x in ("chiliflocken", "chili flocken", "chilipulver", "oregano", "thymian", "basilikum", "rosmarin", "petersilie", "muskat", "pfeffer", "salz", "kräuter", "kraeuter", "paprikapulver", "paprika edelsüß", "paprika edelsuess", "ingwer",
            "five spice", "five-spice", "pizzagewürz", "pizzagewuerz", "pizza gewürz", "pizza gewuerz", "gewürzsalz", "gewuerzsalz",
            "gewürzmischung", "gewuerzmischung", "seasoning mix", "spice mix")):
            product_type, role, prep, convenience = "ingredient", "seasoning", "ready_to_use", 1
            confidence = 0.86
            evidence.append("herb-or-seasoning")
        elif any(x in name for x in ("ricotta", "mozzarella", "parmesan", "parmigiano", "grana padano", "feta")):
            product_type, role, prep, convenience = "ingredient", "cheese", "ready_to_use", 1
            confidence = 0.88
            evidence.append("cheese-ingredient")
        elif any(x in name for x in ("kartoffelsalat", "bratkartoffeln", "vorgekochte kartoffeln", "gekochte kartoffeln", "kartoffelpüree", "kartoffelpueree", "kartoffelbrei", "kartoffelklöße", "kartoffelkloesse")):
            product_type, role, prep, convenience = "prepared_component", "starch", "ready_to_eat", 4
            confidence = 0.84
            evidence.append("prepared-potato-component")
        elif any(x in name for x in ("tofu",)) and any(
            marker in name for marker in (
                "geräuchert", "geraeuchert", "räuchertofu", "raeuchertofu",
                "mariniert", "gewürzt", "gewuerzt", "smoked", "marinated",
            )
        ):
            product_type, role, prep, convenience = "prepared_component", "protein", "ready_to_use", 3
            confidence = 0.86
            evidence.append("seasoned-tofu-component")
        elif any(x in name for x in ("kichererbse", "kichererbsen", "kidneybohnen", "kidney-bohnen", "bohnen", "linsen", "lentils", "chickpeas")) and (
            "konserven" in category or any(marker in name for marker in ("gekocht", "vorgegart", "abgetropft", "ready to eat", "dose"))
        ):
            product_type, role, prep, convenience = "prepared_component", "legume", "ready_to_use", 3
            confidence = 0.82
            evidence.append("cooked-legume-component")
        elif any(x in name for x in ("gemüse", "brokkoli", "spinat", "paprika", "tomaten", "zucchini", "rucola", "salatmischung", "kürbis", "kuerbis", "kaki", "pitahaya", "physalis")):
            product_type, role = "ingredient", "vegetable"
            prep = "frozen" if frozen else "raw"
            convenience = 2 if frozen else 1
            confidence = 0.72
            evidence.append("vegetable-ingredient")
        elif any(x in name for x in ("hähnchen", "huhn", "chicken", "lachs", "fisch", "tofu", "hackfleisch", "shrimp", "prawn", "garnele", "garnelen")):
            product_type, role, prep = "ingredient", "protein", "raw"
            confidence = 0.76
            evidence.append("protein-ingredient")

    # When the deterministic rules have no specific profile, use the canonical
    # ingredient ontology to assign a useful culinary role. This only runs after
    # snack, beverage, dessert, prepared-meal and component rules above.
    if product_type == "ingredient" and confidence <= 0.58:
        canonical_terms = set(canonical_ingredient_terms(name))
        role_groups = {
            "protein": {
                "chicken", "chicken breast", "beef", "ground beef", "pork",
                "duck", "goose", "lamb", "wild boar", "tempeh", "seitan",
                "plant based mince", "cod", "pollock", "mackerel", "trout",
                "sea bream", "octopus", "surimi", "salmon", "tuna", "shrimp",
                "tofu", "turkey", "ham", "sausage", "meatballs", "kasseler",
                "liver sausage", "veal", "venison", "herring", "anchovy",
                "mussels", "crab", "prawns", "prosciutto", "smoked salmon",
                "smoked trout", "caviar",
            },
            "cheese": {
                "cheese", "mozzarella", "parmesan", "feta", "provolone",
                "berg cheese", "camembert", "cream cheese", "cream cheese spread",
                "cottage cheese", "blue cheese", "grana padano", "gouda",
                "cheddar", "emmental", "halloumi", "burrata", "manchego",
                "limburger", "brie",
            },
            "vegetable": {
                "kale", "brussels sprouts", "pumpkin",
                "green beans", "red cabbage", "leek", "parsnip", "chicory",
                "fennel", "romaine lettuce", "iceberg lettuce", "lamb's lettuce",
                "oyster mushroom", "green onion", "spring onion", "celery",
                "celeriac", "potato", "sweet potato", "tomato", "cherry tomato",
                "cucumber", "onion", "red onion", "garlic", "carrot",
                "bell pepper", "zucchini", "eggplant", "broccoli", "cauliflower",
                "spinach", "lettuce", "mushroom", "avocado", "ginger", "corn",
                "beetroot", "olive", "gherkin", "artichoke", "asparagus",
                "radish", "kohlrabi", "cabbage", "rutabaga", "arugula",
                "garden cress", "chanterelle", "sugar snap peas", "bean sprouts",
                "bamboo shoots", "sauerkraut",
            },
            "starch": {
                "pasta", "tagliatelle", "linguine", "tortellini", "penne", "potato", "sweet potato",
                "lasagne sheets", "trofie pasta", "spaghetti", "noodles",
                "couscous", "rice", "rice noodles", "gnocchi", "bread",
                "bread roll", "rye bread", "sourdough bread", "flour", "oats",
                "semolina", "rye flour", "spelt", "bulgur", "buckwheat",
                "quinoa", "polenta", "potato puree", "potato dumpling",
            },
            "seasoning": {
                "basil", "oregano", "thyme", "rosemary", "parsley", "chives",
                "ginger", "dill", "sage", "chili flakes", "chili powder",
                "nutmeg", "italian seasoning", "salt", "black pepper",
                "paprika powder", "cinnamon", "vanilla", "coriander", "mint",
                "savory", "five spice",
            },
            "sauce": {
                "tomato passata", "pesto", "curry paste", "miso paste",
                "fish sauce", "rice vinegar", "mango chutney", "chili sauce",
                "hummus", "tahini", "mayonnaise", "soy sauce", "tomato sauce",
                "tomato paste", "coconut milk", "apple cider vinegar",
                "remoulade", "hollandaise sauce", "pasta sauce",
            },
            "legume": {
                "chickpea", "bean", "kidney beans", "lentil", "peas",
                "edamame", "soybean", "falafel",
            },
        }
        inferred_role = next(
            (candidate_role for candidate_role, terms in role_groups.items()
             if canonical_terms.intersection(terms)),
            "ingredient",
        )
        role = inferred_role
        confidence = 0.78
        evidence.append("canonical-ingredient-semantic-profile")

    if not families:
        families = []
    # Avoid implying stock availability from category or storage classification.
    return ProductProfile(
        product_type=product_type, culinary_role=role,
        dish_families=tuple(dict.fromkeys(families)),
        preparation_state=prep, storage_type=storage,
        convenience_level=convenience, is_complete_meal=complete,
        confidence=confidence, evidence=tuple(evidence),
    )

def persist_product_profile(db, product, profile: ProductProfile | None = None):
    """Upsert only the intelligence row; never mutates catalog or image fields."""
    from ..database import ProductIntelligence
    profile = profile or classify_product({
        "name_original": product.name_original,
        "name_normalized": product.name_normalized,
        "translated_name": product.translated_name,
        "brand": product.brand,
        "category": product.category,
    })
    row = db.query(ProductIntelligence).filter_by(product_id=product.id).first()
    payload = profile.as_dict()
    values = {
        "product_type": profile.product_type,
        "culinary_role": profile.culinary_role,
        "dish_families_json": json.dumps(payload["dish_families"]),
        "preparation_state": profile.preparation_state,
        "storage_type": profile.storage_type,
        "convenience_level": profile.convenience_level,
        "is_complete_meal": profile.is_complete_meal,
        "confidence": profile.confidence,
        "evidence_json": json.dumps(payload["evidence"]),
        "classifier_version": profile.classifier_version,
        "classified_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    if row is None:
        row = ProductIntelligence(product_id=product.id, **values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row
