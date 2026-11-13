"""Catalog-first supermarket discovery for convenient meal solutions.

This module ranks real REWE catalog products locally. It does not call an LLM and
never treats a product as an ingredient substitute without recipe validation.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import or_

from .database import Product


def _normalise(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# Search-language bridges are concepts, not ingredient-specific matching rules.
# They make German supermarket naming discoverable from common English dish names.
_QUERY_EXPANSIONS = {
    "pizza": ("pizza", "pizza baguette", "pizzabaguette", "flammkuchen", "pizza kit", "pizzateig"),
    "chili con carne": ("chili con carne", "chili", "chili sin carne", "chili eintopf"),
    "french fries": ("pommes", "pommes frites", "backofen pommes"),
    "lasagna": ("lasagne", "lasagne fertig"),
    "burger": ("burger", "hamburger", "cheeseburger"),
    "curry": ("curry", "currygericht", "curry pfanne"),
}

_READY_MARKERS = (
    "fertiggericht", "fertigmen", "ready meal", "ready to eat", "verzehrfertig",
    "konserve", "dose", "eintopf", "suppe", "tk gericht", "tiefkuhlgericht",
    "mikrowellen", "pfannengericht", "menuschale",
)
_KIT_MARKERS = (
    "kit", "set", "basis", "backmischung", "pizzateig", "wrap kit",
    "kochbox", "gewurzmix",
)
_PREPARED_MARKERS = (
    "baguette", "flammkuchen", "pizza", "pommes", "gnocchi", "ravioli",
    "tortellini", "spatzle", "schnitzel", "falafel", "burger patty",
)
_EXCLUDE_MARKERS = (
    "hundefutter", "katzenfutter", "proteinpulver", "duft", "reiniger",
    "geschirrspul", "waschmittel",
)


def expand_catalog_query(query: str) -> list[str]:
    normal = _normalise(query)
    variants = list(_QUERY_EXPANSIONS.get(normal, ()))
    # Also recognise a dish inside natural-language prompts such as
    # "quick air-fryer chili con carne tonight" or "easy pizza for two".
    for concept, aliases in _QUERY_EXPANSIONS.items():
        if concept in normal and concept != normal:
            variants.extend(aliases)
    if normal and normal not in variants:
        variants.insert(0, normal)
    return list(dict.fromkeys(term for term in variants if term))


def _product_text(product: Any) -> str:
    return _normalise(" ".join(str(getattr(product, key, "") or "") for key in (
        "name_original", "name_normalized", "translated_name", "brand", "category", "ingredient"
    )))


def _convenience_type(text: str) -> str:
    if any(marker in text for marker in _READY_MARKERS):
        return "ready_meal"
    if any(marker in text for marker in _KIT_MARKERS):
        return "meal_kit"
    if any(marker in text for marker in _PREPARED_MARKERS):
        return "ready_to_cook"
    return "catalog_product"


def search_catalog_opportunities(db, query: str, limit: int = 12) -> dict:
    """Find useful supermarket shortcuts for a dish/search phrase from the full catalog."""
    query = str(query or "").strip()[:160]
    if len(_normalise(query)) < 2:
        return {"query": query, "products": [], "catalog_count": 0}
    variants = expand_catalog_query(query)
    token_set = {token for token in _normalise(query).split() if len(token) > 2}
    for variant in variants:
        token_set.update(token for token in _normalise(variant).split() if len(token) > 2)

    # Pull a broad but bounded lexical candidate pool from every searchable catalog field.
    clauses = []
    for term in variants[:8]:
        pattern = f"%{term}%"
        clauses.extend((
            Product.name_original.ilike(pattern),
            Product.name_normalized.ilike(pattern),
            Product.translated_name.ilike(pattern),
            Product.category.ilike(pattern),
            Product.ingredient.ilike(pattern),
        ))
    for token in sorted(token_set)[:8]:
        pattern = f"%{token}%"
        clauses.extend((Product.name_original.ilike(pattern), Product.category.ilike(pattern)))
    query_rows = db.query(Product).filter(Product.supermarket == "REWE").filter(or_(*clauses))
    catalog_count = db.query(Product).filter(Product.supermarket == "REWE").count()
    rows = query_rows.limit(500).all()

    ranked = []
    for product in rows:
        text = _product_text(product)
        if any(marker in text for marker in _EXCLUDE_MARKERS):
            continue
        phrase_hits = sum(1 for variant in variants if _normalise(variant) in text)
        token_hits = sum(1 for token in token_set if token in text.split())
        if not phrase_hits and not token_hits:
            continue
        kind = _convenience_type(text)
        # Ready meals and cook-at-home shortcuts are surfaced alongside raw ingredients,
        # but exact dish identity remains the strongest relevance signal.
        score = phrase_hits * 8 + token_hits * 1.5
        if kind == "ready_meal":
            score += 2.5
        elif kind == "meal_kit":
            score += 2.0
        elif kind == "ready_to_cook":
            score += 1.5
        if product.price is not None and product.price > 0:
            score += 0.25
        if product.availability in {"unavailable", "out_of_stock", "not_available", "discontinued"}:
            score -= 8
        ranked.append((score, product, kind))

    ranked.sort(key=lambda item: (
        -item[0],
        item[1].price is None,
        item[1].price if item[1].price is not None else float("inf"),
        item[1].name_original.casefold(),
    ))
    products = []
    seen = set()
    for score, product, kind in ranked:
        if product.id in seen:
            continue
        seen.add(product.id)
        products.append({
            "id": product.id,
            "name_original": product.name_original,
            "brand": product.brand,
            "category": product.category,
            "ingredient": product.ingredient,
            "package_size": product.package_size,
            "package_unit": product.package_unit,
            "price": product.price,
            "price_per_unit": product.price_per_unit,
            "product_url": product.product_url,
            "image_url": product.image_url,
            "availability": product.availability,
            "convenience_type": kind,
            "relevance_score": round(score, 2),
        })
        if len(products) >= max(1, min(int(limit), 30)):
            break
    return {
        "query": query,
        "catalog_count": catalog_count,
        "products": products,
        "source": "local_rewe_catalog",
    }
