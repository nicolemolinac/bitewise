"""Read-only diagnostics for ingredients that remain unmatched in saved REWE recipes.

Run from backend/: python diagnose_catalog_matches.py
This does not change the database, scrape REWE, or call Gemini.
"""
import json
from collections import defaultdict

from sqlalchemy import or_

# Import server first so CatalogAdapter uses the multilingual REWE matcher.
from app import server
from app.database import Product, ProductOverride, RecipeHistory, SessionLocal
from app.ingredient_aliases import ingredient_search_terms


def main():
    main_module = server.main_module
    db = SessionLocal()
    try:
        recipes = db.query(RecipeHistory).filter(
            RecipeHistory.record_type == "recipe",
            RecipeHistory.status.in_(["saved", "cooked"]),
        ).order_by(RecipeHistory.created_at.desc()).all()
        if not recipes:
            print("No saved full recipes found in recipe history.")
            return

        overrides = {row.ingredient: row.product_id for row in db.query(ProductOverride).all()}
        adapter = main_module.CatalogAdapter(db)
        pantry = main_module.pantry_snapshot(db)
        unmatched = defaultdict(lambda: {"count": 0, "units": set(), "recipes": set()})
        total_ingredients = 0
        matched_ingredients = 0

        for row in recipes:
            try:
                meal = json.loads(row.meal_json)
            except Exception:
                continue
            if not isinstance(meal, dict) or not meal.get("ingredients") or not meal.get("id"):
                continue
            requirements = main_module.consolidate(
                [meal], {meal["id"]: float(meal.get("base_servings", 2) or 2)}
            )
            basket = main_module.build_basket(
                requirements, adapter, "best-value",
                overrides=overrides, pantry=pantry,
            )
            for item in basket:
                total_ingredients += 1
                if item.get("match_status") in {"matched", "substituted", "covered"}:
                    matched_ingredients += 1
                    continue
                name = str(item.get("ingredient") or "unknown")
                record = unmatched[name]
                record["count"] += 1
                record["units"].add(str(item.get("unit") or ""))
                record["recipes"].add(str(meal.get("name") or row.name))

        print(f"Saved recipes checked: {len(recipes)}")
        print(f"Ingredient rows: {total_ingredients}")
        print(f"Resolved: {matched_ingredients}")
        print(f"Unmatched: {total_ingredients - matched_ingredients}")
        if total_ingredients:
            print(f"Coverage: {matched_ingredients / total_ingredients:.1%}")
        if not unmatched:
            print("All saved recipe ingredients resolve to REWE products or pantry.")
            return

        print("\nUNMATCHED INGREDIENTS (most frequent first)")
        for ingredient, record in sorted(
            unmatched.items(), key=lambda item: (-item[1]["count"], item[0].casefold())
        )[:30]:
            terms = ingredient_search_terms(ingredient)
            clauses = []
            for term in terms:
                pattern = f"%{term}%"
                clauses.extend([
                    Product.ingredient.ilike(pattern),
                    Product.name_normalized.ilike(pattern),
                    Product.name_original.ilike(pattern),
                    Product.translated_name.ilike(pattern),
                ])
            candidates = db.query(Product).filter(or_(*clauses)).limit(8).all() if clauses else []
            print(
                f"\n- {ingredient} | occurrences={record['count']} "
                f"| units={', '.join(sorted(record['units']))}"
            )
            print("  recipes: " + "; ".join(sorted(record["recipes"])[:5]))
            print("  search terms: " + ", ".join(terms[:10]))
            if candidates:
                print("  raw catalog candidates (before strict title/unit/price checks):")
                for product in candidates:
                    print(
                        f"    • {product.name_original} | ingredient={product.ingredient} "
                        f"| pack={product.package_size:g} {product.package_unit} "
                        f"| price={product.price}"
                    )
            else:
                print("  raw catalog candidates: none")
    finally:
        db.close()


if __name__ == "__main__":
    main()
