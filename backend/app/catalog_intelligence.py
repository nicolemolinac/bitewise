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

_QUERY_STOPWORDS = {"a", "an", "and", "for", "two", "the", "tonight", "today", "quick", "quickly", "easy", "easiest", "simple", "healthy", "cheap", "budget", "meal", "recipe", "make", "cook", "cooking", "air", "fryer", "with", "of", "to", "in", "on", "my", "some", "please", "ich", "ein", "eine", "fur", "mit", "heute", "schnell", "einfach"}


def _normalise(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# Search-language bridges are concepts, not ingredient-specific matching rules.
# They make German supermarket naming discoverable from common English dish names.
_QUERY_EXPANSIONS = {
    "pizza": ("pizza", "pizza baguette", "pizzabaguette", "bistro baguette", "baguette pizza", "flammkuchen", "pizza kit", "pizzateig"),
    "chili con carne": ("chili con carne", "chili sin carne", "chili eintopf"),
    "french fries": ("pommes", "pommes frites", "backofen pommes"),
    "lasagna": ("lasagne", "lasagne fertig"),
    "burger": ("burger", "hamburger", "cheeseburger"),
    "curry": ("curry", "currygericht", "curry pfanne"),
}

_READY_MARKERS = (
    "fertiggericht", "fertigmen", "ready meal", "ready to eat", "verzehrfertig",
    "eintopf", "suppe", "tk gericht", "tiefkuhlgericht",
    "mikrowellen", "pfannengericht", "menuschale",
)
_KIT_MARKERS = (
    "pizza kit", "pizzakit", "taco kit", "wrap kit", "meal kit",
    "kochbox", "backmischung",
)
_PREPARED_MARKERS = (
    "baguette", "flammkuchen", "pizza", "pizzateig", "pizza teig", "pizza dough", "pommes",
    "gnocchi", "ravioli", "tortellini", "spatzle", "schnitzel",
    "falafel", "burger patty",
)
_EXCLUDE_MARKERS = (
    "hundefutter", "katzenfutter", "proteinpulver", "duft", "reiniger",
    "geschirrspul", "waschmittel", "fruchtgummi", "gummibonbon",
    "susswaren", "suesswaren", "nascherei", "gewurzsalz",
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


def _convenience_type(text: str, query: str = "", product: Any = None) -> str:
    name = _normalise(" ".join(str(getattr(product, key, "") or "") for key in (
        "name_original", "name_normalized", "translated_name"
    )))
    category = _normalise(getattr(product, "category", ""))
    # Retail taxonomy varies by source spelling and hierarchy. Match the
    # category family rather than a single exact label so child snacks and
    # confectionery never surface as full-meal alternatives.
    if any(marker in category for marker in (
        "baby", "kinder", "snack", "knabber", "suess", "suss", "salzig",
    )):
        return "catalog_product"
    # Dry "Fix" seasoning sachets often share the canned/ready-meal aisle;
    # classify them as components before using broad aisle metadata.
    if " fix " in f" {text} " or "gewurzmischung" in text or "wurzmittel" in category:
        return "prepared_component"
    # Tiny packs are usually snacks, toppings or seasoning sachets rather than
    # complete meals, even when their titles contain a dish word like "pizza".
    try:
        package_size = float(getattr(product, "package_size", 0) or 0)
        package_unit = _normalise(getattr(product, "package_unit", ""))
        if 0 < package_size < 100 and package_unit in {"g", "ml"}:
            return "catalog_product"
    except (TypeError, ValueError):
        pass
    # Explicit kits take precedence over broad ready-meal aisle labels.
    if any(marker in text for marker in _KIT_MARKERS):
        return "meal_kit"
    # A frozen/retail pizza is a complete meal; pizza dough and pizza kits
    # remain cook-at-home formats and are classified by the rules below.
    if any(marker in category for marker in ("baby-kind", "babynahrung", "kindernahrung", "baby food")):
        return "catalog_product"
    if (
        "pizza" in name
        and any(marker in category for marker in ("tiefkuhlkost", "tiefkuehlkost", "fertiggerichte", "ready meals"))
        and not any(marker in name for marker in (
            "pizzateig", "pizza teig", "pizza dough", "baguette", "pizza stange",
        ))
    ):
        return "ready_meal"
    # A finished Flammkuchen is a complete meal; its dough/base is a
    # cook-at-home component. Use product format and aisle together so a
    # chilled dough is not mistaken for a finished dish.
    if (
        "flammkuchen" in name
        and any(marker in category for marker in ("tiefkuhlkost", "tiefkuehlkost", "fertiggerichte", "ready meals"))
        and not any(marker in name for marker in ("teig", "boden", "backmischung"))
    ):
        return "ready_meal"
    if "gewurze" in category:
        return "prepared_component"
    # Product formats that still require cooking/heating outrank broad aisle
    # metadata such as "Fertiggerichte-Konserven".
    if any(marker in text for marker in _PREPARED_MARKERS):
        return "ready_to_cook"
    if any(marker in text for marker in _READY_MARKERS) or any(
        marker in category for marker in ("fertiggerichte", "fertigmahlzeiten", "ready meals")
    ):
        return "ready_meal"
    # A canned product is a complete meal only when the requested dish itself
    # matches its product title. Canned beans/tomatoes stay components.
    if any(marker in category for marker in ("konserven", "canned food")):
        requested_dish_match = any(
            len(_normalise(term).split()) >= 2 and _normalise(term) in name
            for term in expand_catalog_query(query)
        )
        return "ready_meal" if requested_dish_match else "prepared_component"
    return "catalog_product"


def _format_diversity_key(product: Any, convenience_type: str) -> str:
    """Group similar retail formats so one product family cannot fill the first screen."""
    name = _normalise(" ".join(str(getattr(product, key, "") or "") for key in (
        "name_original", "name_normalized", "translated_name"
    )))
    if convenience_type == "ready_to_cook":
        for markers, key in (
            (("flammkuchen", "flamkuchen"), "flatbread"),
            (("baguette",), "baguette"),
            (("pizzateig", "pizza dough", "teig"), "dough"),
            (("pommes", "frites"), "fries"),
            (("pizza",), "pizza"),
        ):
            if any(marker in name for marker in markers):
                return key
    return convenience_type


def search_catalog_opportunities(db, query: str, limit: int = 12) -> dict:
    """Find useful supermarket shortcuts for a dish/search phrase from the full catalog."""
    query = str(query or "").strip()[:160]
    if len(_normalise(query)) < 2:
        return {"query": query, "products": [], "catalog_count": 0}
    variants = expand_catalog_query(query)
    # Token overlap comes only from the user's words. Alias tokens are
    # searched as complete phrases below; otherwise a generic alias such as
    # "kit" could pull in an unrelated taco kit for a pizza query.
    token_set = {token for token in _normalise(query).split() if len(token) > 2 and token not in _QUERY_STOPWORDS}

    # Retrieve each retail-format alias independently. A single broad OR with
    # one global limit can fill its first 500 rows with generic "pizza" matches
    # and silently drop useful formats such as Bistro Baguette or Flammkuchen.
    candidate_rows = {}
    for term in variants[:8]:
        pattern = f"%{term}%"
        term_rows = db.query(Product).filter(
            Product.supermarket == "REWE",
            or_(
                Product.name_original.ilike(pattern),
                Product.name_normalized.ilike(pattern),
                Product.translated_name.ilike(pattern),
                Product.category.ilike(pattern),
                Product.ingredient.ilike(pattern),
            ),
        ).all()
        candidate_rows.update({row.id: row for row in term_rows})
    for token in sorted(token_set)[:8]:
        pattern = f"%{token}%"
        token_rows = db.query(Product).filter(
            Product.supermarket == "REWE",
            or_(Product.name_original.ilike(pattern), Product.category.ilike(pattern)),
        ).all()
        candidate_rows.update({row.id: row for row in token_rows})
    catalog_count = db.query(Product).filter(Product.supermarket == "REWE").count()
    rows = list(candidate_rows.values())

    # Add broad local-embedding candidates when the optional index exists. The
    # semantic layer is discovery-only; exact lexical evidence still dominates.
    semantic_scores = {}
    try:
        from .semantic_catalog import semantic_catalog_candidates
        semantic_scores = {
            int(row["id"]): float(row["semantic_similarity"])
            for row in semantic_catalog_candidates(db, query, limit=160)
        }
        if semantic_scores:
            existing_ids = {row.id for row in rows}
            missing_ids = [product_id for product_id in semantic_scores if product_id not in existing_ids]
            if missing_ids:
                rows.extend(db.query(Product).filter(
                    Product.supermarket == "REWE", Product.id.in_(missing_ids)
                ).all())
    except Exception:
        # The lexical path remains fully functional without model files/indexes.
        semantic_scores = {}

    ranked = []
    for product in rows:
        text = _product_text(product)
        if any(marker in text for marker in _EXCLUDE_MARKERS):
            continue
        phrase_hits = sum(1 for variant in variants if _normalise(variant) in text)
        token_hits = sum(1 for token in token_set if token in text.split())
        semantic_score = semantic_scores.get(int(product.id), 0.0)
        multiword_dish_query = any(
            concept in _normalise(query) and len(_normalise(concept).split()) >= 2
            for concept in _QUERY_EXPANSIONS
        )
        if multiword_dish_query:
            # A single shared word ("chili" or "pommes") is not enough to
            # match a compound dish; require two user-query tokens, a complete
            # multiword alias phrase, or a strong local semantic candidate.
            multiword_phrase_hits = sum(
                1 for variant in variants
                if len(_normalise(variant).split()) >= 2 and _normalise(variant) in text
            )
            if token_hits < 2 and not multiword_phrase_hits and semantic_score < 0.58:
                continue
        elif not phrase_hits and not token_hits and semantic_score < 0.58:
            continue
        kind = _convenience_type(text, query, product)
        # Exact dish matches dominate; embeddings recover useful German/English
        # supermarket formats when wording differs from the user's query.
        query_normal = _normalise(query)
        alias_hits = [
            _normalise(variant) for variant in variants
            if _normalise(variant) != query_normal and _normalise(variant) in text
        ]
        alias_bonus = sum(2.5 if len(alias.split()) >= 2 else 1.5 for alias in set(alias_hits))
        score = phrase_hits * 8 + token_hits * 1.5 + alias_bonus + max(0.0, semantic_score - 0.45) * 16
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
    # This endpoint is for convenience alternatives, not a second raw
    # ingredient search. Keep generic catalog matches only as a fallback when
    # no meal, kit, ready-to-cook product or prepared component was found.
    if any(item[2] != "catalog_product" for item in ranked):
        ranked = [item for item in ranked if item[2] != "catalog_product"]
    # Reserve a small number of slots for each useful convenience format so
    # the first screen compares meals, kits and cook-at-home shortcuts rather
    # than showing ten near-identical products from one format.
    diversified = []
    selected_ids = set()
    for kind in ("ready_meal", "meal_kit", "ready_to_cook", "prepared_component"):
        added_for_kind = 0
        # Cook-at-home searches need enough distinct format slots to show
        # dough, baguettes, frozen pizza, fries and flatbreads such as Flammkuchen.
        max_for_kind = 5 if kind == "ready_to_cook" else 2
        selected_formats = set()
        for item in ranked:
            if item[2] != kind or item[1].id in selected_ids:
                continue
            format_key = _format_diversity_key(item[1], kind)
            if format_key in selected_formats:
                continue
            diversified.append(item)
            selected_ids.add(item[1].id)
            selected_formats.add(format_key)
            added_for_kind += 1
            if added_for_kind >= max_for_kind:
                break
    diversified.extend(item for item in ranked if item[1].id not in selected_ids)
    ranked = diversified
    products = []
    seen = set()
    brand_counts = {}
    for score, product, kind in ranked:
        if product.id in seen:
            continue
        brand_key = _normalise(product.brand)
        if brand_key and brand_counts.get(brand_key, 0) >= 2:
            continue
        seen.add(product.id)
        if brand_key:
            brand_counts[brand_key] = brand_counts.get(brand_key, 0) + 1
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
            **({"semantic_similarity": round(semantic_scores[int(product.id)], 4)}
               if int(product.id) in semantic_scores else {}),
        })
        if len(products) >= max(1, min(int(limit), 30)):
            break
    return {
        "query": query,
        "catalog_count": catalog_count,
        "products": products,
        "source": "local_rewe_catalog",
        "retrieval": "hybrid_local" if semantic_scores else "lexical_fallback",
    }
