"""Second-wave 30-recipe semantic and basket QA.

Uses the committed REWE catalog snapshot in a disposable SQLite database.
No live scraping, image jobs, Gemini calls, product-detail jobs or user DB writes.
Run from backend/: python qa_recipe_semantic_second_wave.py
"""
from collections import Counter
import qa_recipe_family_matching as base
from app.ingredient_aliases import ingredient_search_terms

RECIPES = {
    "Japanese chicken curry": ["chicken breast", "potato", "carrot", "onion", "coconut milk", "rice", "ginger"],
    "Korean bibimbap": ["rice", "beef", "spinach", "carrot", "cucumber", "eggs", "sesame seeds", "soy sauce"],
    "Pad Thai": ["rice noodles", "shrimp", "eggs", "bean sprouts", "peanut", "lime", "fish sauce"],
    "Vietnamese lemongrass chicken": ["chicken breast", "lemongrass", "fish sauce", "lime", "rice", "coriander"],
    "Japanese teriyaki tofu bowl": ["tofu", "rice", "soy sauce", "honey", "ginger", "sesame seeds"],
    "Chinese mapo tofu": ["tofu", "ground beef", "chili flakes", "soy sauce", "garlic", "spring onion", "rice"],
    "Japchae glass noodle stir fry": ["glass noodles", "beef", "spinach", "carrot", "mushroom", "soy sauce", "sesame seeds"],
    "Kimchi fried rice": ["rice", "kimchi", "eggs", "spring onion", "sesame seeds", "soy sauce"],
    "Salmon sushi bowl": ["rice", "cucumber", "avocado", "salmon", "rice vinegar", "sesame seeds"],
    "Thai green curry": ["curry paste", "coconut milk", "chicken breast", "bamboo shoots", "bell pepper", "rice"],
    "Lemon drizzle cake": ["flour", "butter", "sugar", "eggs", "lemon", "baking powder"],
    "Carrot walnut cake": ["flour", "carrot", "eggs", "sugar", "walnut", "cinnamon", "cream cheese"],
    "Chocolate brownies": ["chocolate", "cocoa powder", "butter", "sugar", "eggs", "flour"],
    "Baked cheesecake": ["cream cheese", "quark", "butter", "eggs", "sugar", "vanilla"],
    "Apple strudel": ["puff pastry", "apple", "cinnamon", "raisin", "almond"],
    "Banana bread": ["banana", "flour", "eggs", "butter", "brown sugar", "baking soda", "walnut"],
    "Blueberry muffins": ["flour", "blueberry", "eggs", "milk", "butter", "sugar", "baking powder"],
    "Belgian waffles": ["flour", "milk", "eggs", "butter", "sugar", "baking powder"],
    "Buttermilk scones": ["flour", "butter", "milk", "sugar", "baking powder"],
    "Vanilla panna cotta": ["cream", "gelatin", "sugar", "vanilla", "raspberry"],
    "Mushroom risotto": ["rice", "mushroom", "parmesan", "white wine", "vegetable broth", "shallot"],
    "Beetroot goat cheese salad": ["beetroot", "goat cheese", "walnut", "arugula", "balsamic vinegar"],
    "Fennel orange salad": ["fennel", "orange", "olive oil", "lemon", "black olive"],
    "Sardine lemon toast": ["sardine", "bread", "lemon", "parsley", "olive oil"],
    "Mussels in white wine": ["mussels", "white wine", "garlic", "parsley", "butter"],
    "Creamy polenta with mushrooms": ["polenta", "mushroom", "vegetable broth", "parmesan", "thyme"],
    "Stuffed vine leaves": ["grape leaves", "rice", "lemon", "mint", "parsley"],
    "Tahini roasted cauliflower": ["cauliflower", "sesame paste", "chickpea", "cumin", "lemon"],
    "Falafel hummus wraps": ["falafel", "wrap", "hummus", "cucumber", "tomato", "yogurt"],
    "Buckwheat savory crepes": ["buckwheat", "eggs", "milk", "butter", "cheese", "ham"],
}

def main():
    assert len(RECIPES) == 30 and len(set(RECIPES)) == 30
    db = base.SessionLocal()
    try:
        catalog_count = db.query(base.Product).filter(base.Product.supermarket == "REWE").count()
        assert catalog_count >= 1000, f"Expected committed REWE snapshot, got {catalog_count}"
        adapter = base.CatalogAdapter(db)
        basket_adapter = base._CachedCatalogAdapter(adapter)

        total = matched = 0
        missing = {}
        selected_candidates = Counter()
        per_recipe = {}
        for recipe, ingredients in RECIPES.items():
            found = []
            absent = []
            for ingredient in ingredients:
                total += 1
                rows = adapter.search(ingredient)
                valid = [
                    row for row in rows
                    if base.ingredient_product_match_type(
                        ingredient, base._product_title(row), row.get("category")
                    )
                ]
                if valid:
                    matched += 1
                    found.append(ingredient)
                    selected_candidates[ingredient] += len(valid)
                else:
                    absent.append(ingredient)
            per_recipe[recipe] = (len(found), len(ingredients))
            if absent:
                missing[recipe] = absent

        coverage = matched / max(total, 1)
        print(f"SECOND-WAVE RECIPES: {len(RECIPES)}")
        print(f"INGREDIENT MATCHING: {matched}/{total} ({coverage:.1%})")
        for recipe, (hit, count) in per_recipe.items():
            print(f"  RECIPE COVERAGE — {recipe}: {hit}/{count}")
        for recipe, absent in missing.items():
            print(f"  UNRESOLVED — {recipe}: {', '.join(absent)}")

        # Diagnose every unresolved ingredient against raw catalog titles before
        # changing aliases. This separates a true assortment gap from a strict
        # semantic-filter/search-index miss and prints evidence for review.
        all_catalog_rows = db.query(base.Product).filter(
            base.Product.supermarket == "REWE"
        ).all()
        broad_title_terms = {
            "bean sprouts": ("spross", "keim", "sprout"),
            "mussels": ("muschel", "mussel", "shellfish", "meeresfrucht", "frutti"),
        }
        for recipe, absent in missing.items():
            for ingredient in absent:
                terms = [term.lower().strip() for term in ingredient_search_terms(ingredient) if term.strip()]
                broad_terms = broad_title_terms.get(ingredient.lower().strip(), ())
                raw_hits = []
                for product in all_catalog_rows:
                    title = base._product_title({
                        "name_original": product.name_original,
                        "name": product.name_normalized,
                    }).lower()
                    matched_terms = [term for term in terms if term in title]
                    broad_hits_for_title = [term for term in broad_terms if term in title]
                    if matched_terms or broad_hits_for_title:
                        raw_hits.append((
                            product.name_original or product.name_normalized or "",
                            product.category or "",
                            product.price,
                            matched_terms,
                            broad_hits_for_title,
                        ))
                print(
                    f"  RAW CATALOG DIAGNOSTIC — {ingredient}: "
                    f"{len(raw_hits)} title hits; aliases={terms}; broad stems={list(broad_terms)}"
                )
                for title, category, price, matched_terms, broad_hits_for_title in raw_hits[:12]:
                    print(
                        f"    RAW CANDIDATE — {title} | {category} | "
                        f"price={price} | aliases={matched_terms} | broad={broad_hits_for_title}"
                    )
                if not raw_hits:
                    print(
                        f"    NO RAW TITLE EVIDENCE — no configured alias or broad title stem "
                        f"was found for {ingredient}; manual assortment review may still be needed"
                    )

        # This is a discovery/coverage gate, not an assertion that every niche
        # ingredient is sold in this supermarket snapshot.
        assert coverage >= 0.78, (
            f"Second-wave semantic coverage below 78%: {coverage:.1%}; "
            f"unresolved={missing}"
        )

        meals = [base._recipe_meal(name, ingredients) for name, ingredients in RECIPES.items()]
        servings = {meal["id"]: (3 if i % 5 == 0 else 2) for i, meal in enumerate(meals)}
        requirements = base.consolidate(meals, servings)
        keys = [(r["canonical_ingredient"], r["unit"]) for r in requirements]
        assert len(keys) == len(set(keys)), "Duplicate canonical ingredient/unit rows in 30-recipe basket"
        assert all(r["quantity"] > 0 and r["source_meals"] for r in requirements)
        shared = [r for r in requirements if len(r["source_meals"]) >= 3]
        assert shared, "Expected shared ingredients in the 30-recipe plan"

        basket_checks = 0
        unmatched = Counter()
        totals = {}
        for strategy in ("maximum-savings", "best-value", "premium", "plan-efficiency"):
            basket = base.build_basket(requirements, basket_adapter, strategy)
            assert len(basket) == len(requirements), f"{strategy}: dropped basket rows"
            seen = set()
            for row in basket:
                basket_checks += 1
                key = (row["canonical_ingredient"], row["unit"])
                assert key not in seen, f"{strategy}: duplicate basket row {key}"
                seen.add(key)
                product = row.get("product")
                if row["match_status"] == "unmatched":
                    unmatched[row["ingredient"]] += 1
                    assert product is None
                    continue
                if row["match_status"] == "covered":
                    continue
                assert product is not None
                title = base._product_title(product)
                match_type = base.ingredient_product_match_type(
                    row["ingredient"], title, product.get("category")
                )
                assert match_type is not None, (
                    f"{strategy}: false-positive product selected for {row['ingredient']}: {title}"
                )
                assert float(product.get("price") or 0) > 0
                assert int(row.get("packs") or 0) >= 1
                assert float(row.get("checkout_cost") or 0) > 0
                assert float(row.get("consumed_cost") or 0) <= float(row.get("checkout_cost") or 0) + 0.01
                profile = (product.get("intelligence") or {})
                assert not profile.get("is_complete_meal"), (
                    f"{strategy}: complete meal selected as ingredient for {row['ingredient']}: {title}"
                )
            totals[strategy] = round(sum(float(r.get("checkout_cost") or 0) for r in basket), 2)

        print(f"CONSOLIDATED BASKET: {len(requirements)} unique ingredient/unit rows")
        print(f"SHARED INGREDIENTS: {len(shared)} used by >=3 recipes")
        print(f"BASKET DECISIONS: {basket_checks} across 4 strategies")
        print(f"UNMATCHED REQUIREMENTS: {dict(unmatched)}")
        print(f"STRATEGY CHECKOUT ESTIMATES: {totals}")
        # Some ingredients (e.g. specialist vine leaves/lemongrass) may not
        # exist in the imported catalog; keep those visible rather than
        # accepting a semantically unrelated substitute.
        unmatched_ratio = sum(unmatched.values()) / max(basket_checks, 1)
        assert unmatched_ratio <= 0.22, (
            f"Too many unmatched basket decisions: {unmatched_ratio:.1%}; {dict(unmatched)}"
        )

        # New German aliases must be precise and must not collapse related foods.
        alias_expectations = {
            "goat cheese": "ziegenkäse",
            "sardine": "sardinen",
            "grape leaves": "weinblätter",
        }
        for ingredient, german_term in alias_expectations.items():
            terms = ingredient_search_terms(ingredient)
            assert any(german_term in term for term in terms), (ingredient, terms)
        precise_negative_cases = [
            ("sardine", "REWE Sardellenfilets in Öl", "fleisch-wurst-fisch"),
            ("goat cheese", "REWE Ziegenmilch 1l", "kaese-eier-molkerei"),
            ("grape leaves", "REWE Weintrauben kernlos 500g", "obst-gemuese"),
        ]
        for ingredient, title, category in precise_negative_cases:
            assert base.ingredient_product_match_type(ingredient, title, category) is None, (
                f"Related-but-different product matched: {ingredient} -> {title}"
            )
        print("GERMAN SPECIALTY ALIASES + RELATED-FOOD NEGATIVES: PASS")

        # Adversarial title tests: flavor/ingredient co-occurrence must not
        # convert a prepared beverage/snack into a fresh ingredient.
        negative_cases = [
            ("mango", "Alpro Haferdrink Mango 1l", "kaese-eier-molkerei"),
            ("peanut butter", "Ben & Jerry's Eis Peanut Butter Cup 465ml", "tiefkuehlkost"),
            ("chicken", "Instant Ramen Chicken Flavour 85g", "fertiggerichte-konserven"),
            ("coconut milk", "Alpro Kokosdrink 1l", "kaese-eier-molkerei"),
        ]
        for ingredient, title, category in negative_cases:
            assert base.ingredient_product_match_type(ingredient, title, category) is None, (
                f"Adversarial false positive: {ingredient} matched {title}"
            )
        print(f"ADVERSARIAL NEGATIVE CASES: {len(negative_cases)} passed")
        print("SECOND-WAVE SEMANTIC QA: PASS")
    finally:
        db.close()

if __name__ == "__main__":
    main()
