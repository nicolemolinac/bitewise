"""Intensive recipe-family, convenience-variant and basket QA against the full REWE snapshot.

Run from backend/: python qa_recipe_family_matching.py
Uses a disposable SQLite DB imported from the committed catalog snapshot.
No Gemini API calls, live REWE calls, scraper, image process or user DB are touched.
"""
import os
from pathlib import Path
from sqlalchemy import or_
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-recipe-matrix-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "rewe.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

from app.database import Product, SessionLocal
# Import the production entrypoint first: it installs the strict multilingual
# CatalogAdapter used by app.server:app and deliberately disables demo fallbacks.
import app.server as production_server  # noqa: F401
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
    "Chicken schnitzel with potato salad": [
        "chicken breast", "breadcrumbs", "eggs", "flour", "potato",
        "cucumber", "yogurt", "mustard", "lemon", "parsley",
    ],
    "Beef meatballs in tomato sauce": [
        "ground beef", "breadcrumbs", "eggs", "onion", "garlic",
        "tomato passata", "parmesan", "parsley", "olive oil",
    ],
    "Chili con carne": [
        "ground beef", "kidney beans", "corn", "tomato passata",
        "tomato paste", "onion", "bell pepper", "garlic", "chili flakes",
    ],
    "Vegetarian chickpea coconut curry": [
        "chickpea", "coconut milk", "sweet potato", "spinach",
        "rice", "ginger", "garlic", "onion", "chili flakes",
    ],
    "Greek village salad": [
        "tomato", "cucumber", "red onion", "feta", "olive oil",
        "lemon", "oregano", "lettuce",
    ],
    "Roasted vegetable couscous": [
        "couscous", "chickpea", "zucchini", "bell pepper", "carrot",
        "tomato", "vegetable broth", "lemon", "parsley", "olive oil",
    ],
    "Creamy pork mushroom medallions": [
        "pork", "mushroom", "cream", "onion", "garlic",
        "potato", "rosemary", "black pepper", "butter",
    ],
    "Salmon fish tacos": [
        "salmon", "tortilla", "cucumber", "tomato", "avocado",
        "greek yogurt", "lime", "chili flakes", "lettuce",
    ],
    "Eggplant parmesan bake": [
        "eggplant", "tomato passata", "mozzarella", "parmesan",
        "breadcrumbs", "eggs", "basil", "olive oil",
    ],
    "Broccoli potato soup": [
        "broccoli", "potato", "onion", "garlic", "cream",
        "vegetable broth", "cheese", "butter", "black pepper",
    ],
    "Miso-style tofu noodle bowl": [
        "tofu", "noodles", "eggs", "mushroom", "spinach",
        "soy sauce", "ginger", "garlic", "spring onion",
    ],
    "Tuna avocado rice bowl": [
        "tuna", "rice", "avocado", "cucumber", "carrot",
        "soy sauce", "lime", "sesame seeds",
    ],
    "Quiche lorraine": [
        "eggs", "cream", "bacon", "cheese", "onion",
        "flour", "butter", "black pepper",
    ],
    "Stuffed bell peppers": [
        "bell pepper", "rice", "ground beef", "tomato passata",
        "onion", "garlic", "cheese", "parsley",
    ],
    "Chicken noodle soup": [
        "chicken breast", "noodles", "carrot", "celery",
        "onion", "chicken broth", "parsley", "black pepper",
    ],
    "Crispy tofu peanut noodles": [
        "tofu", "noodles", "peanut butter", "soy sauce",
        "lime", "ginger", "garlic", "carrot", "cucumber",
    ],
    "Apple almond crumble": [
        "apple", "oats", "flour", "butter", "brown sugar",
        "cinnamon", "almond", "lemon",
    ],
    "Blueberry banana overnight oats": [
        "oats", "milk", "yogurt", "blueberry", "banana",
        "honey", "peanut butter",
    ],
    "Sweet potato black bean bowls": [
        "sweet potato", "bean", "corn", "rice", "avocado",
        "tomato", "lime", "greek yogurt", "chili flakes",
    ],
    "Turkey meatloaf": [
        "turkey", "breadcrumbs", "eggs", "onion", "garlic",
        "tomato paste", "carrot", "potato", "parsley",
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
    "Chicken schnitzel with potato salad": ["chicken breast", "breadcrumbs", "potato", "yogurt"],
    "Beef meatballs in tomato sauce": ["ground beef", "breadcrumbs", "tomato sauce", "parmesan"],
    "Chili con carne": ["ground beef", "kidney beans", "corn", "tomato passata"],
    "Vegetarian chickpea coconut curry": ["chickpea", "coconut milk", "spinach", "rice"],
    "Greek village salad": ["feta", "cucumber", "tomato", "greek yogurt"],
    "Roasted vegetable couscous": ["couscous", "chickpea", "zucchini", "vegetable broth"],
    "Creamy pork mushroom medallions": ["pork", "mushroom", "cream", "potato"],
    "Salmon fish tacos": ["tortilla", "salmon", "greek yogurt", "avocado"],
    "Eggplant parmesan bake": ["eggplant", "tomato passata", "mozzarella", "parmesan"],
    "Broccoli potato soup": ["broccoli", "vegetable broth", "cream", "cheese"],
    "Miso-style tofu noodle bowl": ["tofu", "noodles", "soy sauce", "ginger"],
    "Tuna avocado rice bowl": ["tuna", "rice", "avocado", "soy sauce"],
    "Quiche lorraine": ["eggs", "cream", "bacon", "cheese"],
    "Stuffed bell peppers": ["bell pepper", "rice", "ground beef", "tomato sauce"],
    "Chicken noodle soup": ["chicken breast", "noodles", "carrot", "chicken broth"],
    "Crispy tofu peanut noodles": ["tofu", "noodles", "peanut butter", "soy sauce"],
    "Apple almond crumble": ["apple", "oats", "cinnamon", "almond"],
    "Blueberry banana overnight oats": ["oats", "milk", "yogurt", "blueberry"],
    "Sweet potato black bean bowls": ["sweet potato", "bean", "corn", "rice"],
    "Turkey meatloaf": ["turkey", "breadcrumbs", "tomato paste", "potato"],
    "Creamy carbonara": ["spaghetti", "bacon", "parmesan", "cream", "eggs"],
    "Garlic shrimp pasta": ["tagliatelle", "shrimp", "garlic", "butter", "parsley"],
    "Creamy salmon spinach rice": ["salmon", "spinach", "rice", "cream", "lemon"],
    "Beef tacos": ["ground beef", "tortilla", "tomato", "lettuce", "yogurt"],
    "Teriyaki salmon rice": ["salmon", "rice", "soy sauce", "honey", "ginger"],
    "Potato gratin": ["potato", "cream", "milk", "parmesan", "butter"],
    "Banana oat pancakes": ["banana", "oats", "eggs", "milk", "yogurt"],
}

READY_MEAL_FAMILIES = {}


def _qa_quantity(ingredient):
    """Use realistic compatible recipe units so basket QA tests package matching, not bad fixtures."""
    name = ingredient.lower()
    if name in {"eggs", "garlic", "lemon", "lime", "lettuce", "eggplant", "aubergine"}:
        return (2 if name in {"eggs", "tortilla", "garlic"} else 1, "unit")
    if name in {"olive oil", "soy sauce", "milk", "cream", "coconut milk", "mustard"}:
        return (20 if name in {"olive oil", "soy sauce", "mustard"} else 100, "ml")
    if name == "mustard":
        return (15, "ml")
    if name in {"salt", "black pepper", "oregano", "thyme", "nutmeg", "paprika powder", "chili flakes", "cinnamon", "baking powder"}:
        return (2, "g")
    if name == "honey":
        return (20, "g")
    return (100, "g")


def _recipe_meal(name, ingredients):
    return {
        "id": "qa-" + str(abs(hash(name))),
        "name": name,
        "base_servings": 2,
        "ingredients": [
            [ingredient, *_qa_quantity(ingredient)]
            for ingredient in ingredients
        ],
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
        if base_missing:
            # Distinguish a missing product from an alias/query bug by showing
            # the real REWE titles that contain likely German search stems.
            for recipe, missing in base_missing.items():
                for ingredient in missing:
                    stems = {
                        "paprika powder": ("paprika", "paprik"),
                        "ginger": ("ingwer", "ginger"),
                        "soy sauce": ("soja", "soy"),
                        "eggplant": ("aubergine", "melanzani", "eggplant"),
                        "celery": ("sellerie", "stangensellerie", "knollensellerie", "celery"),
                        "spring onion": ("frühlingszwiebel", "fruehlingszwiebel", "zwiebelgrün", "spring onion"),
                        "sesame seeds": ("sesam", "sesame"),
                    }.get(ingredient, tuple(ingredient.split()))
                    candidates = (
                        db.query(Product)
                        .filter(Product.supermarket == "REWE")
                        .filter(or_(*[
                            getattr(Product, field).ilike(f"%{stem}%")
                            for field in ("name_original", "name_normalized", "translated_name")
                            for stem in stems
                        ]))
                        .limit(20).all()
                    )
                    print(f"  CATALOG DIAGNOSTIC — {ingredient}: " + " | ".join(
                        str(product.name_original or product.name_normalized or "") for product in candidates
                    ))
        print(f"BASE RECIPES: {len(RECIPES)} dishes; {base_matched}/{base_total} ingredients matched ({base_coverage:.1%})")
        for recipe, missing in base_missing.items():
            print(f"  BASE MISSING — {recipe}: {', '.join(missing)}")
        assert base_coverage >= 0.80, f"Base recipe matching below 80%: {base_coverage:.1%}"

        middle_total = middle_matched = 0
        middle_missing = {}
        for recipe, ingredients in MIDDLE_SHORTCUTS.items():
            for ingredient in ingredients:
                middle_total += 1
                products = adapter.search(ingredient)
                valid = [
                    product for product in products
                    if ingredient_product_match_type(ingredient, _product_title(product))
                ]
                if valid:
                    middle_matched += 1
                else:
                    middle_missing.setdefault(recipe, []).append(ingredient)
        middle_coverage = middle_matched / max(middle_total, 1)
        print(f"MIDDLE SHORTCUTS: {middle_matched}/{middle_total} component ingredients matched ({middle_coverage:.1%})")
        for recipe, missing in middle_missing.items():
            print(f"  SHORTCUT MISSING — {recipe}: {', '.join(missing)}")
        assert middle_coverage >= 0.75, f"Middle-shortcut ingredient matching below 75%: {middle_coverage:.1%}"

        # The exact three-level convenience payload consumed by AppV3 is also
        # checked against the real catalog for every recipe. Homemade stays the
        # original recipe; middle shortcuts must be components; ready-made must
        # be a genuine complete meal, never a sauce or ingredient.
        convenience_shortcuts = convenience_ready = 0
        shortcut_recipe_coverage = ready_recipe_coverage = 0
        convenience_counts = {}
        for recipe, ingredients in RECIPES.items():
            options = production_server._build_convenience_options(
                db,
                {"name": recipe, "ingredients": [[name, *_qa_quantity(name)] for name in ingredients]},
            )
            convenience_counts[recipe] = {
                "shortcuts": len(options["shortcuts"]),
                "ready_made": len(options["ready_made"]),
            }
            shortcut_recipe_coverage += bool(options["shortcuts"])
            ready_recipe_coverage += bool(options["ready_made"])
            for product in options["shortcuts"]:
                convenience_shortcuts += 1
                assert not product["is_complete_meal"], (
                    f"{recipe}: complete meal leaked into middle shortcuts: {product['name']}"
                )
                assert (
                    product["product_type"] == "prepared_component"
                    or product["storage_type"] == "frozen"
                    or product["convenience_level"] >= 2
                ), f"{recipe}: unsuitable shortcut candidate: {product['name']}"
            for product in options["ready_made"]:
                convenience_ready += 1
                assert product["is_complete_meal"], (
                    f"{recipe}: component leaked into ready-made alternatives: {product['name']}"
                )
                title = product["name"].lower()
                if "chicken" in " ".join(ingredients).lower():
                    assert any(term in title for term in ("hähnchen", "haehnchen", "chicken")), (
                        f"{recipe}: ready meal does not match the recipe protein: {product['name']}"
                    )
                if "lentil" in " ".join(ingredients).lower():
                    assert any(term in title for term in ("linse", "linsen", "lentil", "vegan", "vegetar")), (
                        f"{recipe}: meat bolognese is not a lentil shortcut: {product['name']}"
                    )
        assert convenience_ready > 0, "Known ready-meal families should expose genuine complete-meal alternatives"
        assert shortcut_recipe_coverage >= 20, (
            f"Middle shortcuts should cover at least half the recipe families, got "
            f"{shortcut_recipe_coverage}/{len(RECIPES)}: {convenience_counts}"
        )
        print(
            f"CONVENIENCE LEVELS: {len(RECIPES)} homemade baselines; "
            f"{convenience_shortcuts} verified middle-shortcut products across "
            f"{shortcut_recipe_coverage} recipes; {convenience_ready} relevant complete ready meals "
            f"across {ready_recipe_coverage} recipes"
        )
        for recipe, counts in convenience_counts.items():
            print(
                f"  CONVENIENCE COVERAGE — {recipe}: "
                f"{counts['shortcuts']} middle shortcuts; {counts['ready_made']} complete meals"
            )

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
            for ingredient in sorted(set(missing)):
                candidates = [
                    product for product in adapter.search(ingredient)
                    if ingredient_product_match_type(ingredient, _product_title(product))
                ]
                for product in candidates[:8]:
                    requirement = next((row for row in requirements if row["ingredient"] == ingredient), {})
                    print(
                        "    BASKET REQUIREMENT — "
                        f"{ingredient}: qty={requirement.get('quantity')} unit={requirement.get('unit')}"
                    )
                    print(
                        "    BASKET CANDIDATE — "
                        f"{ingredient}: id={product.get('id')} "
                        f"name={_product_title(product)} "
                        f"price={product.get('price')} "
                        f"package_size={product.get('package_size')} "
                        f"package_unit={product.get('package_unit')} "
                        f"unit={product.get('unit')} "
                        f"price_per_unit={product.get('price_per_unit')} "
                        f"availability={product.get('availability')}"
                    )
        assert not basket_unmatched, (
            f"All recipe ingredients should resolve to priced, unit-compatible catalog products: {basket_unmatched}"
        )

        # The product-alternatives route must use the recipe ingredient and the
        # same full-catalog matcher, not Product.ingredient equality/category caps.
        alternative_checks = 0
        for ingredient, unit, needed_quantity in (
            ("olive oil", "ml", 100),
            ("tomato passata", "g", 350),
            ("chicken breast", "g", 250),
            ("rice", "g", 150),
            ("parmesan", "g", 40),
        ):
            current_candidates = [
                product for product in adapter.search(ingredient)
                if product.get("id") and float(product.get("price") or 0) > 0
                and product.get("package_unit") == unit
            ]
            assert current_candidates, f"No priced {ingredient} SKU with a compatible package unit"
            current_product = current_candidates[0]
            alternative_result = production_server.main_module.alternatives(
                current_product["id"],
                needed_qty=needed_quantity,
                unit=unit,
                ingredient=ingredient,
            )
            alternatives = alternative_result["alternatives"]
            assert alternatives, f"No compatible product alternatives returned for {ingredient}"
            assert all(item.get("ingredient_match_type") in {"exact", "substitute"} for item in alternatives)
            assert all(float(item.get("price") or 0) > 0 for item in alternatives)
            assert all(item.get("supermarket") == "REWE" for item in alternatives)
            assert all(not (item.get("intelligence") or {}).get("is_complete_meal") for item in alternatives)
            assert all(
                alternatives[index]["price_per_package_unit"] <= alternatives[index+1]["price_per_package_unit"]
                for index in range(len(alternatives)-1)
            ), f"{ingredient} alternatives must be ordered by comparable unit price"
            alternative_checks += 1
            print(f"PRODUCT ALTERNATIVES: {ingredient}: {len(alternatives)} compatible priced alternatives")
        assert alternative_checks == 5, "Oil, sauce, protein, staple and cheese must expose real product alternatives"

        # Explicit economic vs premium selection sanity check using two valid
        # catalog-shaped products for the same ingredient.
        class TierAdapter:
            def search(self, ingredient):
                if ingredient != "olive oil":
                    return []
                return [
                    {
                        "id": 1, "ingredient": "olive oil", "name_original": "ja! Olivenöl",
                        "package_size": 100, "package_unit": "ml", "price": 3.00,
                        "price_per_unit": 0.006, "availability": "available",
                        "ingredient_match_type": "exact",
                    },
                    {
                        "id": 2, "ingredient": "olive oil", "name_original": "REWE Bio Natives Olivenöl",
                        "package_size": 100, "package_unit": "ml", "price": 7.00,
                        "price_per_unit": 0.014, "availability": "available",
                        "ingredient_match_type": "exact",
                    },
                ]

            def get_by_id(self, product_id):
                return next((product for product in self.search("olive oil") if product["id"] == product_id), None)

        tier_meal = {"id": "tier-qa", "name": "Olive oil test", "ingredients": [["olive oil", 100, "ml"]]}
        tier_requirements = consolidate([tier_meal], {"tier-qa": 2})
        cheap = build_basket(tier_requirements, TierAdapter(), "maximum-savings")[0]
        premium = build_basket(tier_requirements, TierAdapter(), "premium")[0]
        from app.shopping.optimizer import _candidate_score, _premium_signal
        cheap_product = next(p for p in TierAdapter().search("olive oil") if p["id"] == 1)
        premium_product = next(p for p in TierAdapter().search("olive oil") if p["id"] == 2)
        assert _premium_signal(cheap_product) < 0, "Discount SKU fixture must carry a discount signal"
        assert _premium_signal(premium_product) > 0, "Bio SKU fixture must carry a premium signal"
        cheap_score = _candidate_score("premium", 3.0, 0.0, 0.006, 1, cheap_product)
        premium_score = _candidate_score("premium", 7.0, 0.0, 0.014, 1, premium_product)
        assert premium_score < cheap_score, (
            f"Premium scoring must prefer the premium signal: bio={premium_score}, discount={cheap_score}"
        )
        assert cheap["product"]["id"] == 1, (
            f"Economic strategy must choose lower checkout price; got {cheap['product']}"
        )
        assert premium["product"]["id"] == 2, (
            f"Premium strategy must prefer premium signal; got {premium['product']}"
        )
        print("PRICE TIERS: economic selects the cheaper SKU; premium selects the premium SKU")

        # Quantity, pantry and override regressions: test the actual basket
        # optimizer with known package sizes, not only that it returns a row.
        class QuantityAdapter:
            def search(self, ingredient):
                rows = {
                    "rice": [{
                        "id": 10, "name_original": "Rice 500 g", "package_size": 500,
                        "package_unit": "g", "price": 1.50, "price_per_unit": 0.003,
                        "availability": "available", "ingredient_match_type": "exact",
                    }],
                    "milk": [{
                        "id": 11, "name_original": "Milk 500 ml", "package_size": 500,
                        "package_unit": "ml", "price": 0.90, "price_per_unit": 0.0018,
                        "availability": "available", "ingredient_match_type": "exact",
                    }],
                    "parmesan": [
                        {
                            "id": 12, "name_original": "Grana Padano 200 g",
                            "package_size": 200, "package_unit": "g", "price": 1.80,
                            "price_per_unit": 0.009, "availability": "available",
                            "ingredient_match_type": "substitute",
                        },
                        {
                            "id": 13, "name_original": "Parmigiano Reggiano 200 g",
                            "package_size": 200, "package_unit": "g", "price": 3.50,
                            "price_per_unit": 0.0175, "availability": "available",
                            "ingredient_match_type": "exact",
                        },
                    ],
                    "pine nuts": [{
                        "id": 14, "name_original": "REWE Kürbiskerne 200 g",
                        "package_size": 200, "package_unit": "g", "price": 1.20,
                        "price_per_unit": 0.006, "availability": "available",
                        "ingredient_match_type": "substitute",
                    }],
                }
                return rows.get(ingredient, [])

            def get_by_id(self, product_id):
                for ingredient in ("rice", "milk", "parmesan", "pine nuts"):
                    for product in self.search(ingredient):
                        if product["id"] == product_id:
                            return product
                return None

        qa_adapter = QuantityAdapter()
        quantity_cases = [
            ({"ingredient": "rice", "quantity": 1, "unit": "kg", "source_meals": ["Rice bowl"]},
             {"rice": {"quantity": 0.25, "unit": "kg"}}, 2, 3.0, 10),
            ({"ingredient": "milk", "quantity": 1, "unit": "l", "source_meals": ["Pancakes"]},
             {}, 2, 1.8, 11),
        ]
        for requirement, pantry_data, expected_packs, expected_cost, expected_id in quantity_cases:
            row = build_basket([requirement], qa_adapter, "maximum-savings", pantry=pantry_data)[0]
            assert row["match_status"] == "matched"
            assert row["product"]["id"] == expected_id
            assert row["packs"] == expected_packs, (
                f"{requirement['ingredient']}: expected {expected_packs} packs, got {row['packs']}"
            )
            assert abs(row["checkout_cost"] - expected_cost) < 0.01
        assert abs(build_basket([quantity_cases[0][0]], qa_adapter, "maximum-savings",
                                pantry=quantity_cases[0][1])[0]["pantry_used"] - 0.25) < 0.01

        # Exact culinary match must outrank a cheaper substitute; substitutions
        # must remain explicitly labeled and a user override must be respected.
        parmesan_requirement = {"ingredient": "parmesan", "quantity": 40, "unit": "g", "source_meals": ["Pasta"]}
        exact_parmesan = build_basket([parmesan_requirement], qa_adapter, "maximum-savings")[0]
        assert exact_parmesan["product"]["id"] == 13
        assert exact_parmesan["match_status"] == "matched"
        pine_requirement = {"ingredient": "pine nuts", "quantity": 30, "unit": "g", "source_meals": ["Pesto"]}
        pine = build_basket([pine_requirement], qa_adapter, "maximum-savings")[0]
        assert pine["product"]["id"] == 14 and pine["match_status"] == "substituted"
        override = build_basket(
            [{"ingredient": "olive oil", "quantity": 100, "unit": "ml", "source_meals": ["Test"]}],
            TierAdapter(), "maximum-savings", overrides={"olive oil": 2},
        )[0]
        assert override["product"]["id"] == 2 and override["selected_by_user"]
        incompatible = build_basket(
            [{"ingredient": "rice", "quantity": 100, "unit": "ml", "source_meals": ["Invalid unit"]}],
            qa_adapter, "maximum-savings",
        )[0]
        assert incompatible["match_status"] == "unmatched", "Mass/volume must never be guessed"
        print("QUANTITY QA: kg↔g, l↔ml, pantry deduction, exact-vs-substitute, user override and incompatible units passed")

        # Semantic guardrails for the three preparation levels.
        assert classify_product({"name_original": "REWE Bio Passata 700 g", "category": "fertiggerichte-konserven"}).product_type == "prepared_component"
        assert not classify_product({"name_original": "REWE Lasagneplatten 500 g"}).is_complete_meal
        assert classify_product({"name_original": "REWE Garnelen Curry Fertiggericht 400 g"}).is_complete_meal
        assert classify_product({"name_original": "REWE Pizza Margherita 350 g"}).is_complete_meal
        assert not classify_product({"name_original": "Bamboo Garden Bowl Topping 15g"}).is_complete_meal
        assert classify_product({"name_original": "REWE Pizzateig"}).culinary_role == "dough"
        assert not classify_product({"name_original": "REWE Pizza Gewürz"}).is_complete_meal
        assert not classify_product({"name_original": "REWE Pizza Sauce"}).is_complete_meal
        assert not classify_product({"name_original": "REWE Ramen Nudeln"}).is_complete_meal
        assert not classify_product({
            "name_original": "Henglein Pizzateig XXL 550g",
            "category": "fertiggerichte-konserven",
        }).is_complete_meal
        assert not classify_product({
            "name_original": "Marziale Sfoglia Lasagne Blätter 250g",
            "category": "fertiggerichte-konserven",
        }).is_complete_meal
        assert classify_product({
            "name_original": "ja! Lasagne Bolognese 1 kg",
            "category": "fertiggerichte-konserven",
        }).is_complete_meal
        assert classify_product({"name_original": "REWE Gemüsebrühe"}).culinary_role == "broth"
        assert classify_product({"name_original": "REWE Oregano gerebelt"}).culinary_role == "seasoning"
        assert classify_product({"name_original": "REWE Bio Räuchertofu"}).product_type == "prepared_component"
        assert classify_product({"name_original": "REWE Bio Kichererbsen 400 g", "category": "fertiggerichte-konserven"}).product_type == "prepared_component"
        assert classify_product({"name_original": "REWE Kartoffelsalat 400 g"}).product_type == "prepared_component"
        assert classify_product({"name_original": "REWE Quiche Lorraine"}).is_complete_meal

        print(
            f"PASS: {len(RECIPES)} recipe families, {base_total} base ingredients, "
            f"{len(MIDDLE_SHORTCUTS)} middle-shortcut variants, {basket_checks} basket decisions, "
            "economic/premium tiers and complete-meal/component separation"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
