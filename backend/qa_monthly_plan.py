"""Thirty-day Bitewise plan QA: 90 meals, consolidated REWE basket and extras.

One-person scenario: breakfast, lunch and dinner for 30 days. The plan is
deterministic and uses the committed REWE snapshot; it makes no Gemini calls,
does not scrape, does not write user data and never opens a live REWE session.
Run from backend/: python qa_monthly_plan.py
"""
from collections import Counter
from datetime import date, timedelta

import qa_recipe_family_matching as base
from app.database import Product
from app.shopping.optimizer import build_basket, consolidate, summarize_waste


# Ingredients are two-serving recipe quantities; the simulation scales to one.
BREAKFASTS = [
    ("Blueberry overnight oats", ["oats", "milk", "yogurt", "blueberry", "banana", "chia seeds", "honey"]),
    ("Banana oat pancakes", ["banana", "oats", "eggs", "milk", "yogurt", "cinnamon", "honey"]),
    ("Avocado egg toast", ["bread", "avocado", "eggs", "lemon", "chili flakes"]),
    ("Greek yogurt fruit bowl", ["greek yogurt", "banana", "apple", "blueberry", "walnut", "honey"]),
    ("Spinach feta omelette", ["eggs", "spinach", "feta", "milk", "butter", "bread"]),
    ("Peanut butter banana toast", ["bread", "peanut butter", "banana", "milk"]),
    ("Apple cinnamon porridge", ["oats", "milk", "apple", "cinnamon", "walnut", "honey"]),
    ("Smoked salmon bagel", ["bagel", "smoked salmon", "cream cheese", "cucumber", "lemon"]),
    ("Berry chia pudding", ["chia seeds", "milk", "yogurt", "raspberry", "blueberry", "honey"]),
    ("Breakfast burrito", ["tortilla", "eggs", "cheese", "bell pepper", "tomato", "spinach"]),
]
LUNCHES = [
    ("Chicken pesto pasta", ["chicken breast", "pasta", "pesto", "parmesan", "cherry tomato", "garlic"]),
    ("Greek chicken bowl", ["chicken breast", "rice", "cucumber", "tomato", "feta", "greek yogurt", "lemon"]),
    ("Tuna avocado rice bowl", ["tuna", "rice", "avocado", "cucumber", "carrot", "soy sauce"]),
    ("Lentil bolognese", ["lentil", "spaghetti", "tomato passata", "onion", "carrot", "garlic", "parmesan"]),
    ("Falafel hummus wrap", ["falafel", "wrap", "hummus", "cucumber", "tomato", "lettuce", "yogurt"]),
    ("Chicken Caesar-style salad", ["chicken breast", "lettuce", "parmesan", "bread", "yogurt", "lemon"]),
    ("Chickpea couscous bowl", ["couscous", "chickpea", "cucumber", "tomato", "feta", "lemon", "parsley"]),
    ("Shrimp garlic noodles", ["shrimp", "noodles", "garlic", "soy sauce", "spring onion", "lime"]),
    ("Caprese mozzarella sandwich", ["bread", "mozzarella", "tomato", "basil", "olive oil"]),
    ("Beef taco bowl", ["ground beef", "rice", "tomato", "lettuce", "corn", "yogurt", "lime"]),
    ("Tomato mozzarella pasta salad", ["pasta", "mozzarella", "cherry tomato", "basil", "olive oil"]),
    ("Salmon cucumber sushi bowl", ["salmon", "rice", "cucumber", "avocado", "soy sauce", "sesame seeds"]),
    ("Shakshuka with bread", ["eggs", "tomato", "bell pepper", "onion", "garlic", "bread"]),
    ("Roasted vegetable couscous", ["couscous", "chickpea", "zucchini", "bell pepper", "carrot", "lemon"]),
    ("Potato broccoli soup", ["potato", "broccoli", "onion", "cream", "vegetable broth", "bread"]),
]
DINNERS = [
    ("Creamy mushroom tagliatelle", ["tagliatelle", "mushroom", "cream", "garlic", "parmesan", "thyme"]),
    ("Teriyaki salmon rice", ["salmon", "rice", "soy sauce", "honey", "ginger", "garlic"]),
    ("Chicken fajita rice bowl", ["chicken breast", "rice", "bell pepper", "onion", "tomato", "lime", "yogurt"]),
    ("Vegetarian chickpea coconut curry", ["chickpea", "coconut milk", "sweet potato", "spinach", "rice", "ginger"]),
    ("Beef meatballs and tomato pasta", ["ground beef", "breadcrumbs", "eggs", "tomato passata", "spaghetti", "parmesan"]),
    ("Crispy tofu peanut noodles", ["tofu", "noodles", "peanut butter", "soy sauce", "lime", "ginger", "carrot"]),
    ("Garlic shrimp pasta", ["shrimp", "tagliatelle", "garlic", "lemon", "parsley", "butter"]),
    ("Chicken schnitzel and potato salad", ["chicken breast", "breadcrumbs", "eggs", "flour", "potato", "cucumber", "yogurt"]),
    ("Mushroom spinach risotto", ["rice", "mushroom", "spinach", "parmesan", "white wine", "vegetable broth"]),
    ("Chili con carne", ["ground beef", "kidney beans", "corn", "tomato passata", "onion", "bell pepper"]),
    ("Eggplant parmesan", ["eggplant", "tomato passata", "mozzarella", "parmesan", "breadcrumbs", "basil"]),
    ("Lemon herb cod and potatoes", ["cod", "potato", "lemon", "butter", "parsley", "broccoli"]),
    ("Thai green chicken curry", ["chicken breast", "curry paste", "coconut milk", "bell pepper", "rice", "lime"]),
    ("Stuffed bell peppers", ["bell pepper", "rice", "ground beef", "tomato passata", "onion", "cheese"]),
    ("Pork mushroom skillet", ["pork", "mushroom", "cream", "onion", "potato", "rosemary"]),
]

# Hands-on time and elapsed cook time are separate. Values are planning estimates,
# not values claimed to have been generated or verified by Gemini.
COOKING = {
    "Blueberry overnight oats": (5, 0, "no-cook / overnight"),
    "Banana oat pancakes": (10, 12, "from scratch / stovetop"),
    "Avocado egg toast": (8, 7, "quick / stovetop"),
    "Greek yogurt fruit bowl": (5, 0, "no-cook"),
    "Spinach feta omelette": (8, 8, "from scratch / stovetop"),
    "Peanut butter banana toast": (3, 3, "assembly / toaster"),
    "Apple cinnamon porridge": (5, 8, "stovetop"),
    "Smoked salmon bagel": (5, 0, "assembly / no-cook"),
    "Berry chia pudding": (5, 0, "no-cook / chilled"),
    "Breakfast burrito": (10, 10, "stovetop"),
    "Chicken pesto pasta": (10, 15, "from scratch / stovetop"),
    "Greek chicken bowl": (12, 18, "from scratch / stovetop"),
    "Tuna avocado rice bowl": (10, 15, "shortcut / cooked rice"),
    "Lentil bolognese": (12, 30, "from scratch / stovetop"),
    "Falafel hummus wrap": (7, 8, "shortcut / assembly"),
    "Chicken Caesar-style salad": (10, 15, "hybrid / stovetop"),
    "Chickpea couscous bowl": (8, 10, "shortcut / kettle"),
    "Shrimp garlic noodles": (10, 12, "from scratch / stovetop"),
    "Caprese mozzarella sandwich": (5, 0, "assembly / no-cook"),
    "Beef taco bowl": (12, 18, "from scratch / stovetop"),
    "Tomato mozzarella pasta salad": (10, 12, "hybrid / stovetop"),
    "Salmon cucumber sushi bowl": (12, 15, "hybrid / stovetop"),
    "Shakshuka with bread": (10, 15, "from scratch / stovetop"),
    "Roasted vegetable couscous": (12, 20, "from scratch / air fryer + kettle"),
    "Potato broccoli soup": (10, 25, "from scratch / stovetop"),
    "Creamy mushroom tagliatelle": (10, 18, "from scratch / stovetop"),
    "Teriyaki salmon rice": (10, 18, "from scratch / stovetop"),
    "Chicken fajita rice bowl": (12, 20, "from scratch / stovetop"),
    "Vegetarian chickpea coconut curry": (12, 25, "from scratch / stovetop"),
    "Beef meatballs and tomato pasta": (15, 25, "from scratch / stovetop"),
    "Crispy tofu peanut noodles": (12, 18, "hybrid / air fryer + stovetop"),
    "Garlic shrimp pasta": (10, 15, "from scratch / stovetop"),
    "Chicken schnitzel and potato salad": (15, 25, "from scratch / air fryer + stovetop"),
    "Mushroom spinach risotto": (12, 30, "from scratch / stovetop"),
    "Chili con carne": (12, 30, "from scratch / stovetop"),
    "Eggplant parmesan": (15, 25, "hybrid / air fryer"),
    "Lemon herb cod and potatoes": (12, 22, "hybrid / air fryer + stovetop"),
    "Thai green chicken curry": (12, 22, "hybrid / stovetop"),
    "Stuffed bell peppers": (15, 30, "from scratch / air fryer"),
    "Pork mushroom skillet": (12, 22, "from scratch / stovetop"),
}


def recipe(name, ingredients, day, slot):
    meal = base._recipe_meal(name, ingredients)
    meal["id"] = f"month-{day:02d}-{slot}"
    meal["name"] = f"Day {day} {slot}: {name}"
    return meal


def find_coke(db):
    rows = db.query(Product).filter(
        Product.supermarket == "REWE",
        Product.name_original.ilike("%coca-cola%"),
    ).all()
    candidates = []
    for row in rows:
        title = (row.name_original or "").lower()
        if row.price and row.price > 0 and row.product_url and "coca-cola" in title:
            candidates.append(row)
    # Prefer a regular 1.5l bottle if available; otherwise select a priced,
    # valid Coca-Cola SKU and report its actual pack size.
    candidates.sort(key=lambda row: (
        0 if "1,5" in (row.name_original or "").lower() or "1.5" in (row.name_original or "").lower() else 1,
        float(row.price or 0),
    ))
    return candidates[0] if candidates else None


def main():
    db = base.SessionLocal()
    try:
        catalog_count = db.query(Product).filter(Product.supermarket == "REWE").count()
        assert catalog_count >= 1000, f"Full REWE snapshot missing: {catalog_count}"
        adapter = base._CachedCatalogAdapter(base.CatalogAdapter(db))
        meals = []
        schedule = []
        cooking_minutes = []
        for day in range(1, 31):
            b_name, b_ingredients = BREAKFASTS[(day - 1) % len(BREAKFASTS)]
            l_name, l_ingredients = LUNCHES[(day - 1) % len(LUNCHES)]
            d_name, d_ingredients = DINNERS[((day - 1) * 7) % len(DINNERS)]
            for slot, pair in (("breakfast", (b_name, b_ingredients)),
                               ("lunch", (l_name, l_ingredients)),
                               ("dinner", (d_name, d_ingredients))):
                name, ingredients = pair
                meals.append(recipe(name, ingredients, day, slot))
                hands_on, elapsed, mode = COOKING[name]
                cooking_minutes.append((name, hands_on, elapsed, mode))
                schedule.append((day, slot, name, hands_on, elapsed, mode))

        assert len(meals) == 90 and len({m["id"] for m in meals}) == 90
        servings = {meal["id"]: 1 for meal in meals}  # one person, 30 days
        requirements = consolidate(meals, servings)
        keys = [(r["canonical_ingredient"], r["unit"]) for r in requirements]
        assert len(keys) == len(set(keys)), "Duplicate canonical ingredient/unit rows"
        assert all(r["quantity"] > 0 and r["source_meals"] for r in requirements)
        assert all(len(r["source_meals"]) <= 90 for r in requirements)

        print("MONTHLY PLAN: 30 days | 1 person | 90 meals | 30 breakfasts + 30 lunches + 30 dinners")
        print(f"MENU VARIETY: {len(set(x[2] for x in schedule))} distinct dishes")
        print(f"CONSOLIDATED SHOPPING LINES: {len(requirements)}")
        print(f"RECIPE-TO-BASKET COVERAGE: {sum(bool(adapter.search(r['ingredient'])) for r in requirements)}/{len(requirements)} distinct ingredients")
        print("COOKING TIME BY MEAL (estimated hands-on / elapsed minutes):")
        for day, slot, name, hands_on, elapsed, mode in schedule:
            print(f"  DAY {day:02d} {slot.upper()} | {name} | {hands_on} min hands-on / {elapsed} min elapsed | {mode}")

        strategy_results = {}
        for strategy in ("maximum-savings", "best-value", "premium", "plan-efficiency"):
            basket = build_basket(requirements, adapter, strategy)
            assert len(basket) == len(requirements), f"{strategy}: dropped shopping rows"
            seen = set()
            for row in basket:
                key = (row["canonical_ingredient"], row["unit"])
                assert key not in seen, f"{strategy}: duplicate row {key}"
                seen.add(key)
                if row["match_status"] == "unmatched":
                    assert row.get("product") is None
                    continue
                if row["match_status"] == "covered":
                    continue
                product = row.get("product")
                assert product and float(product.get("price") or 0) > 0
                assert int(row.get("packs") or 0) >= 1
                assert float(row.get("checkout_cost") or 0) >= float(row.get("consumed_cost") or 0)
                assert base.ingredient_product_match_type(
                    row["ingredient"], base._product_title(product), product.get("category")
                ), f"{strategy}: semantically invalid selection for {row['ingredient']}: {base._product_title(product)}"
            checkout = round(sum(float(r.get("checkout_cost") or 0) for r in basket), 2)
            consumed = round(sum(float(r.get("consumed_cost") or 0) for r in basket), 2)
            unmatched = [r["ingredient"] for r in basket if r["match_status"] == "unmatched"]
            strategy_results[strategy] = (basket, checkout, consumed, unmatched)
            print(f"MONTH COST {strategy}: checkout €{checkout:.2f} | consumed estimate €{consumed:.2f} | unmatched {len(unmatched)}")
            if unmatched:
                print(f"  UNMATCHED ({strategy}): {', '.join(unmatched)}")

        savings = strategy_results["maximum-savings"][1]
        balanced = strategy_results["best-value"][1]
        premium = strategy_results["premium"][1]
        assert savings <= balanced + 0.01, "Maximum-savings should not exceed Best Value on this same basket"
        print(f"STRATEGY COMPARISON: savings €{savings:.2f} | best-value €{balanced:.2f} | premium €{premium:.2f}")
        print("Maximum-savings is checked against the lowest checkout choice; other strategies are compared empirically, not forced into a price order.")

        # Add discretionary extras separately from recipe ingredients. This prevents
        # drinks/snacks from being misclassified as ingredients in recipes.
        coke = find_coke(db)
        if coke:
            print(f"EXTRA PRODUCT: {coke.name_original} | pack={coke.package_size} {coke.package_unit} | €{float(coke.price):.2f} | REWE URL={'valid' if str(coke.product_url).startswith('https://www.rewe.de/shop/p/') else 'invalid'}")
            assert str(coke.product_url).startswith("https://www.rewe.de/shop/p/")
            monthly_extra_packs = 4
            extras_cost = round(float(coke.price) * monthly_extra_packs, 2)
            print(f"EXTRAS: {monthly_extra_packs} packs/month | €{extras_cost:.2f}")
            for strategy in strategy_results:
                print(f"MONTH TOTAL WITH COCA-COLA {strategy}: €{strategy_results[strategy][1] + extras_cost:.2f}")
        else:
            print("EXTRA PRODUCT: NO PRICED COCA-COLA SKU WITH VALID REWE PRODUCT URL IN SNAPSHOT")

        # Report estimated package leftovers in their own units; never combine g/ml/pieces.
        best_basket = strategy_results["best-value"][0]
        print(f"BEST-VALUE LEFTOVERS BY UNIT: {summarize_waste(best_basket)}")
        print("MONTHLY PLAN QA: PASS")
    finally:
        db.close()


if __name__ == "__main__":
    main()
