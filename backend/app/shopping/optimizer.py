import math
from collections import defaultdict

from ..ingredient_aliases import ingredient_aliases
from ..ingredient_intelligence import ingredient_substitution_name, ingredient_suggested_substitution_name, normalize_text, validate_ingredient_unit


STRATEGIES = {
    "maximum-savings",
    "best-value",
    "plan-efficiency",
    "premium",
    "cheapest",
    "less-waste",
}


def consolidate(meals, servings_map):
    grouped = defaultdict(lambda: {"quantity": 0.0, "source_meals": [], "ingredient_intelligence": None, "unit_validation": None})
    canonical_units = {"mass": "g", "volume": "ml", "count": "piece"}
    for meal in meals:
        def _safe_servings(value, default=2.0):
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return default
            return parsed if math.isfinite(parsed) and parsed > 0 else default

        servings = max(0.1, _safe_servings(servings_map.get(meal["id"], 2) or 2))
        base_servings = max(0.1, _safe_servings(meal.get("base_servings", 2) or 2))
        factor = servings / base_servings
        for name, quantity, unit in meal["ingredients"]:
            normalized_unit = _normal_unit(unit)
            try:
                raw_quantity = float(quantity)
                normalized_quantity = (
                    raw_quantity if math.isfinite(raw_quantity) and raw_quantity >= 0
                    else float("nan")
                )
            except (TypeError, ValueError):
                normalized_quantity = float("nan")
            unit_info = _UNIT_BASE.get(normalized_unit)
            if unit_info:
                dimension, multiplier = unit_info
                normalized_unit = canonical_units[dimension]
                normalized_quantity *= multiplier
            # Keep semantically different units (e.g. cloves vs pieces) separate.
            key = (name.lower().strip(), normalized_unit)
            row = grouped[key]
            scaled_quantity = normalized_quantity * factor
            row["quantity"] = (
                float("nan")
                if not math.isfinite(row["quantity"]) or not math.isfinite(scaled_quantity)
                else row["quantity"] + scaled_quantity
            )
            row["source_meals"].append(meal["name"])
            intelligence = meal.get("ingredient_intelligence") or {}
            if isinstance(intelligence, dict):
                # Recipe metadata keys are normalized with normalize_text(), so use
                # the same normalization here (hyphens, accents and punctuation matter).
                intelligence_key = normalize_text(name)
                row["ingredient_intelligence"] = (
                    intelligence.get(intelligence_key)
                    or intelligence.get(name.lower().strip())
                    or intelligence.get(name)
                    or row["ingredient_intelligence"]
                )
            row["unit_validation"] = validate_ingredient_unit(name, normalized_unit, row["ingredient_intelligence"])
    return [
        {
            "ingredient": ingredient,
            "quantity": round(value["quantity"], 2),
            "unit": unit,
            "source_meals": list(dict.fromkeys(value["source_meals"])),
            "ingredient_intelligence": value.get("ingredient_intelligence"),
            "unit_validation": value.get("unit_validation") or validate_ingredient_unit(ingredient, unit, value.get("ingredient_intelligence")),
        }
        for (ingredient, unit), value in grouped.items()
    ]


_UNIT_ALIASES = {
    "gram": "g", "grams": "g", "gr": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kg": "kg",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "ml": "ml",
    "liter": "l", "litre": "l", "liters": "l", "litres": "l", "l": "l",
    "stück": "piece", "stuck": "piece", "pcs": "piece", "pc": "piece",
    "clove": "cloves", "cloves": "cloves",
    "pieces": "piece", "piece": "piece", "unit": "piece", "units": "piece",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "cup": "cup", "cups": "cup",
}
_UNIT_BASE = {"g": ("mass", 1.0), "kg": ("mass", 1000.0),
              "ml": ("volume", 1.0), "l": ("volume", 1000.0),
              "tbsp": ("volume", 15.0), "tsp": ("volume", 5.0), "cup": ("volume", 250.0),
              "piece": ("count", 1.0)}


def _normal_unit(value):
    raw = str(value or "piece").strip().lower()
    return _UNIT_ALIASES.get(raw, raw)


def _convert_quantity(quantity, from_unit, to_unit):
    """Convert only well-defined mass, volume and count units; otherwise return None."""
    source, target = _normal_unit(from_unit), _normal_unit(to_unit)
    if source == target:
        return float(quantity)
    source_info, target_info = _UNIT_BASE.get(source), _UNIT_BASE.get(target)
    if not source_info or not target_info or source_info[0] != target_info[0]:
        return None
    return float(quantity) * source_info[1] / target_info[1]

# Approximate edible weights are used only when a recipe gives a whole produce
# count but REWE sells that ingredient by weight. They are explicit estimates,
# never generic piece-to-gram conversions.
_COUNT_TO_GRAMS = {
    "onion": 150,
    "red onion": 150,
    "potato": 170,
    "tomato": 120,
    "carrot": 70,
    "bell pepper": 150,
    "lemon": 100,
    "lime": 70,
    "apple": 180,
    "banana": 120,
    "zucchini": 200,
    "garlic": 3,
    "tortillas": 45,
    "soft tortillas": 45,
    "burger buns": 70,
    "hot dog buns": 50,
    "cheese slices": 20,
    "eggs": 60,
}


def _ingredient_count_weight(ingredient):
    terms = set(ingredient_aliases(ingredient))
    for canonical, grams in _COUNT_TO_GRAMS.items():
        if terms.intersection(ingredient_aliases(canonical)):
            return grams
    return None


_SPOON_GRAMS_PER_TSP = {
    "curry powder": 2.0,
    "cumin": 2.1,
    "paprika powder": 2.3,
    "oregano": 1.0,
    "baking powder": 4.0,
    "taco seasoning": 2.5,
    "salt": 6.0,
    "black pepper": 2.3,
}

# Approximate density for the common condiment whose recipe and pack units differ.
_DENSITY_G_PER_ML = {
    "mayonnaise": 0.95,
    "caesar dressing": 1.0,
}


def _convert_ingredient_quantity(quantity, from_unit, to_unit, ingredient):
    """Convert standard units plus explicit ingredient-specific kitchen estimates."""
    converted = _convert_quantity(quantity, from_unit, to_unit)
    if converted is not None:
        return converted, None

    source, target = _normal_unit(from_unit), _normal_unit(to_unit)
    ingredient_key = normalize_text(ingredient)

    density = _DENSITY_G_PER_ML.get(ingredient_key)
    if density and source in {"ml", "l"} and target in {"g", "kg"}:
        volume_ml = float(quantity) * (1000 if source == "l" else 1)
        grams = volume_ml * density
        return (grams / 1000 if target == "kg" else grams), (
            f"Estimated density {density:g} g/ml for {ingredient}; actual product density may vary."
        )
    if density and source in {"g", "kg"} and target in {"ml", "l"}:
        grams = float(quantity) * (1000 if source == "kg" else 1)
        volume_ml = grams / density
        return (volume_ml / 1000 if target == "l" else volume_ml), (
            f"Estimated density {density:g} g/ml for {ingredient}; actual product density may vary."
        )

    # consolidate() converts tsp/tbsp to ml. Use a disclosed average density only
    # for common dry seasonings that REWE sells by mass.
    grams_per_tsp = _SPOON_GRAMS_PER_TSP.get(ingredient_key)
    if source == "ml" and target in {"g", "kg"} and grams_per_tsp is not None:
        grams = float(quantity) * grams_per_tsp / 5.0
        return (grams / 1000 if target == "kg" else grams), (
            f"Estimated {grams_per_tsp:g} g per teaspoon of {ingredient}."
        )

    # These retail condiments are commonly sold by volume while recipes specify
    # mass. Use explicit, visible estimates rather than pretending g == ml.
    condiment_density_g_per_ml = {
        "mayonnaise": 0.95,
        "caesar dressing": 1.0,
    }
    density = condiment_density_g_per_ml.get(ingredient_key)
    source_info, target_info = _UNIT_BASE.get(source), _UNIT_BASE.get(target)
    if density and source_info and target_info:
        if source_info[0] == "mass" and target_info[0] == "volume":
            grams = float(quantity) * source_info[1]
            millilitres = grams / density
            return millilitres / target_info[1], (
                f"Estimated density {density:g} g/ml for {ingredient}."
            )
        if source_info[0] == "volume" and target_info[0] == "mass":
            millilitres = float(quantity) * source_info[1]
            grams = millilitres * density
            return grams / target_info[1], (
                f"Estimated density {density:g} g/ml for {ingredient}."
            )

    grams_per_piece = _ingredient_count_weight(ingredient)
    if grams_per_piece is None:
        return None, None
    if source in {"piece", "cloves"} and target in {"g", "kg"}:
        grams = float(quantity) * grams_per_piece
        return (grams / 1000 if target == "kg" else grams), (
            f"Estimated {grams_per_piece} g per piece of {ingredient.rstrip('s')}."
        )
    if source in {"g", "kg"} and target in {"piece", "cloves"}:
        grams = float(quantity) * (1000 if source == "kg" else 1)
        return grams / grams_per_piece, (
            f"Estimated {grams_per_piece} g per piece of {ingredient.rstrip('s')}."
        )
    return None, None


def _package(product):
    raw_qty = product.get("pack_qty")
    if raw_qty is None:
        raw_qty = product.get("package_size")
    if raw_qty is None:
        raw_qty = 1.0
    unit = product.get("unit") or product.get("package_unit") or "piece"
    try:
        qty = float(raw_qty)
    except (TypeError, ValueError):
        return 0.0, _normal_unit(unit)
    if not math.isfinite(qty) or qty <= 0:
        return 0.0, _normal_unit(unit)
    return qty, _normal_unit(unit)


def _premium_signal(product):
    name = f"{product.get('brand') or ''} {product.get('name') or product.get('name_original') or ''}".lower()
    premium_terms = ("bio", "organic", "demeter", "de cecco", "barilla", "premium", "regional")
    discount_terms = ("ja!", "rewe beste wahl", "discount")
    if any(term in name for term in premium_terms):
        return 1.0
    if any(term in name for term in discount_terms):
        return -0.5
    return 0.0


def _candidate_score(mode, total, waste_ratio, unit_price, reuse_count, product):
    premium = _premium_signal(product)
    if mode in ("cheapest", "maximum-savings"):
        return total
    if mode == "less-waste":
        return total + waste_ratio * max(total, 1) * 2.0
    if mode == "plan-efficiency":
        reuse_bonus = min(reuse_count, 5) * 0.25
        return total + waste_ratio * max(total, 1) * 1.6 - reuse_bonus
    if mode == "premium":
        return total * 0.25 + waste_ratio * max(total, 1) * 0.35 - premium * 2.0 + unit_price * 0.03
    return total + waste_ratio * max(total, 1) * 1.15 + unit_price * 0.05 - min(reuse_count, 4) * 0.12 - premium * 0.15


def _badge(mode, waste_ratio, reuse_count, product, cheapest_total, total):
    if waste_ratio <= 0.08:
        return "♻️ Low Waste"
    if mode in ("cheapest", "maximum-savings") or abs(total - cheapest_total) < 0.01:
        return "💰 Cheapest"
    if mode == "plan-efficiency" or reuse_count >= 3:
        return "🔥 Best for Plan"
    if mode == "premium":
        return "✨ Premium"
    if _premium_signal(product) > 0.5:
        return "🟢 Good Value"
    return "⭐ Best Value"


def build_basket(requirements, adapter, mode="best-value", owned=None, overrides=None, pantry=None):
    owned = {x.lower().strip() for x in (owned or [])}
    overrides = overrides or {}
    pantry = pantry or {}
    output = []

    for requirement in requirements:
        ingredient = requirement["ingredient"].lower().strip()
        try:
            requested = float(requirement["quantity"])
        except (TypeError, ValueError):
            requested = float("nan")
        unit = _normal_unit(requirement["unit"])
        pantry_row = pantry.get(ingredient)
        pantry_used = 0.0
        valid_requested = math.isfinite(requested) and requested >= 0
        if valid_requested and pantry_row:
            try:
                pantry_quantity = float(pantry_row.get("quantity", 0))
            except (TypeError, ValueError):
                pantry_quantity = float("nan")
            if math.isfinite(pantry_quantity) and pantry_quantity >= 0:
                converted_pantry, _ = _convert_ingredient_quantity(
                    pantry_quantity, pantry_row.get("unit"), unit, ingredient
                )
                if converted_pantry is not None and math.isfinite(converted_pantry):
                    pantry_used = min(requested, max(0.0, converted_pantry))
        needed = max(0.0, requested - pantry_used) if valid_requested else 0.0

        base = {
            **requirement,
            "needed_quantity": round(needed, 2),
            "pantry_used": round(pantry_used, 2),
            "pantry_unit": unit,
            "product": None,
            "packs": 0,
            "total": 0.0,
            "checkout_cost": 0.0,
            "consumed_cost": 0.0,
            "waste": 0.0,
            "waste_ratio": 0.0,
            "package_quantity": None,
            "package_unit": None,
            "unit_cost": None,
            "unit_conversion_note": None,
            "unit_validation": requirement.get("unit_validation") or validate_ingredient_unit(ingredient, unit, requirement.get("ingredient_intelligence")),
            "semantic_suggestions": [],
            "match_status": "unmatched",
            "match_reason": None,
            "why": None,
            "badge": "Availability unknown",
            "selected_by_user": False,
        }

        if not valid_requested:
            base.update({
                "match_reason": "Recipe quantity is invalid (must be a finite, non-negative number).",
                "why": "Correct the ingredient quantity before shopping.",
            })
            output.append(base)
            continue

        if ingredient in owned or needed <= 0:
            base.update({
                "needed_quantity": 0.0 if ingredient in owned else 0.0,
                "pantry_used": round(requested if ingredient in owned else pantry_used, 2),
                "match_status": "covered",
                "match_reason": "Covered by pantry / marked as owned.",
                "why": "Covered by pantry / marked as owned.",
                "badge": "🏠 Uses Pantry",
            })
            output.append(base)
            continue

        candidates = []
        semantic_suggestions = []
        unit_validation = requirement.get("unit_validation") or validate_ingredient_unit(ingredient, unit, requirement.get("ingredient_intelligence"))
        if not unit_validation.get("valid", True):
            base.update({
                "unit_validation": unit_validation,
                "match_reason": unit_validation.get("reason") or "Ingredient unit failed validation.",
                "why": "Recipe ingredient needs correction before safe product matching.",
            })
            output.append(base)
            continue
        intelligence = requirement.get("ingredient_intelligence")
        try:
            raw_products = list(adapter.search(ingredient, intelligence=intelligence) or [])
        except TypeError:
            raw_products = list(adapter.search(ingredient) or [])
        override_id = overrides.get(ingredient)
        for product in raw_products:
            match_type = product.get("ingredient_match_type")
            # Curated substitutions with an explicit replacement label are
            # approved catalogue rules. Semantic suggestions remain review-only
            # until the user explicitly selects them.
            curated_substitution = (
                match_type == "suggested_substitution"
                and bool(product.get("ingredient_substitute"))
                and not product.get("semantic_match_type")
            )
            requires_confirmation = (
                match_type == "semantic_candidate"
                or (match_type == "suggested_substitution" and not curated_substitution)
            )
            if requires_confirmation:
                if override_id is not None and str(product.get("id")) == str(override_id):
                    semantic_type = product.get("semantic_match_type") or product.get("ingredient_match_type")
                    product_title = product.get("name_original") or product.get("name_normalized") or ""
                    replacement_name = (
                        ingredient_substitution_name(ingredient, product_title, intelligence)
                        or ingredient_suggested_substitution_name(ingredient, product_title, intelligence)
                        or product.get("ingredient_substitute")
                    )
                    if semantic_type in {"substitute", "suggested_substitution"}:
                        fallback_replacement = product.get("ingredient")
                        if not fallback_replacement or normalize_text(fallback_replacement) == normalize_text(ingredient):
                            fallback_replacement = product.get("name_normalized") or product_title
                        product = {
                            **product,
                            "ingredient_match_type": "substitute",
                            "ingredient_substitute": replacement_name or fallback_replacement,
                        }
                    else:
                        product = {**product, "ingredient_match_type": "user_confirmed_semantic"}
                else:
                    semantic_suggestions.append(product)
                    continue
            price = product.get("price")
            try:
                numeric_price = float(price)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric_price) or numeric_price <= 0 or str(product.get("availability") or "").lower() in {
                "unavailable", "out_of_stock", "not_available", "discontinued"
            }:
                continue
            pack_qty, product_unit = _package(product)
            if not math.isfinite(pack_qty) or pack_qty <= 0:
                continue
            needed_in_pack_unit, unit_conversion_note = _convert_ingredient_quantity(needed, unit, product_unit, ingredient)
            if needed_in_pack_unit is None or not math.isfinite(needed_in_pack_unit) or needed_in_pack_unit <= 0:
                continue
            packs = max(1, math.ceil(needed_in_pack_unit / pack_qty))
            try:
                purchased_quantity = packs * pack_qty
                checkout_cost = packs * numeric_price
            except OverflowError:
                continue
            if (
                not math.isfinite(purchased_quantity) or purchased_quantity <= 0
                or not math.isfinite(checkout_cost) or checkout_cost <= 0
            ):
                continue
            waste_in_pack_unit = max(0.0, purchased_quantity - needed_in_pack_unit)
            consumed_cost = checkout_cost * min(1.0, needed_in_pack_unit / purchased_quantity)
            waste_ratio = waste_in_pack_unit / max(needed_in_pack_unit, 1e-9)
            # The checkout price and normalized package quantity are the
            # authoritative pair. Recompute unit price instead of trusting a
            # stale/misparsed cached price_per_unit field.
            unit_price = numeric_price / pack_qty
            score = _candidate_score(mode, checkout_cost, waste_ratio, unit_price, len(requirement.get("source_meals", [])), product)
            # Exact matches win over substitutions; a substitute is used only when
            # no exact priced/available option is present.
            if product.get("ingredient_match_type") in {"substitute", "suggested_substitution"}:
                score += 1000
            product_id = product.get("id")
            selected_by_user = override_id is not None and str(product_id) == str(override_id)
            if selected_by_user:
                score -= 1_000_000
            candidates.append({
                "score": score, "packs": packs, "checkout_cost": checkout_cost,
                "consumed_cost": consumed_cost, "waste": waste_in_pack_unit,
                "waste_ratio": waste_ratio, "unit_price": unit_price,
                "product": product, "selected_by_user": selected_by_user,
                "package_quantity": purchased_quantity, "package_unit": product_unit,
                "needed_in_pack_unit": needed_in_pack_unit,
                "unit_conversion_note": unit_conversion_note,
            })

        if not candidates:
            base.update({
                "semantic_suggestions": semantic_suggestions[:5],
                "match_reason": (
                    "No high-confidence match was found. Semantic product suggestions are shown for your review."
                    if semantic_suggestions else
                    "No available catalog product with a compatible unit and a real price was found."
                ),
                "why": (
                    "Review the possible products before selecting one."
                    if semantic_suggestions else "No compatible priced REWE product found."
                ),
            })
            output.append(base)
            continue

        # A curated substitute must never beat a purchasable exact match merely
        # because its pack is cheaper or its scoring mode favors it. Explicit user
        # selection remains authoritative, including a confirmed substitute.
        user_selected = [row for row in candidates if row["selected_by_user"]]
        if user_selected:
            candidates = user_selected
        else:
            exact_candidates = [
                row for row in candidates
                if row["product"].get("ingredient_match_type") not in {"substitute", "suggested_substitution"}
            ]
            if exact_candidates:
                candidates = exact_candidates

        cheapest_total = min(row["checkout_cost"] for row in candidates)
        chosen = min(candidates, key=lambda row: row["score"])
        badge = _badge(mode, chosen["waste_ratio"], len(requirement.get("source_meals", [])),
                       chosen["product"], cheapest_total, chosen["checkout_cost"])
        if chosen["selected_by_user"]:
            badge = "✓ Your choice"
        selected_match_type = chosen["product"].get("ingredient_match_type") or "exact"
        if selected_match_type == "suggested_substitution":
            selected_match_type = "substitute"
        availability_status = str(chosen["product"].get("availability") or "unknown").lower()
        availability_note = (
            "Stock not verified — this is a recent catalog listing, not live inventory."
            if availability_status not in {"available", "in_stock"}
            else "Catalog currently marks this product as available."
        )
        base.update({
            "product": chosen["product"],
            "packs": chosen["packs"],
            "total": round(chosen["checkout_cost"], 2),
            "checkout_cost": round(chosen["checkout_cost"], 2),
            "consumed_cost": round(chosen["consumed_cost"], 2),
            "waste": round(chosen["waste"], 2),
            "waste_ratio": round(chosen["waste_ratio"], 4),
            "package_quantity": round(chosen["package_quantity"], 2),
            "package_unit": chosen["package_unit"],
            "unit_cost": round(chosen["unit_price"], 6),
            "unit_conversion_note": chosen.get("unit_conversion_note"),
            "match_status": "substituted" if selected_match_type == "substitute" else "matched",
            "match_reason": (
                "Used a curated culinary substitute because an exact catalog match was not selected."
                if selected_match_type == "substitute"
                else (
                    "You confirmed this semantic product suggestion. Verify that it is suitable for the recipe."
                    if selected_match_type == "user_confirmed_semantic"
                    else (
                        "Matched against a priced catalog product. " + chosen["unit_conversion_note"]
                        if chosen.get("unit_conversion_note")
                        else "Matched against a priced catalog product using compatible units."
                    )
                )
            ),
            "availability_status": availability_status,
            "availability_note": availability_note,
            "why": f"Used in {len(requirement.get('source_meals', []))} meal(s); {round(chosen['waste_ratio'] * 100)}% estimated package leftover.",
            "badge": badge,
            "selected_by_user": chosen["selected_by_user"],
        })
        output.append(base)

    return output
