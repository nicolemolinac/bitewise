"""Regression QA: the full REWE catalog and Product Intelligence drive basket matching.

Uses a temporary SQLite database only. No REWE requests, scraper, image process,
or user database are touched.
"""
import os
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-catalog-matching-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "catalog.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "false"

from app.database import Base, Product, ProductIntelligence, SessionLocal, engine
from fastapi import HTTPException
from app.main import CatalogAdapter, PurchaseIn, purchase


def add_product(db, external_id, title, ingredient="shrimp", price=2.5, category=None):
    row = Product(
        supermarket="REWE",
        external_id=external_id,
        ingredient=ingredient,
        name_original=title,
        name_normalized=title.lower(),
        package_size=200,
        package_unit="g",
        category=category,
        price=price,
        price_per_unit=price / 200,
        availability="available",
    )
    db.add(row)
    db.flush()
    return row


def main():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        # More than 40 catalog rows deliberately carry a misleading canonical
        # ingredient hint. Their actual titles do not contain a shrimp product.
        for index in range(55):
            add_product(db, f"noise-{index}", f"REWE Generic Pantry Item {index}")
        raw = add_product(db, "shrimp-raw", "REWE Garnelen roh 200 g")
        cooked = add_product(db, "shrimp-cooked", "REWE Garnelen vorgegart 200 g")
        meal = add_product(db, "shrimp-meal", "REWE Garnelen Curry Fertiggericht 400 g")
        pet = add_product(db, "pet-chicken", "REWE Huhn Katzenfutter 200 g", category="tierbedarf")
        misleading_beverage = add_product(
            db, "misleading-cola", "Coca-Cola Zero 1 l",
            ingredient="milk", price=1.2, category="getraenke-genussmittel",
        )
        sugar_free_drink = add_product(
            db, "sugar-free-drink", "7UP Zero Zucker 440ml",
            ingredient="sugar", price=1.2, category="getraenke-genussmittel",
        )
        flavored_drink = add_product(
            db, "flavored-drink", "Active O2 Apfel-Kiwi 0,75l",
            ingredient="apple", price=1.2, category="getraenke-genussmittel",
        )
        candy = add_product(
            db, "low-sugar-candy", "ahead Low Sugar Gummies Sweet Cherries 50g",
            ingredient="sugar", price=1.2, category="suesses-salziges",
        )
        wine = add_product(
            db, "cooking-wine", "1112 Weißwein Blanc de Noirs trocken 0,75l",
            ingredient="wine", price=4.99, category="getraenke-genussmittel",
        )
        sugar = add_product(db, "real-sugar", "REWE Zucker 1 kg", ingredient="wrong-hint")
        ketchup = add_product(
            db, "tomato-ketchup", "REWE Tomaten Ketchup 500ml",
            ingredient="tomato", price=1.5, category="oele-sossen-gewuerze",
        )
        fresh_tomato = add_product(
            db, "fresh-tomato", "REWE Rispentomaten 500g",
            ingredient="tomato", category="obst-gemuese",
        )
        ginger_juice = add_product(
            db, "ginger-juice", "Alnavit Bio Ingwer Saft 0,2l",
            ingredient="ginger", price=4.99, category="getraenke-genussmittel",
        )
        ginger_soda = add_product(
            db, "ginger-soda", "Bionade Bio Ingwer-Orange 12x0,33l",
            ingredient="ginger", price=9.99, category="getraenke-genussmittel",
        )
        milk_chocolate = add_product(
            db, "milk-chocolate", "REWE Vollmilch Schokolade 100g",
            ingredient="milk", price=1.2, category="suesses-salziges",
        )
        sour_cream_chips = add_product(
            db, "sour-cream-chips", "Saltletts Sour Cream & Onion Chips 130g",
            ingredient="cream", price=1.5, category="suesses-salziges",
        )
        plain_almonds = add_product(
            db, "plain-almonds", "Seeberger Mandeln 200g",
            ingredient="almond", price=2.5, category="suesses-salziges",
        )
        tomato_soup = add_product(
            db, "tomato-soup", "Erasco Tomaten-Cremesuppe 390ml",
            ingredient="tomato", price=1.99, category="fertiggerichte-konserven",
        )
        potato_salad = add_product(
            db, "potato-salad", "Golßener Klassischer Kartoffelsalat 400g",
            ingredient="potato", price=2.5, category="fertiggerichte-konserven",
        )
        frozen_curry = add_product(
            db, "frozen-curry", "Frosta Rotes Curry mit Hähnchen und Reis 375g",
            ingredient="chicken", price=3.69, category="tiefkuehlkost",
        )
        chicken_nuggets = add_product(
            db, "chicken-nuggets", "ja! Chicken Nuggets 500g",
            ingredient="chicken", price=3.99, category="tiefkuehlkost",
        )
        db.add(ProductIntelligence(
            product_id=meal.id,
            product_type="ready_meal",
            culinary_role="complete_meal",
            dish_families_json='["curry"]',
            preparation_state="ready_to_heat",
            storage_type="chilled",
            convenience_level=5,
            is_complete_meal=True,
            confidence=0.99,
            evidence_json='["qa-complete-meal"]',
            classifier_version="qa",
        ))
        db.commit()

        candidates = CatalogAdapter(db).search("shrimp")
        by_id = {item["external_id"]: item for item in candidates}

        assert "shrimp-raw" in by_id, "German alias Garnelen must match English shrimp"
        assert "shrimp-cooked" in by_id, "Prepared protein components should remain usable"
        assert "shrimp-meal" not in by_id, "A complete ready meal must not match a recipe ingredient"
        assert len(candidates) == 2, "Misleading Product.ingredient labels must not create false matches"
        assert all(item["external_id"] != "pet-chicken" for item in candidates), (
            "Pet food containing an ingredient word must never match a recipe ingredient"
        )
        sugar_candidates = CatalogAdapter(db).search("sugar")
        sugar_ids = {item["external_id"] for item in sugar_candidates}
        assert "real-sugar" in sugar_ids
        assert "sugar-free-drink" not in sugar_ids, (
            "A sugar-free beverage must not satisfy a recipe's sugar requirement"
        )
        assert "low-sugar-candy" not in sugar_ids, (
            "A confectionery product must not satisfy a raw sugar ingredient requirement"
        )
        apple_candidates = CatalogAdapter(db).search("apple")
        assert all(item["external_id"] != "flavored-drink" for item in apple_candidates), (
            "Fruit flavor in a drink must not match the whole fruit ingredient"
        )
        wine_candidates = CatalogAdapter(db).search("white wine")
        assert any(item["external_id"] == "cooking-wine" for item in wine_candidates), (
            "Actual cooking wine must remain searchable as a recipe ingredient"
        )
        tomato_candidates = CatalogAdapter(db).search("tomato")
        tomato_matches = {item["external_id"]: item["ingredient_match_type"] for item in tomato_candidates}
        assert tomato_matches.get("fresh-tomato") == "exact"
        assert tomato_matches.get("tomato-ketchup") is None, (
            "Ketchup must not be offered as fresh tomato or an equivalent cooking substitute"
        )

        ginger_candidates = CatalogAdapter(db).search("ginger")
        ginger_ids = {item["external_id"] for item in ginger_candidates}
        assert "ginger-juice" not in ginger_ids
        assert "ginger-soda" not in ginger_ids, (
            "A drink-aisle product containing ginger must not replace fresh ginger"
        )
        milk_ids = {item["external_id"] for item in CatalogAdapter(db).search("milk")}
        assert "milk-chocolate" not in milk_ids, (
            "Milk chocolate must not satisfy a recipe's milk requirement"
        )
        cream_ids = {item["external_id"] for item in CatalogAdapter(db).search("cream")}
        assert "sour-cream-chips" not in cream_ids, (
            "Sour-cream-flavoured snacks must not satisfy a cream requirement"
        )
        almond_ids = {item["external_id"] for item in CatalogAdapter(db).search("almond")}
        assert "plain-almonds" in almond_ids, (
            "Plain nuts in the snack aisle remain valid culinary ingredients"
        )

        assert "tomato-soup" not in {item["external_id"] for item in tomato_candidates}, (
            "Prepared tomato soup must not satisfy a raw tomato requirement"
        )
        potato_ids = {item["external_id"] for item in CatalogAdapter(db).search("potato")}
        assert "potato-salad" not in potato_ids, (
            "Prepared potato salad must not be matched as raw potatoes"
        )

        chicken_candidates = CatalogAdapter(db).search("chicken")
        chicken_ids = {item["external_id"] for item in chicken_candidates}
        assert "frozen-curry" not in chicken_ids, (
            "A frozen composed meal must not satisfy a raw chicken requirement"
        )
        assert "chicken-nuggets" in chicken_ids, (
            "Prepared protein components should remain available as recipe shortcuts"
        )
        assert all(item["external_id"] != "pet-chicken" for item in chicken_candidates), (
            "German Huhn in a pet-food title must not match a chicken recipe ingredient"
        )
        assert by_id["shrimp-raw"]["ingredient_match_type"] == "exact"
        assert by_id["shrimp-raw"]["intelligence"]["culinary_role"] == "protein"
        assert by_id["shrimp-cooked"]["intelligence"]["product_type"] == "prepared_component"
        assert by_id["shrimp-cooked"]["intelligence"]["convenience_level"] == 4

        # Purchase must never use the imported Product.ingredient hint as a
        # canonical pantry ingredient when the SKU title does not support it.
        try:
            purchase(PurchaseIn(product_id=misleading_beverage.id, packs=1))
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("A drink with a misleading 'milk' hint must not enter Pantry")
        try:
            purchase(PurchaseIn(product_id=pet.id, packs=1, ingredient="chicken"))
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("Pet food must never enter the ingredient Pantry")

        # The matcher is not limited to the first 40 rows in insertion order.
        assert raw.id > 40 and cooked.id > 40
        print(
            "Catalog matching QA PASS: complete-catalog alias search, strict title "
            "validation, Product Intelligence filtering, and prepared-component support"
        )
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


if __name__ == "__main__":
    main()
