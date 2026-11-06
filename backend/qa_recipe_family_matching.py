"""Intensive recipe-family, convenience-variant and basket QA against the full REWE snapshot.

Run from backend/: python qa_recipe_family_matching.py
Uses a disposable SQLite DB imported from the committed catalog snapshot.
No Gemini API calls, live REWE calls, scraper, image process or user DB are touched.
"""
import os
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-recipe-matrix-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "rewe.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

from app.database import Product, SessionLocal
# Import the production entrypoint first: it installs the strict multilingual
# CatalogAdapter used by app.server:app and deliberately disables demo fallbacks.
import app.server  # noqa: F401
from app.main import CatalogAdapter
from app.catalog.intelligence import classify_product
from app.ingredient_aliases import ingredient_product_match_type
from app.shopping.optimizer import build_basket, consolidate


# 20 distinct recipes: familiar weeknight dishes, comfort food, seafood,
# vegetarian meals, international food and breakfast.
RECIPES = {
    "Creamy mushroom tagliatelle": [
        "tagliatelle", "mushroom", "cream", "garlic", "parmesan",
        "thyme", "parsley", "butter", "black pepper", "salt",
    ],
    "Pasta arrabbiata": [
        "penne", "tomato passata", "garlic", "chili flakes",
        "oregano", "parsley", "olive oil", "parmesan",
    ],
    "Spinach ricotta tortellini": [
        "tortellini", "spinach", "ricotta", "garlic", "cream",
        "nutmeg", "parmesan",
    ],
    "Creamy carbonara": [
        "spaghetti", "eggs", "parmesan", "bacon", "black pepper", "olive oil",
    ],
    "Lasagna": [
        "lasagne sheets", "ground beef", "onion", "garlic", "tomato passata",
        "tomato paste", "vegetable broth", "milk", "butter", "flour",
        "parmesan", "oregano", "nutmeg",
    ],
    "Pizza": [
        "pizza dough", "mozzarella", "tomato sauce", "basil", "oregano",
        "mushroom", "olive oil",
    ],
    "Garlic shrimp pasta": [
        "shrimp", "tagliatelle", "garlic", "lemon", "parsley",
        "chili flakes", "butter", "olive oil",
    ],
    "Creamy salmon spinach rice": [
        "salmon", "spinach", "rice", "cream", "dill", "lemon",
        "garlic", "black pepper",
    ],
    "Chicken pesto pasta": [
        "chicken breast", "pasta", "pesto", "parmesan",
        "cherry tomato", "olive oil", "garlic", "basil",
    ],
    "Creamy chicken mushroom rice": [
        "chicken breast", "rice", "mushroom", "cream", "onion",
        "garlic", "chicken broth", "thyme", "parsley",
    ],
    "Beef tacos": [
        "ground beef", "tortilla", "tomato", "lettuce", "onion",
        "garlic", "paprika powder", "lime", "yogurt", "chili flakes",
    ],
    "Chicken fajita rice bowls": [
        "chicken breast", "rice", "bell pepper", "onion", "garlic",
        "tomato", "lime", "yogurt", "chili flakes", "olive oil",
    ],
    "Greek chicken bowls": [
        "chicken breast", "rice", "cucumber", "tomato", "red onion",
        "feta", "greek yogurt", "lemon", "garlic", "oregano",
    ],
    "Coconut chicken curry": [
        "chicken breast", "coconut milk", "rice", "bell pepper",
        "onion", "garlic", "ginger", "soy sauce", "lime", "chili flakes",
    ],
    "Teriyaki salmon rice": [
        "salmon", "rice", "soy sauce", "honey", "ginger",
        "garlic", "lime",
    ],
    "Lentil bolognese": [
        "lentil", "spaghetti", "tomato passata", "tomato paste",
        "onion", "garlic", "carrot", "olive oil", "oregano", "basil",
    ],
    "Tuna tomato pasta": [
        "tuna", "spaghetti", "tomato passata", "olive oil",
        "garlic", "lemon", "parsley", "chili flakes",
    ],
    "Potato gratin": [
        "potato", "cream", "milk", "butter", "garlic",
        "parmesan", "nutmeg", "black pepper", "salt",
    ],
    "Shakshuka": [
        "eggs", "tomato", "bell pepper", "onion", "garlic",
        "tomato paste", "paprika powder", "chili flakes", "parsley",
    ],
    "Banana oat pancakes": [
        "banana", "eggs", "milk", "flour", "baking powder",
        "cinnamon", "yogurt", "honey",
    ],
}

# These are not new AI-generated recipes. They are deterministic ingredient
# substitutions used to QA the "middle shortcut" route: keep the dish recognizable
# while replacing selected prep work with a genuine REWE component.
MIDDLE_SHORTCUTS = {
    "Creamy mushroom tagliatelle": ["tagliatelle", "mushroom", "pesto", "cream", "parmesan"],
    "Pasta arrabbiata": ["penne", "tomato sauce", "pesto", "chili flakes", "parmesan"],
    "Spinach ricotta tortellini": ["tortellini", "spinach", "ricotta", "cream"],
    "Lasagna": ["lasagne sheets", "tomato sauce", "ground beef", "mozzarella"],
    "Pizza": ["pizza dough", "tomato sauce", "mozzarella", "mushroom"],
    "Chicken pesto pasta": ["pasta", "pesto", "parmesan", "chicken breast"],
    "Creamy chicken mushroom rice": ["rice", "mushroom", "cream", "chicken breast"],
    "Chicken fajita rice bowls": ["rice", "bell pepper", "chicken breast", "tomato sauce"],
    "Greek chicken bowls": ["rice", "feta", "greek yogurt", "cucumber", "chicken breast"],
    "Coconut chicken curry": ["rice", "coconut milk", "chicken breast", "soy sauce"],
    "Lentil bolognese": ["spaghetti", "tomato sauce", "lentil", "parmesan"],
    "Tuna tomato pasta": ["spaghetti", "tomato sauce", "tuna", "olive oil"],
    "Shakshuka": ["eggs", "tomato passata", "bell pepper", "feta"],
}

READY_MEAL_FAMILIES = {
    "Lasagna": ("lasagne", "lasagna"),
    "Pizza": ("pizza",),
    "Creamy chicken mushroom rice": ("chicken", "reis", "rice", "bowl"),
    "Coconut chicken curry": ("curry",),
    "Lentil bolognese": ("bolognese",),
    "Potato gratin": ("gratin", "auflauf"),
}


def _recipe_meal(name, ingredients):
    return {
        "id": "qa-" + str(abs(hash(name))),
        "name": name,
        "base_servings": 2,
        "ingredients": [[ingredient, 100, "g"] for ingredient in ingredients],
    }


def _product_title(product):
    return " ".join(str(product.get(key) or "") for key in (
        "name_original", "name_normalized", "translated_name", "name"
    ))


def main():
    db = SessionLocal()
    try:
        catalog_count = db.query(Product).filter(Product.supermarket == "REWE").count()
        assert catalog_count >= 1000, f"Expected full REWE snapshot, got {catalog_count}"
        adapter = CatalogAdapter(db)

        base_total = base_matched = 0
        base_missing = {}
        base_rows = {}
        for recipe, ingredients in RECIPES.items():
            rows = {}
            for ingredient in ingredients:
                base_total += 1
                products = adapter.search(ingredient)
                valid = [
                    product for product in products
                    if ingredient_product_match_type(ingredient, _product_title(product))
                ]
                rows[ingredient] = valid
                if valid:
                    base_matched += 1
                else:
                    base_missing.setdefault(recipe, []).append(ingredient)
            base_rows[recipe] = rows

        base_coverage = base_matched / max(base_total, 1)
        print(f"BASE RECIPES: {len(RECIPES)} dishes; {base_matched}/{base_total} ingredients matched ({base_coverage:.1%})")
        for recipe, missing in base_missing.items():
            print(f"  BASE MISSING — {recipe}: {', '.join(missing)}")
        assert base_coverage >= 0.80, f"Base recipe matching below 80%: {base_coverage:.1%}"

        middle_total = middle_matched = 0
        middle_missing = {}
        for recipe, ingredients in MIDDLE_SHORTCUTS.items():
            for ingredient in ingredients:
                middle_total += 1
                if adapter.search(ingredient):
                    middle_matched += 1
                else:
                    middle_missing.setdefault(recipe, []).append(ingredient)
        middle_coverage = middle_matched / max(middle_total, 1)
        print(f"MIDDLE SHORTCUTS: {middle_matched}/{middle_total} component ingredients matched ({middle_coverage:.1%})")
        for recipe, missing in middle_missing.items():
            print(f"  SHORTCUT MISSING — {recipe}: {', '.join(missing)}")
        assert middle_coverage >= 0.75, f"Middle-shortcut ingredient matching below 75%: {middle_coverage:.1%}"

        # Every available ready-meal candidate must really be a complete meal.
        # A component such as passata, dry pasta or lasagne sheets is never enough.
        ready_candidates = 0
        for recipe, terms in READY_MEAL_FAMILIES.items():
            rows = (
                db.query(Product)
                .filter(Product.supermarket == "REWE", Product.price.isnot(None), Product.price > 0)
                .all()
            )
            hits = []
            for product in rows:
                title = _product_title({
                    "name_original": product.name_original,
                    "name_normalized": product.name_normalized,
                    "translated_name": product.translated_name,
                }).lower()
                if not any(term in title for term in terms):
                    continue
                profile = classify_product({
                    "name_original": product.name_original,
                    "name_normalized": product.name_normalized,
                    "translated_name": product.translated_name,
                    "category": product.category,
                    "brand": product.brand,
                })
                if profile.is_complete_meal:
                    hits.append(product)
            ready_candidates += len(hits)
            print(f"  READY-MEAL CANDIDATES — {recipe}: {len(hits)} verified complete meals")
        print(f"READY-MEAL CHECK: {ready_candidates} classified complete-meal candidates; components excluded")

        # Basket QA: test budget, balanced and premium strategies over every recipe.
        # The optimizer must never choose a zero/negative-price or unavailable SKU,
        # and must preserve package count, checkout cost and consumed-cost semantics.
        strategies = ("maximum-savings", "best-value", "premium", "plan-efficiency")
        basket_checks = 0
        basket_unmatched = {}
        strategy_totals = {strategy: 0.0 for strategy in strategies}
        for recipe, ingredients in RECIPES.items():
            meal = _recipe_meal(recipe, ingredients)
            requirements = consolidate([meal], {meal["id"]: 2})
            for strategy in strategies:
                basket = build_basket(requirements, adapter, strategy)
                assert len(basket) == len(requirements), f"{recipe}/{strategy}: ingredient rows were lost"
                for row in basket:
                    basket_checks += 1
                    product = row.get("product")
                    if row["match_status"] == "unmatched":
                        basket_unmatched.setdefault(recipe, []).append(row["ingredient"])
                        assert product is None
                        continue
                    if row["match_status"] == "covered":
                        continue
                    assert product is not None, f"{recipe}/{strategy}/{row['ingredient']}: matched without product"
                    assert float(product.get("price") or 0) > 0, f"{recipe}/{strategy}: invalid price"
                    assert str(product.get("availability") or "unknown").lower() not in {
                        "unavailable", "out_of_stock", "not_available", "discontinued"
                    }, f"{recipe}/{strategy}: unavailable product selected"
                    assert int(row.get("packs") or 0) >= 1, f"{recipe}/{strategy}: invalid pack count"
                    assert float(row.get("checkout_cost") or 0) > 0
                    assert float(row.get("consumed_cost") or 0) <= float(row.get("checkout_cost") or 0) + 0.01
                    assert not (row.get("product", {}).get("intelligence") or {}).get("is_complete_meal"), (
                        f"{recipe}/{strategy}: complete meal selected as an ingredient"
                    )
                strategy_totals[strategy] += sum(float(row.get("checkout_cost") or 0) for row in basket)
        print(f"BASKET QA: {basket_checks} ingredient/strategy decisions across {len(RECIPES)} recipes")
        for strategy, total in strategy_totals.items():
            print(f"  {strategy}: combined recipe checkout estimate €{total:.2f}")
        for recipe, missing in basket_unmatched.items():
            print(f"  BASKET UNMATCHED — {recipe}: {', '.join(sorted(set(missing)))}")

        # Explicit economic vs premium selection sanity check using two valid
        # catalog-shaped products for the same ingredient.
        class TierAdapter:
            def search(self, ingredient):
                if ingredient != "olive oil":
                    return []
                return [
                    {
                        "id": 1, "ingredient": "olive oil", "name_original": "ja! Olivenöl",
                        "package_size": 500, "package_unit": "ml", "price": 3.00,
                        "price_per_unit": 0.006, "availability": "available",
                        "ingredient_match_type": "exact",
                    },
                    {
                        "id": 2, "ingredient": "olive oil", "name_original": "REWE Bio Natives Olivenöl",
                        "package_size": 500, "package_unit": "ml", "price": 7.00,
                        "price_per_unit": 0.014, "availability": "available",
                        "ingredient_match_type": "exact",
                    },
                ]
        tier_meal = {"id": "tier-qa", "name": "Olive oil test", "ingredients": [["olive oil", 100, "ml"]]}
        tier_requirements = consolidate([tier_meal], {"tier-qa": 2})
        cheap = build_basket(tier_requirements, TierAdapter(), "maximum-savings")[0]
        premium = build_basket(tier_requirements, TierAdapter(), "premium")[0]
        assert cheap["product"]["id"] == 1, "Economic strategy must choose the lower checkout price"
        assert premium["product"]["id"] == 2, "Premium strategy must prefer the premium signal"
        print("PRICE TIERS: economic selects the cheaper SKU; premium selects the premium SKU")

        # Semantic guardrails for the three preparation levels.
        assert classify_product({"name_original": "REWE Bio Passata 700 g", "category": "fertiggerichte-konserven"}).product_type == "prepared_component"
        assert not classify_product({"name_original": "REWE Lasagneplatten 500 g"}).is_complete_meal
        assert classify_product({"name_original": "REWE Garnelen Curry Fertiggericht 400 g"}).is_complete_meal
        assert classify_product({"name_original": "REWE Pizza Margherita 350 g"}).is_complete_meal
        assert classify_product({"name_original": "REWE Pizzateig"}).culinary_role == "dough"
        assert classify_product({"name_original": "REWE Gemüsebrühe"}).culinary_role == "broth"
        assert classify_product({"name_original": "REWE Oregano gerebelt"}).culinary_role == "seasoning"

        print(
            f"PASS: {len(RECIPES)} recipe families, {base_total} base ingredients, "
            f"{len(MIDDLE_SHORTCUTS)} middle-shortcut variants, {basket_checks} basket decisions, "
            "economic/premium tiers and complete-meal/component separation"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
