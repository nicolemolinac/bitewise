"""Optional local semantic retrieval over the REWE catalog.

Product vectors are indexed once and persisted in SQL. Query vectors are computed
locally and cached; no Gemini/API calls are made by this module.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import and_

from .database import Product, ProductSemanticEmbedding
from .ingredient_intelligence import _form_compatible, normalize_text

logger = logging.getLogger(__name__)
MODEL_NAME = os.getenv("BITEWISE_EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
BACKEND_DIR = Path(__file__).resolve().parents[1]


def product_embedding_text(product: Product) -> str:
    fields = [
        product.name_original,
        product.translated_name,
        product.name_normalized,
        product.brand,
        product.category,
    ]
    text = " | ".join(str(value).strip() for value in fields if str(value or "").strip())
    return "passage: " + text[:1200]


def _query_text(ingredient: str, intelligence: Any = None) -> str:
    profile = intelligence if isinstance(intelligence, dict) else {}
    fields = [
        ingredient,
        profile.get("canonical"),
        profile.get("name_en"),
        profile.get("name_de"),
        profile.get("name_es"),
        profile.get("form"),
        profile.get("culinary_role"),
        profile.get("preparation"),
    ]
    for key in ("aliases", "search_terms", "translations", "allowed_substitutions"):
        values = profile.get(key, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            fields.extend(values[:12])
    return "query: " + " | ".join(str(value).strip() for value in fields if str(value or "").strip())[:1200]


@lru_cache(maxsize=1)
def _model():
    # FastEmbed uses a compact ONNX runtime model; no PyTorch/GPU is required.
    os.environ.setdefault("HF_HOME", str(BACKEND_DIR / "data" / "models" / "huggingface"))
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL_NAME)


@lru_cache(maxsize=512)
def _cached_query_vector(query_text: str) -> tuple[float, ...]:
    vector = next(iter(_model().embed([query_text])))
    return tuple(float(value) for value in vector)


def index_rewe_products(db, batch_size: int = 128, force: bool = False) -> dict:
    """Incrementally embed new/changed REWE products and persist their vectors."""
    products = db.query(Product).filter(Product.supermarket == "REWE").all()
    existing = {
        row.product_id: row
        for row in db.query(ProductSemanticEmbedding).filter_by(model_name=MODEL_NAME).all()
    }
    pending = []
    for product in products:
        document = product_embedding_text(product)
        digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
        old = existing.get(product.id)
        if force or old is None or old.content_hash != digest or old.model_name != MODEL_NAME:
            pending.append((product, document, digest))

    indexed = 0
    for start in range(0, len(pending), max(1, batch_size)):
        batch = pending[start:start + max(1, batch_size)]
        vectors = list(_model().embed([document for _, document, _ in batch], batch_size=batch_size))
        for (product, _, digest), vector in zip(batch, vectors):
            row = existing.get(product.id)
            if row is None:
                row = ProductSemanticEmbedding(product_id=product.id, model_name=MODEL_NAME,
                                                content_hash=digest, vector_json="[]")
                db.add(row)
            row.model_name = MODEL_NAME
            row.content_hash = digest
            row.vector_json = json.dumps([float(value) for value in vector], separators=(",", ":"))
            indexed += 1
        db.commit()
    return {
        "model": MODEL_NAME,
        "products_seen": len(products),
        "products_indexed": indexed,
        "products_already_indexed": len(products) - len(pending),
        "total_embeddings": len(existing) + indexed,
    }


def semantic_product_candidates(db, ingredient: str, intelligence: Any = None,
                                limit: int = 5, minimum_score: float = 0.78) -> list[dict]:
    """Return review-only semantic candidates; callers must not auto-add these."""
    indexed_count = db.query(ProductSemanticEmbedding).filter_by(model_name=MODEL_NAME).count()
    if indexed_count == 0:
        return []
    try:
        query = _query_text(ingredient, intelligence)
        query_vector = np.asarray(_cached_query_vector(query), dtype=np.float32)
        rows = (
            db.query(Product, ProductSemanticEmbedding)
            .join(ProductSemanticEmbedding, ProductSemanticEmbedding.product_id == Product.id)
            .filter(and_(Product.supermarket == "REWE",
                         ProductSemanticEmbedding.model_name == MODEL_NAME))
            .all()
        )
        if not rows:
            return []
        matrix = np.asarray([json.loads(embedding.vector_json) for _, embedding in rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1) * max(float(np.linalg.norm(query_vector)), 1e-12)
        scores = np.divide(matrix @ query_vector, norms, out=np.zeros(len(rows), dtype=np.float32), where=norms > 0)
        profile = intelligence if isinstance(intelligence, dict) else {}
        form = str(profile.get("form") or "")
        ranked = []
        for index in np.argsort(scores)[::-1]:
            score = float(scores[index])
            if score < minimum_score:
                break
            product, _ = rows[int(index)]
            title = " ".join(str(value or "") for value in (
                product.name_original, product.name_normalized, product.translated_name
            ))
            if not _form_compatible(form, normalize_text(title)):
                continue
            if product.price is None or str(product.availability or "").lower() in {
                "unavailable", "out_of_stock", "not_available", "discontinued"
            }:
                continue
            ranked.append({
                "id": product.id,
                "supermarket": product.supermarket,
                "external_id": product.external_id,
                "ingredient": product.ingredient,
                "name_original": product.name_original,
                "name_normalized": product.name_normalized,
                "translated_name": product.translated_name,
                "brand": product.brand,
                "category": product.category,
                "package_size": product.package_size,
                "package_unit": product.package_unit,
                "price": product.price,
                "price_per_unit": product.price_per_unit,
                "currency": product.currency,
                "product_url": product.product_url,
                "image_url": product.image_url,
                "availability": product.availability,
                "postcode_context": product.postcode_context,
                "last_checked_at": product.last_checked_at,
                "ingredient_match_type": "semantic_candidate",
                "semantic_similarity": round(score, 4),
            })
            if len(ranked) >= max(1, limit):
                break
        return ranked
    except Exception as exc:
        logger.warning("Local REWE semantic search unavailable; using lexical matching only: %s", exc)
        return []
