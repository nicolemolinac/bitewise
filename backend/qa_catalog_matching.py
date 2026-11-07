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
from app.main import CatalogAdapter


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
        assert by_id["shrimp-raw"]["ingredient_match_type"] == "exact"
        assert by_id["shrimp-raw"]["intelligence"]["culinary_role"] == "protein"
        assert by_id["shrimp-cooked"]["intelligence"]["product_type"] == "prepared_component"
        assert by_id["shrimp-cooked"]["intelligence"]["convenience_level"] == 4

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
