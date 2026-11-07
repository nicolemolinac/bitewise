"""Deterministic product intelligence for the REWE catalog.

This layer classifies catalog products once into a stable culinary vocabulary.
It deliberately does not scrape, call an LLM, or infer nutrition facts.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

CLASSIFIER_VERSION = "1.1.0"

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

    # Full meals must be recognized before individual components such as pasta or sauce.
    meal_markers = (
        "fertiggericht", "fertigmenü", "fertig menu", "ready meal", "microwave meal",
        "foodmaker", "youcook", "rice bowl", "reis bowl", "bowl mit ", "spaghetti bolognese", "lasagne", "lasagna",
        "pizza ", "curry mit reis", "reisgericht", "nudelgericht", "pasta bolognese", "mahlzeit",
        "chili con carne", "quiche", "ramen", "nudelsuppe", "schnitzel mit",
    )
    dry_lasagne_sheets = any(term in name for term in ("lasagneplatten", "lasagne platten", "lasagne blätter", "lasagneblaetter"))
    # "Bowl" alone is not proof of a complete meal: REWE also lists toppings,
    # crunchy garnishes and sauces with "bowl" in their title.
    bowl_topping = "bowl topping" in name or "topping bowl" in name
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
    )
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
        # Components are useful shortcuts, but are not complete meals.
        if dry_lasagne_sheets:
            product_type, role, prep, convenience = "ingredient", "starch", "dry", 1
            confidence = 0.94
            evidence.append("dry-lasagne-sheets")
            families.append("lasagna")
        elif any(x in name for x in ("passata", "passierte tomaten", "pesto", "tomatensauce", "tomatensosse", "sugo", "cooking sauce")):
            product_type, role, prep, convenience = "prepared_component", "sauce", "ready_to_use", 4
            confidence = 0.94
            evidence.append("sauce-component")
            families.extend(["pasta", "sauce_based"])
        elif any(x in name for x in ("hähnchen-filetstreifen gebraten", "hähnchenbrust gebraten",
                                     "chicken strips cooked", "gegart", "vorgegart")):
            product_type, role, prep, convenience = "prepared_component", "protein", "ready_to_eat", 4
            confidence = 0.88
            evidence.append("cooked-protein-component")
        elif any(x in name for x in ("nudeln", "pasta", "spaghetti", "penne", "fusilli", "trofie", "tagliatelle", "linguine", "tortellini", "ravioli")):
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
        elif any(x in name for x in ("chiliflocken", "chili flocken", "chilipulver", "oregano", "thymian", "basilikum", "rosmarin", "petersilie", "muskat", "pfeffer", "salz", "kräuter", "kraeuter", "paprikapulver", "paprika edelsüß", "paprika edelsuess", "ingwer")):
            product_type, role, prep, convenience = "ingredient", "seasoning", "ready_to_use", 1
            confidence = 0.86
            evidence.append("herb-or-seasoning")
        elif any(x in name for x in ("ricotta", "mozzarella", "parmesan", "parmigiano", "grana padano", "feta")):
            product_type, role, prep, convenience = "ingredient", "cheese", "ready_to_use", 1
            confidence = 0.88
            evidence.append("cheese-ingredient")
        elif any(x in name for x in ("kartoffelsalat", "bratkartoffeln", "vorgekochte kartoffeln", "gekochte kartoffeln")):
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
        elif any(x in name for x in ("gemüse", "brokkoli", "spinat", "paprika", "tomaten", "zucchini")):
            product_type, role = "ingredient", "vegetable"
            prep = "frozen" if frozen else "raw"
            convenience = 2 if frozen else 1
            confidence = 0.72
            evidence.append("vegetable-ingredient")
        elif any(x in name for x in ("hähnchen", "huhn", "chicken", "lachs", "fisch", "tofu", "hackfleisch", "shrimp", "prawn", "garnele", "garnelen")):
            product_type, role, prep = "ingredient", "protein", "raw"
            confidence = 0.76
            evidence.append("protein-ingredient")

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
