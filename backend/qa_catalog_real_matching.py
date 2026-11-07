"""Real REWE snapshot ingredient-matching QA across the complete catalog.

Runs read-only searches against a disposable SQLite import of the committed
11,969-row snapshot. No network, scraper, Gemini, user DB or image job is used.
"""
import os
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-real-catalog-match-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "catalog.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

from app.database import Product, SessionLocal
from app.main import CatalogAdapter


RAW_INGREDIENT_QUERIES = (
    "ginger", "milk", "cream", "tomato", "potato", "chicken",
    "almond", "sugar", "orange", "lemon", "rice", "pasta",
    "garlic", "onion", "salmon", "shrimp", "cheese", "butter",
    "yogurt", "vanilla", "spinach", "mushroom", "carrot", "olive oil", "bell pepper", "chocolate", "mustard", "red onion",
)

BLOCKED_TYPES = {"non_food", "beverage", "snack"}
BLOCKED_ROLES = {"soup", "salad", "dessert", "potato_side", "seasoning_mix", "topping"}
FINISHED_FOOD_MARKERS = (
    "schokolade", "chocolate", "chips", "cracker", "cookie", "keks",
    "praline", "bonbon", "pudding", "milchreis", "eiscreme",
)


def main():
    db = SessionLocal()
    try:
        total = db.query(Product).filter(Product.supermarket == "REWE").count()
        assert total >= 10000, f"Expected complete REWE snapshot, got {total}"
        adapter = CatalogAdapter(db)
        results = {}
        for ingredient in RAW_INGREDIENT_QUERIES:
            candidates = adapter.search(ingredient)
            results[ingredient] = len(candidates)
            for item in candidates:
                profile = item.get("intelligence") or {}
                title = str(item.get("name_original") or "").lower()
                category = str(item.get("category") or "")
                product_type = profile.get("product_type")
                role = profile.get("culinary_role")
                assert product_type not in BLOCKED_TYPES, (
                    f"{ingredient!r} matched blocked product type {product_type}: {title}"
                )
                assert role not in BLOCKED_ROLES, (
                    f"{ingredient!r} matched prepared {role}: {title}"
                )
                assert not profile.get("is_complete_meal"), (
                    f"{ingredient!r} matched a complete meal: {title}"
                )
                assert category != "getraenke-genussmittel", (
                    f"{ingredient!r} matched a beverage aisle SKU: {title}"
                )
                if any(marker in title for marker in FINISHED_FOOD_MARKERS):
                    raise AssertionError(
                        f"{ingredient!r} matched a finished snack/dessert: {title}"
                    )

        # Sanity: the full catalog must still yield genuine ingredient candidates.
        for ingredient in ("chicken", "tomato", "almond", "pasta", "milk", "mustard", "red onion"):
            assert results[ingredient] > 0, (
                f"Expected genuine catalog candidates for {ingredient!r}"
            )
        print(
            f"Real catalog ingredient matching PASS: {total} products scanned; "
            f"{len(RAW_INGREDIENT_QUERIES)} ingredient searches; "
            f"candidate counts={results}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
