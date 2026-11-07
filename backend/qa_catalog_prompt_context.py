"""Regression QA for catalog context supplied to both Gemini service paths.

Uses an isolated SQLite database. No Gemini API calls or REWE network requests.
"""
import os
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-catalog-prompt-context-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "context.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "false"

from app.database import Base, Product, ProductIntelligence, SessionLocal, engine
from app import server
from app.ai.gemini import _shopping_context
from app.ai.gemini_efficient import _catalog_context


def add_product(db, external_id, title, ingredient, category, price=1.5):
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
        availability="unknown",
    )
    db.add(row)
    db.flush()
    # Simulate a persisted profile created before the beverage/snack taxonomy.
    db.add(ProductIntelligence(
        product_id=row.id,
        product_type="ingredient",
        culinary_role="ingredient",
        dish_families_json="[]",
        preparation_state="unknown",
        storage_type="ambient",
        convenience_level=1,
        is_complete_meal=False,
        confidence=0.58,
        evidence_json="[]",
        classifier_version="1.1.0",
    ))
    return row


def main():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        add_product(db, "zero-sugar-drink", "REWE Lemon Zero Zucker 500ml",
                    "sugar", "getraenke-genussmittel")
        add_product(db, "fruit-flavor-drink", "REWE Apfel-Kiwi Drink 500ml",
                    "apple", "getraenke-genussmittel")
        add_product(db, "low-sugar-candy", "REWE Low Sugar Candy Bar 45g",
                    "sugar", "suesses-salziges")
        add_product(db, "garlic", "REWE Knoblauch 200g",
                    "garlic", "obst-gemuese")
        add_product(db, "chicken-recipe-mix", "Knorr Fix Hähnchen Curry 36g",
                    "chicken", "oele-sossen-gewuerze")
        add_product(db, "protein-bar", "Premier Protein Riegel Chocolate Caramel 40g",
                    "chocolate", "kaese-eier-molkerei")
        add_product(db, "rice-pudding", "Dr. Oetker High Protein Milchreis 400g",
                    "rice", "kaese-eier-molkerei")
        add_product(db, "tomato-soup", "Erasco Tomaten-Cremesuppe 390ml",
                    "tomato", "fertiggerichte-konserven")
        add_product(db, "potato-salad", "Golßener Kartoffelsalat 400g",
                    "potato", "fertiggerichte-konserven")
        db.commit()

        ingredient_context = _catalog_context("simple dinner", limit=60)
        assert "garlic" in ingredient_context
        assert "sugar" not in ingredient_context, (
            "Sugar-free drinks and candy must not be sent as sugar ingredient signals"
        )
        assert "apple" not in ingredient_context, (
            "Fruit-flavored beverages must not be sent as fresh fruit ingredient signals"
        )
        assert "chicken" not in ingredient_context, (
            "A branded recipe-mix sachet must not be sent as raw chicken ingredient evidence"
        )
        assert "chocolate" not in ingredient_context, (
            "A protein bar must not be sent as raw chocolate ingredient evidence"
        )
        for forbidden in ("rice", "tomato", "potato"):
            assert forbidden not in ingredient_context, (
                f"Prepared desserts/soups/salads must not send {forbidden} as raw ingredient context"
            )

        adapter = server.main_module.CatalogAdapter(db)
        assert not any(
            item["external_id"] == "zero-sugar-drink"
            for item in adapter.search("sugar")
        ), "Production catalog matching must reject sugar-free beverages"
        assert not any(
            item["external_id"] == "fruit-flavor-drink"
            for item in adapter.search("apple")
        ), "Production catalog matching must reject fruit-flavored drinks"

        assert not any(
            item["external_id"] == "chicken-recipe-mix"
            for item in adapter.search("chicken")
        ), "Production catalog matching must reject branded recipe-mix sachets as raw chicken"

        assert not any(
            item["external_id"] == "protein-bar"
            for item in adapter.search("chocolate")
        ), "Production catalog matching must reject protein bars as raw chocolate"

        for ingredient, blocked_id in (
            ("rice", "rice-pudding"),
            ("tomato", "tomato-soup"),
            ("potato", "potato-salad"),
        ):
            assert not any(
                item["external_id"] == blocked_id
                for item in adapter.search(ingredient)
            ), f"Production catalog matching must reject prepared {blocked_id}"

        pantry, catalog, preferences = _shopping_context()
        catalog_text = " ".join(catalog).lower()
        assert "knoblauch" in catalog_text
        assert "zero zucker" not in catalog_text
        assert "apfel-kiwi drink" not in catalog_text
        assert "candy bar" not in catalog_text
        assert "milchreis" not in catalog_text
        assert "tomaten-cremesuppe" not in catalog_text
        assert "kartoffelsalat" not in catalog_text

        # A real sugar SKU remains eligible; the earlier false positives do not
        # suppress a legitimate ingredient candidate.
        add_product(db, "real-sugar", "REWE Zucker 1kg",
                    "sugar", "kochen-backen")
        db.commit()
        ingredient_context = _catalog_context("simple dinner", limit=60)
        assert "sugar" in ingredient_context

        print("Gemini catalog context QA PASS: canonical titles only, current taxonomy, beverage/snack exclusion")
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


if __name__ == "__main__":
    main()
