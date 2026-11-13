"""Offline QA for the local REWE semantic index (no model download or API calls)."""
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Product, ProductSemanticEmbedding
import app.semantic_catalog as semantic


class FakeEmbeddingModel:
    def embed(self, texts, batch_size=32):
        for _ in texts:
            yield np.asarray([1.0, 0.0, 0.0], dtype=np.float32)


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
        db.add_all([fries, chips])
        db.commit()

        first = semantic.index_rewe_products(db, batch_size=2)
        assert first["products_seen"] == 2
        assert first["products_indexed"] == 2
        assert db.query(ProductSemanticEmbedding).count() == 2

        second = semantic.index_rewe_products(db, batch_size=2)
        assert second["products_indexed"] == 0
        assert second["products_already_indexed"] == 2

        semantic._INDEX_CACHE = None
        candidates = semantic.semantic_product_candidates(
            db,
            "frozen french fries",
            {"canonical": "potato fries", "form": "frozen"},
            limit=5,
            minimum_score=0.5,
        )
        assert [row["id"] for row in candidates] == [fries.id]
        assert candidates[0]["ingredient_match_type"] == "semantic_candidate"

        fries.name_original = "REWE Backofen Pommes Frites 750g"
        fries.name_normalized = fries.name_original.casefold()
        db.commit()
        changed = semantic.index_rewe_products(db, batch_size=2)
        assert changed["products_indexed"] == 1

        db.delete(chips)
        db.commit()
        cleaned = semantic.index_rewe_products(db, batch_size=2)
        assert cleaned["total_embeddings"] == 1
        assert db.query(ProductSemanticEmbedding).count() == 1

        print("SEMANTIC CATALOG QA PASS: indexing, incremental updates, local retrieval, form safety, and stale-vector cleanup")
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
        semantic._INDEX_CACHE = None
        semantic._cached_query_vector.cache_clear()


if __name__ == "__main__":
    run()
