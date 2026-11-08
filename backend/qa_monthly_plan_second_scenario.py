"""Second 30-day monthly simulation: two people and a different menu rotation.

Uses the committed REWE snapshot in a disposable QA database. No Gemini calls,
live scraping, user DB writes, browser session or checkout.
Run from backend/: python qa_monthly_plan_second_scenario.py
"""
from collections import Counter

import qa_monthly_plan as month
from app.shopping.optimizer import build_basket, consolidate

base = month.base
db = base.SessionLocal()
try:
    count = db.query(base.Product).filter(base.Product.supermarket == "REWE").count()
    assert count >= 1000, f"Full REWE snapshot missing: {count}"
    adapter = base._CachedCatalogAdapter(base.CatalogAdapter(db))

    meals = []
    schedule = []
    for day in range(1, 31):
        # Rotate independently from the first monthly simulation so this is a
        # genuinely different menu mix, not a rerun of the same 90 meals.
        breakfast = month.BREAKFASTS[(day + 2) % len(month.BREAKFASTS)]
        lunch = month.LUNCHES[(day + 5) % len(month.LUNCHES)]
        dinner = month.DINNERS[(day * 11 + 3) % len(month.DINNERS)]
        for slot, (name, ingredients) in (
            ("breakfast", breakfast), ("lunch", lunch), ("dinner", dinner)
        ):
            meal = month.recipe(name, ingredients, day, slot)
            meals.append(meal)
            schedule.append((day, slot, name))

    assert len(meals) == 90
    assert len({meal["id"] for meal in meals}) == 90
    servings = {meal["id"]: 2 for meal in meals}
    requirements = consolidate(meals, servings)
    keys = [(row["canonical_ingredient"], row["unit"]) for row in requirements]
    assert len(keys) == len(set(keys)), "Duplicate canonical ingredient/unit rows"
    assert all(row["quantity"] > 0 and row["source_meals"] for row in requirements)

    # Verify serving scaling against the exact same menu at one serving.
    one_person = consolidate(meals, {meal["id"]: 1 for meal in meals})
    one_map = {(r["canonical_ingredient"], r["unit"]): r["quantity"] for r in one_person}
    two_map = {(r["canonical_ingredient"], r["unit"]): r["quantity"] for r in requirements}
    assert one_map.keys() == two_map.keys(), "Ingredient rows changed when servings doubled"
    for key, quantity in one_map.items():
        assert abs(float(two_map[key]) - 2 * float(quantity)) <= 0.001, (
            f"Serving scaling mismatch for {key}: {quantity} -> {two_map[key]}"
        )

    print("SECOND MONTHLY SCENARIO: 30 days | 2 people | 180 servings | 90 meals")
    print(f"MENU VARIETY: {len(set(name for _, _, name in schedule))} distinct dishes")
    print(f"CONSOLIDATED SHOPPING LINES: {len(requirements)}")
    print(f"RECIPE-TO-BASKET COVERAGE: {sum(bool(adapter.search(r['ingredient'])) for r in requirements)}/{len(requirements)}")
    print("SERVING SCALING: PASS — every consolidated ingredient quantity doubles exactly")

    for strategy in ("maximum-savings", "best-value", "premium", "plan-efficiency"):
        basket = build_basket(requirements, adapter, strategy)
        assert len(basket) == len(requirements), f"{strategy}: dropped shopping rows"
        unmatched = []
        checkout = 0.0
        consumed = 0.0
        for row in basket:
            if row["match_status"] == "unmatched":
                unmatched.append(row["ingredient"])
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
            ), f"{strategy}: invalid product for {row['ingredient']}"
            checkout += float(row.get("checkout_cost") or 0)
            consumed += float(row.get("consumed_cost") or 0)
        print(
            f"2-PERSON MONTH {strategy}: checkout €{checkout:.2f} | "
            f"consumed €{consumed:.2f} | unmatched {len(unmatched)}"
        )
        if unmatched:
            print(f"  UNMATCHED: {', '.join(unmatched)}")

    print("SECOND MONTHLY SCENARIO: PASS")
finally:
    db.close()
