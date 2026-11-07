"""Real REWE snapshot ingredient-matching QA across the complete catalog.

Runs read-only searches against a disposable SQLite import of the committed
11,969-row snapshot. No network, scraper, Gemini, user DB or image job is used.
"""
import os
import re
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
    "yogurt", "vanilla", "spinach", "mushroom", "carrot", "olive oil", "bell pepper", "chocolate", "mustard", "red onion", "broccoli",
)

BLOCKED_TYPES = {"non_food", "beverage", "snack"}
BLOCKED_ROLES = {"soup", "salad", "dessert", "potato_side", "seasoning_mix", "topping", "filled_pasta"}
FINISHED_FOOD_MARKERS = (
    "chips", "cracker", "cookie", "keks", "praline", "bonbon",
    "pudding", "milchreis", "eiscreme", "tiramisu", "mousse",
    "cheesecake", "dessert", "ice cream",
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
                normalized_title = re.sub(r"[^a-z0-9äöüß]+", " ", title).strip()
                is_plant_milk_substitute = (
                    ingredient == "milk"
                    and item.get("ingredient_match_type") == "substitute"
                    and any(marker in f" {normalized_title} " for marker in (
                        " haferdrink ", " hafer drink ", " sojadrink ", " soja drink ",
                        " mandeldrink ", " mandel drink ", " kokosdrink ", " kokos drink ",
                        " reisdrink ", " reis drink ", " erbsendrink ", " mandelmilch ",
                    ))
                )
                assert product_type not in BLOCKED_TYPES or is_plant_milk_substitute, (
                    f"{ingredient!r} matched blocked product type {product_type} without a valid milk-substitute exception: {title}"
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

        # Protein words in flavors, instant meals, recipe-mix sachets and
        # prepared snacks must not be mistaken for raw chicken.
        chicken_candidates = adapter.search("chicken")
        for item in chicken_candidates:
            title = str(item.get("name_original") or "").lower()
            profile = item.get("intelligence") or {}
            assert not any(marker in title for marker in (
                "flavour", "flavor", "taste", "geschmack",
            )), f"Chicken flavor product matched as chicken meat: {title}"
            prepared_shortcut_markers = (
                "nugget", "gyoza", "dumpling", "onigiri",
                "meatball", "frikadellen", "burger", "patties",
            )
            if any(marker in title for marker in prepared_shortcut_markers):
                assert item.get("ingredient_match_type") == "substitute", (
                    f"Prepared chicken shortcut must not be an exact raw-chicken match: {title}"
                )
            assert not any(marker in title for marker in (
                "noodles", "noodle", "ramen", "tteokbokki",
                "sauce", "soße", "sosse", "paste", "gewürzpaste",
                "gewuerzpaste", "currypaste", "würzpaste", "wuerzpaste",
            )), f"Chicken-flavored meal/sauce matched as raw chicken: {title}"
            assert profile.get("culinary_role") != "seasoning_mix", (
                f"Chicken seasoning mix matched as raw chicken: {title}"
            )
            assert profile.get("product_type") != "snack", (
                f"Meat snack matched as raw chicken: {title}"
            )

        # Chocolate is a valid cooking ingredient; a chocolate dessert is not.
        chocolate_titles = [
            str(item.get("name_original") or "").lower()
            for item in adapter.search("chocolate")
        ]
        assert not any("tiramisu" in title for title in chocolate_titles), (
            "Chocolate search must not return a finished chocolate tiramisu"
        )
        assert any(
            any(marker in title for marker in ("backschokolade", "kuvertüre", "kuvertuere", "kakaopulver"))
            for title in chocolate_titles
        ), "Chocolate search must retain real baking/cooking chocolate products"

        # Filled pasta must not leak into generic pasta matches, but it is
        # valid when a recipe explicitly requests tortellini.
        generic_pasta = adapter.search("pasta")
        assert not any(
            "tortellini" in str(item.get("name_original") or "").lower()
            or (item.get("intelligence") or {}).get("culinary_role") == "filled_pasta"
            for item in generic_pasta
        ), "Filled pasta must not be a generic dry-pasta match"
        tortellini = adapter.search("tortellini")
        assert any(
            "tortellini" in str(item.get("name_original") or "").lower()
            and not (item.get("intelligence") or {}).get("is_complete_meal")
            for item in tortellini
        ), "Explicit tortellini search must retain genuine tortellini products"

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
