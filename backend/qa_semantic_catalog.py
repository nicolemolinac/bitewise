"""Offline QA for the local REWE semantic index (no model download or API calls)."""
import os
import tempfile
from pathlib import Path

_QA_DB_DIR = tempfile.TemporaryDirectory(prefix="bitewise-semantic-catalog-qa-")
os.environ["DATABASE_URL"] = ""
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_QA_DB_DIR.name) / "qa.sqlite")
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Product, ProductSemanticEmbedding, SessionLocal
import app.semantic_catalog as semantic


class FakeEmbeddingModel:
    def embed(self, texts, batch_size=32):
        for text in texts:
            value = str(text).casefold()
            if value.startswith("query:"):
                if "rolled oats" in value:
                    vector = [0.0, 1.0, 0.0]
                elif "white fish fillet" in value:
                    vector = [0.0, 0.0, 1.0]
                else:
                    vector = [1.0, 0.0, 0.0]
            elif "haferflocken" in value or "rolled oats" in value:
                vector = [0.0, 1.0, 0.0]
            elif "seelachsfilet" in value:
                vector = [0.0, 0.0, 1.0]
            elif "pommes" in value:
                vector = [1.0, 0.0, 0.0]
            else:
                vector = [0.0, 0.0, 0.0]
            yield np.asarray(vector, dtype=np.float32)


def _product(external_id, name, category):
    return Product(
        supermarket="REWE",
        external_id=external_id,
        ingredient="pommes frites",
        name_original=name,
        name_normalized=name.casefold(),
        category=category,
        package_size=750,
        package_unit="g",
        price=2.49,
        availability="available",
    )


def run():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    semantic._model = lambda: FakeEmbeddingModel()
    semantic._cached_query_vector.cache_clear()
    semantic._INDEX_CACHE = None

    try:
        fries = _product("fries-1", "REWE Pommes Frites 750g", "Tiefkühlkost")
        chips = _product("chips-1", "Pommes Frites Chips", "Snacks")
        potatoes = _product("potatoes-1", "REWE Speisekartoffeln 2kg", "Obst & Gemüse")
        oats = _product("oats-1", "REWE Bio Haferflocken zart 500g", "Brot-Cerealien-Aufstriche")
        oats.ingredient = "rolled oats"
        fish = _product("fish-1", "REWE Beste Wahl Alaska Seelachsfilet 400g", "Tiefkühlkost")
        fish.ingredient = "white fish fillet"
        db.add_all([fries, chips, potatoes, oats, fish])
        db.commit()

        first = semantic.index_rewe_products(db, batch_size=2)
        assert first["products_seen"] == 5
        assert first["products_indexed"] == 5
        assert db.query(ProductSemanticEmbedding).count() == 5

        second = semantic.index_rewe_products(db, batch_size=2)
        assert second["products_indexed"] == 0
        assert second["products_already_indexed"] == 5

        semantic._INDEX_CACHE = None
        candidates = semantic.semantic_product_candidates(
            db,
            "frozen french fries",
            {"canonical": "potato fries", "form": "frozen"},
            limit=5,
            minimum_score=0.5,
        )
        candidate_by_id = {row["id"]: row for row in candidates}
        assert set(candidate_by_id) == {fries.id, potatoes.id}
        assert candidate_by_id[fries.id]["ingredient_match_type"] == "semantic_candidate"
        assert candidate_by_id[potatoes.id]["semantic_match_type"] == "suggested_substitution"

        # A semantically similar product with no shared ingredient alias can
        # appear for user review when its form and REWE category are compatible.
        oat_suggestions = semantic.semantic_product_candidates(
            db, "rolled oats", {"canonical": "rolled oats", "form": "unspecified"},
            limit=5, minimum_score=0.5,
        )
        oats_suggestion = next(row for row in oat_suggestions if row["id"] == oats.id)
        assert oats_suggestion["ingredient_match_type"] == "semantic_candidate"
        assert oats_suggestion["semantic_match_type"] == "semantic_only"

        fish_suggestions = semantic.semantic_product_candidates(
            db, "white fish fillet", {"canonical": "white fish fillet", "form": "fresh"},
            limit=5, minimum_score=0.5,
        )
        frozen_fish = next(row for row in fish_suggestions if row["id"] == fish.id)
        assert frozen_fish["semantic_match_type"] == "suggested_substitution"

        fries.name_original = "REWE Backofen Pommes Frites 750g"
        fries.name_normalized = fries.name_original.casefold()
        db.commit()
        changed = semantic.index_rewe_products(db, batch_size=2)
        assert changed["products_indexed"] == 1

        db.delete(chips)
        db.commit()
        cleaned = semantic.index_rewe_products(db, batch_size=2)
        assert cleaned["total_embeddings"] == 4
        assert db.query(ProductSemanticEmbedding).count() == 4

        # The committed REWE snapshot is ~12k rows. Verify that the actual
        # indexer embeds every imported REWE product, not a capped sample.
        full_db = SessionLocal()
        try:
            full_count = full_db.query(Product).filter(Product.supermarket == "REWE").count()
            assert full_count >= 10000, (
                f"Expected the full committed REWE catalog (>=10,000 rows), got {full_count}"
            )
            full_index = semantic.index_rewe_products(full_db, batch_size=256)
            indexed_count = full_db.query(ProductSemanticEmbedding).filter(
                ProductSemanticEmbedding.model_name == semantic.MODEL_NAME
            ).count()
            assert full_index["products_seen"] == full_count
            assert full_index["total_embeddings"] == full_count
            assert indexed_count == full_count, (indexed_count, full_count)

            semantic._INDEX_CACHE = None
            full_candidates = semantic.semantic_product_candidates(
                full_db, "frozen french fries", {"form": "frozen"},
                limit=5, minimum_score=0.5,
            )
            assert any("Pommes Frites" in row["name_original"] for row in full_candidates), (
                "Full-catalog semantic retrieval did not recover a REWE fries product"
            )
            unchanged = semantic.index_rewe_products(full_db, batch_size=256)
            assert unchanged["products_indexed"] == 0
            print(
                f"FULL REWE SEMANTIC INDEX PASS: {full_count} products indexed and searched; "
                "incremental rerun indexed 0 unchanged products"
            )
        finally:
            full_db.close()
            semantic._INDEX_CACHE = None

        print("SEMANTIC CATALOG QA PASS: indexing, incremental updates, local retrieval, form safety, and stale-vector cleanup")
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
        semantic._INDEX_CACHE = None
        semantic._cached_query_vector.cache_clear()


if __name__ == "__main__":
    run()
