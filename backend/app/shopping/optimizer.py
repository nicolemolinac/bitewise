import math
from collections import defaultdict

from ..ingredient_aliases import ingredient_aliases
from ..ingredient_intelligence import _profile_lookup, ingredient_substitution_name, ingredient_suggested_substitution_name, normalize_text, validate_ingredient_unit


STRATEGIES = {
    "maximum-savings",
    "best-value",
    "plan-efficiency",
    "premium",
    "cheapest",
    "less-waste",
}


def consolidate(meals, servings_map):
    grouped = defaultdict(lambda: {
        "quantity": 0.0, "source_meals": [], "ingredient_intelligence": None,
        "unit_validation": None, "quantity_validation": {"valid": True, "reason": None},
    })
    canonical_units = {"mass": "g", "volume": "ml", "count": "piece"}

    def _positive_finite(value):
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if math.isfinite(parsed) and parsed > 0 else None

    for meal in meals:
        # Apply defaults only when a value is genuinely absent. Using "or 2"
        # turns explicit zero into two servings and bypasses validation.
        requested_servings = servings_map.get(meal["id"], 2)
        if requested_servings is None:
            requested_servings = 2
        requested_base_servings = meal.get("base_servings", 2)
        if requested_base_servings is None:
            requested_base_servings = 2
        servings = _positive_finite(requested_servings)
        base_servings = _positive_finite(requested_base_servings)
        scaling_valid = servings is not None and base_servings is not None
        factor = servings / base_servings if scaling_valid else 0.0
        for name, quantity, unit in meal["ingredients"]:
            try:
                raw_quantity = float(quantity)
            except (TypeError, ValueError, OverflowError):
                raw_quantity = float("nan")
            quantity_valid = (
                scaling_valid
                and not isinstance(quantity, bool)
                and math.isfinite(raw_quantity)
                and raw_quantity > 0
            )
            raw_unit = str(unit or "").strip()
            unit_valid = bool(raw_unit)
            normalized_unit = _normal_unit(raw_unit) if unit_valid else ""
            unit_info = _UNIT_BASE.get(normalized_unit)
            if unit_info:
                dimension, multiplier = unit_info
                # Mass and volume units can safely share a canonical unit.
                # Count-like units cannot: one bunch is not one loose piece.
                normalized_unit = (
                    normalized_unit if dimension == "count"
                    else canonical_units[dimension]
                )
                normalized_quantity = raw_quantity * multiplier if quantity_valid else 0.0
            else:
                # Keep semantically different units (e.g. cloves vs pieces) separate.
                normalized_quantity = raw_quantity if quantity_valid else 0.0
            intelligence = meal.get("ingredient_intelligence") or {}
            # Reuse the shared lookup so punctuation/accents and both supported
            # metadata shapes (ingredient-keyed map or a single profile) behave
            # identically in matching, unit validation and weekly consolidation.
            profile = _profile_lookup(intelligence, str(name or ""))
            form_key = normalize_text(profile.get("form") or "unspecified") if isinstance(profile, dict) else "unspecified"
            preparation_key = normalize_text(profile.get("preparation") or "") if isinstance(profile, dict) else ""
            # Same ingredient/unit can still represent different retail forms
            # (e.g. whole vs ground cumin) or preparation states (whole vs
            # chopped garlic). Never merge quantities and let the last recipe
            # choose the matching/unit-validation rules for all meals.
            key = (normalize_text(name), normalized_unit, form_key, preparation_key)
            row = grouped[key]
            row.setdefault("display_ingredient", str(name or "").strip())
            row["quantity"] += normalized_quantity * factor
            if not quantity_valid:
                row["quantity_validation"] = {
                    "valid": False,
                    "reason": (
                        f"Ingredient quantity must be a finite positive number; received {quantity!r}."
                        if scaling_valid else
                        "Serving count and base servings must be finite positive numbers before scaling ingredients."
                    ),
                }
            row["source_meals"].append(meal["name"])
            if isinstance(profile, dict) and profile:
                row["ingredient_intelligence"] = profile
            row["unit_validation"] = (
                validate_ingredient_unit(name, normalized_unit, row["ingredient_intelligence"])
                if unit_valid else {
                    "valid": False, "family": None,
                    "reason": "Ingredient unit is missing; add an explicit unit before shopping.",
                }
            )
    return [
        {
            "ingredient": value.get("display_ingredient") or ingredient,
            "quantity": round(value["quantity"], 2),
            "unit": unit,
            "source_meals": list(dict.fromkeys(value["source_meals"])),
            "ingredient_intelligence": value.get("ingredient_intelligence"),
            "ingredient_form": _form if _form != "unspecified" else None,
            "ingredient_preparation": _preparation or None,
            "unit_validation": value.get("unit_validation") or validate_ingredient_unit(ingredient, unit, value.get("ingredient_intelligence")),
            "quantity_validation": value.get("quantity_validation") or {"valid": True, "reason": None},
        }
        for (ingredient, unit, _form, _preparation), value in grouped.items()
    ]


_UNIT_ALIASES = {
    "gram": "g", "grams": "g", "gramm": "g", "gr": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kilogramm": "kg", "kilo": "kg", "kg": "kg",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "ml": "ml",
    "liter": "l", "litre": "l", "liters": "l", "litres": "l", "l": "l",
    "ounce": "oz", "ounces": "oz", "oz": "oz",
    "pound": "lb", "pounds": "lb", "lb": "lb", "lbs": "lb",
    "fluid ounce": "fl oz", "fluid ounces": "fl oz", "fl oz": "fl oz",
    "centiliter": "cl", "centiliters": "cl", "centilitre": "cl", "cl": "cl",
    "deciliter": "dl", "deciliters": "dl", "decilitre": "dl", "dl": "dl",
    "pint": "pt", "pints": "pt", "pt": "pt",
    "quart": "qt", "quarts": "qt", "qt": "qt",
    "gallon": "gal", "gallons": "gal", "gal": "gal",
    "stück": "piece", "stuck": "piece", "pcs": "piece", "pc": "piece",
    "pieces": "piece", "piece": "piece", "unit": "piece", "units": "piece",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "el": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp", "tl": "tsp",
    "clove": "cloves", "cloves": "cloves", "zehe": "cloves", "zehen": "cloves",
    "cup": "cup", "cups": "cup",
    "pinch": "pinch", "prise": "pinch", "prisen": "pinch",
    "bunch": "bunch", "bunches": "bunch", "bund": "bunch",
    "slice": "slice", "slices": "slice", "scheibe": "slice", "scheiben": "slice",
    "esslöffel": "tbsp", "essloeffel": "tbsp",
    "teelöffel": "tsp", "teeloeffel": "tsp",
}
_UNIT_BASE = {
    "g": ("mass", 1.0), "kg": ("mass", 1000.0),
    "oz": ("mass", 28.349523125), "lb": ("mass", 453.59237),
    "ml": ("volume", 1.0), "l": ("volume", 1000.0),
    "cl": ("volume", 10.0), "dl": ("volume", 100.0),
    "fl oz": ("volume", 29.5735295625), "pt": ("volume", 473.176473),
    "qt": ("volume", 946.352946), "gal": ("volume", 3785.411784),
    "tbsp": ("volume", 15.0), "tsp": ("volume", 5.0),
    "pinch": ("volume", 0.3), "cup": ("volume", 250.0),
    "piece": ("count", 1.0), "bunch": ("count", 1.0),
}


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
    # Both are count dimensions, but their semantics are not interchangeable:
    # one bunch of herbs is not one loose piece of produce.
    if source_info[0] == "count":
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
    "romaine lettuce": 100,
    "lettuce": 250,
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
    # Conservative average piece weights for common recipe ingredients.
    # These are estimates and are surfaced in basket conversion notes.
    "broccoli": 300,
    "cucumber": 350,
    "mushroom": 20,
    "avocado": 180,
    "strawberry": 15,
    "aubergine": 300,
    "cabbage": 1000,
    "asparagus": 20,
    "celery": 40,
    "pineapple": 1000,
    "fresh cilantro": 30,
    "parsley": 30,
    "basil": 30,
    "spinach": 100,
    "chicken breast": 150,
    "salmon": 150,
    "white fish fillet": 150,
    "shrimp": 12,
    "turkey": 150,
    "bacon": 15,
    "bratwurst": 100,
    "tofu": 200,
}


def _ingredient_count_weight(ingredient):
    # Require the full ingredient phrase to be an alias of the mapped item.
    # Intersecting arbitrary alias tokens can misclassify compounds such as
    # "turkey bacon" as turkey (150 g) instead of bacon (15 g per slice).
    normalized = normalize_text(ingredient)
    # "pepper" and "paprika" are ambiguous across fresh bell pepper and
    # dried seasonings. The broad bilingual alias ontology intentionally
    # links them for search, but that must never authorize a piece-weight
    # estimate (e.g. 1 tsp pepper -> 150 g bell pepper).
    if normalized in {"pepper", "paprika", "salat", "salad"}:
        return None
    for canonical, grams in _COUNT_TO_GRAMS.items():
        aliases = {normalize_text(alias) for alias in ingredient_aliases(canonical)}
        if normalized in aliases:
            return grams
    return None


# Explicit ingredient-specific average densities support common recipe
# volume measures when REWE sells the product by mass. These are estimates,
# surfaced to the user as conversion notes rather than hidden exact conversions.
_MASS_VOLUME_DENSITY_G_PER_ML = {
    "mayonnaise": 0.95,
    "caesar dressing": 1.0,
    "wheat flour": 0.48,
    "all purpose flour": 0.48,
    "flour": 0.48,
    "granulated sugar": 0.80,
    "sugar": 0.80,
    "brown sugar": 0.85,
    "rolled oats": 0.36,
    "rice": 0.80,
    "breadcrumbs": 0.48,
    "cocoa powder": 0.40,
    "grated cheese": 0.40,
    "honey": 1.42,
    "cornstarch": 0.55,
    "tomato paste": 1.05,
    "fresh basil pesto": 1.0,
    "pine nuts": 0.58,
    "ketchup": 1.1,
    "mustard": 1.05,
    "jam": 1.3,
}


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


def _convert_ingredient_quantity(quantity, from_unit, to_unit, ingredient):
    """Convert standard units plus explicit ingredient-specific kitchen estimates."""
    # Pantry and recipe quantities are external input. Never let NaN, infinity,
    # or negative values flow into conversions (an infinite pantry amount would
    # otherwise make the basket appear fully covered).
    if isinstance(quantity, bool):
        return None, None
    try:
        quantity = float(quantity)
    except (TypeError, ValueError, OverflowError):
        return None, None
    if not math.isfinite(quantity) or quantity < 0:
        return None, None
    converted = _convert_quantity(quantity, from_unit, to_unit)
    if converted is not None:
        return converted, None

    source, target = _normal_unit(from_unit), _normal_unit(to_unit)
    ingredient_key = normalize_text(ingredient)
    # consolidate() converts tsp/tbsp to ml. Use a disclosed average density only
    # for common dry seasonings that REWE sells by mass.
    density = _MASS_VOLUME_DENSITY_G_PER_ML.get(ingredient_key)
    if density and density > 0:
        if source in {"g", "kg"} and target in {"ml", "l"}:
            grams = float(quantity) * (1000 if source == "kg" else 1)
            ml = grams / density
            return (ml / 1000 if target == "l" else ml), (
                f"Estimated density {density:g} g/ml for {ingredient}."
            )
        if source in {"ml", "l"} and target in {"g", "kg"}:
            ml = float(quantity) * (1000 if source == "l" else 1)
            grams = ml * density
            return (grams / 1000 if target == "kg" else grams), (
                f"Estimated density {density:g} g/ml for {ingredient}."
            )

    grams_per_tsp = _SPOON_GRAMS_PER_TSP.get(ingredient_key)
    if source == "ml" and target in {"g", "kg"} and grams_per_tsp is not None:
        grams = float(quantity) * grams_per_tsp / 5.0
        return (grams / 1000 if target == "kg" else grams), (
            f"Estimated {grams_per_tsp:g} g per teaspoon of {ingredient}."
        )

    # A bunch is a distinct retail unit, not a synonym for one piece.
    # Only herbs with an explicit per-bunch estimate may cross between bunches
    # and mass; never reuse that estimate for loose pieces or other produce.
    bunch_herbs = {
        alias
        for canonical in ("fresh cilantro", "parsley", "basil")
        for alias in ingredient_aliases(canonical)
    }
    is_bunch_herb = normalize_text(ingredient) in bunch_herbs
    if (source == "bunch" or target == "bunch") and not is_bunch_herb:
        return None, None
    if (source == "piece" or target == "piece") and is_bunch_herb:
        return None, None

    grams_per_piece = _ingredient_count_weight(ingredient)
    if grams_per_piece is None:
        return None, None
    count_unit_labels = {
        "piece": "piece", "bunch": "bunch", "cloves": "clove", "slice": "slice",
    }
    if source in count_unit_labels and target in {"g", "kg"}:
        grams = float(quantity) * grams_per_piece
        unit_label = count_unit_labels[source]
        return (grams / 1000 if target == "kg" else grams), (
            f"Estimated {grams_per_piece} g per {unit_label} of {ingredient.rstrip('s')}."
        )
    if source in {"g", "kg"} and target in count_unit_labels:
        grams = float(quantity) * (1000 if source == "kg" else 1)
        unit_label = count_unit_labels[target]
        return grams / grams_per_piece, (
            f"Estimated {grams_per_piece} g per {unit_label} of {ingredient.rstrip('s')}."
        )
    return None, None


def _number(product, *keys, default=0.0):
    for key in keys:
        value = product.get(key)
        if value is not None and not isinstance(value, bool):
            try:
                return float(value)
            except (TypeError, ValueError, OverflowError):
                pass
    return default


def _package(product):
    qty = _number(product, "pack_qty", "package_size", default=1.0)
    unit = product.get("unit") or product.get("package_unit") or "piece"
    return max(qty, 0.0001), _normal_unit(unit)


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


def _substitution_profile(intelligence, ingredient):
    # Keep substitution-ratio lookup aligned with the shared punctuation- and
    # accent-insensitive profile resolver used by consolidation and matching.
    return _profile_lookup(intelligence, ingredient)


def _substitution_quantity_ratio(ingredient, product, intelligence):
    profile = _substitution_profile(intelligence, ingredient)
    replacement = normalize_text(product.get("ingredient_substitute") or "")
    if not replacement:
        # A substitute without an explicit replacement identity cannot safely
        # inherit the original ingredient's quantity ratio.
        return None
    options = profile.get("substitution_options", [])
    if not isinstance(options, list):
        return None
    for option in options:
        if not isinstance(option, dict):
            continue
        names = [option.get("name"), option.get("name_de")]
        aliases = option.get("aliases", [])
        if isinstance(aliases, list):
            names.extend(aliases)
        if any(normalize_text(name) == replacement for name in names if isinstance(name, str)):
            # A substitute is not quantity-equivalent by default. Require an
            # explicit curated ratio instead of silently assuming 1:1.
            if "quantity_ratio" not in option:
                return None
            raw_ratio = option.get("quantity_ratio")
            if isinstance(raw_ratio, bool):
                return None
            try:
                ratio = float(raw_ratio)
            except (TypeError, ValueError, OverflowError):
                return None
            return ratio if math.isfinite(ratio) and 0.1 <= ratio <= 5 else None
    return None


def build_basket(requirements, adapter, mode="best-value", owned=None, overrides=None, pantry=None):
    # Use the same accent/punctuation-insensitive key for recipe names, pantry,
    # saved overrides and user-owned ingredients. Consolidation already groups
    # names this way, so lookup must not reintroduce spelling-based mismatches.
    owned = {normalize_text(value) for value in (owned or [])}
    overrides = {normalize_text(key): value for key, value in (overrides or {}).items()}
    pantry = {}
    ambiguous_pantry_keys = set()
    for raw_key, value in (pantry or {}).items():
        normalized_key = normalize_text(raw_key)
        if not normalized_key:
            continue
        if normalized_key in pantry:
            # Never silently overwrite two inventory entries that collapse to
            # the same normalized ingredient key; their units/amounts may differ.
            pantry.pop(normalized_key, None)
            ambiguous_pantry_keys.add(normalized_key)
            continue
        if normalized_key not in ambiguous_pantry_keys:
            pantry[normalized_key] = value
    output = []

    for requirement in requirements:
        ingredient = normalize_text(requirement["ingredient"])
        raw_requested = requirement.get("quantity")
        try:
            requested = float(raw_requested)
        except (TypeError, ValueError, OverflowError):
            requested = float("nan")
        quantity_validation = requirement.get("quantity_validation") or {"valid": True, "reason": None}
        quantity_valid = (
            not isinstance(raw_requested, bool)
            and math.isfinite(requested)
            and requested > 0
            and quantity_validation.get("valid", True) is True
        )
        if not quantity_valid:
            requested = 0.0
            quantity_validation = {
                "valid": False,
                "reason": quantity_validation.get("reason") or "Ingredient quantity must be a finite positive number.",
            }
        raw_unit = str(requirement.get("unit") or "").strip()
        unit = _normal_unit(raw_unit) if raw_unit else ""
        unit_validation = requirement.get("unit_validation") or (
            validate_ingredient_unit(
                ingredient, unit, requirement.get("ingredient_intelligence")
            ) if raw_unit else {
                "valid": False, "family": None,
                "reason": "Ingredient unit is missing; add an explicit unit before shopping.",
            }
        )
        pantry_row = (
            pantry.get(ingredient)
            if unit_validation.get("valid", True) and ingredient not in ambiguous_pantry_keys
            else None
        )
        pantry_used = 0.0
        if isinstance(pantry_row, dict):
            converted_pantry, _ = _convert_ingredient_quantity(
                pantry_row.get("quantity", 0), pantry_row.get("unit"), unit, ingredient
            )
            if converted_pantry is not None:
                pantry_used = min(requested, max(0.0, converted_pantry))
        needed = max(0.0, requested - pantry_used)

        base = {
            **requirement,
            "needed_quantity": round(needed, 2),
            "product_needed_quantity": round(needed, 2),
            "quantity_validation": quantity_validation,
            "quantity_ratio": 1.0,
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
            "unit_validation": unit_validation,
            "semantic_suggestions": [],
            "match_status": "unmatched",
            "match_reason": None,
            "why": None,
            "badge": "Availability unknown",
            "selected_by_user": False,
        }

        if not quantity_valid:
            base.update({
                "match_status": "unmatched",
                "match_reason": quantity_validation.get("reason"),
                "why": "Recipe ingredient quantity needs correction before shopping.",
            })
            output.append(base)
            continue

        if not unit_validation.get("valid", True):
            base.update({
                "unit_validation": unit_validation,
                "match_reason": unit_validation.get("reason") or "Ingredient unit failed validation.",
                "why": "Recipe ingredient needs a valid unit before safe product matching.",
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
        intelligence = requirement.get("ingredient_intelligence")
        try:
            raw_products = list(adapter.search(ingredient, intelligence=intelligence) or [])
        except TypeError as exc:
            # Support legacy test/custom adapters that do not accept the optional
            # intelligence keyword, but never swallow a TypeError raised inside
            # the adapter's actual search implementation.
            if "unexpected keyword argument 'intelligence'" not in str(exc):
                raise
            raw_products = list(adapter.search(ingredient) or [])
        override_id = overrides.get(ingredient)
        for product in raw_products:
            if product.get("ingredient_match_type") in {"semantic_candidate", "suggested_substitution"}:
                if override_id is not None and str(product.get("id")) == str(override_id):
                    semantic_type = product.get("semantic_match_type") or product.get("ingredient_match_type")
                    product_title = product.get("name_original") or product.get("name_normalized") or ""
                    replacement_name = (
                        ingredient_substitution_name(ingredient, product_title, intelligence)
                        or ingredient_suggested_substitution_name(ingredient, product_title, intelligence)
                        or product.get("ingredient_substitute")
                    )
                    if semantic_type in {"substitute", "suggested_substitution"} and replacement_name:
                        product = {
                            **product,
                            "ingredient_match_type": "substitute",
                            "ingredient_substitute": replacement_name,
                        }
                    else:
                        product = {**product, "ingredient_match_type": "user_confirmed_semantic"}
                else:
                    semantic_suggestions.append(product)
                    continue
            price = product.get("price")
            if price is None or str(product.get("availability") or "").lower() in {
                "unavailable", "out_of_stock", "not_available", "discontinued"
            }:
                continue
            if isinstance(price, bool):
                continue
            try:
                price = float(price)
                raw_pack_qty = _number(product, "pack_qty", "package_size", default=float("nan"))
            except (TypeError, ValueError, OverflowError):
                continue
            # Never turn malformed catalog values into a tiny 0.0001-unit pack
            # or allow NaN/negative prices to contaminate basket ranking.
            if not math.isfinite(price) or price <= 0:
                continue
            if not math.isfinite(raw_pack_qty) or raw_pack_qty <= 0:
                continue
            raw_pack_unit = product.get("unit") or product.get("package_unit")
            if not isinstance(raw_pack_unit, str) or not raw_pack_unit.strip():
                # Package size without a unit is ambiguous (e.g. 500 could be
                # grams, millilitres or pieces); never silently assume pieces.
                continue
            pack_qty, product_unit = _package(product)
            quantity_ratio = (
                _substitution_quantity_ratio(ingredient, product, intelligence)
                if product.get("ingredient_match_type") == "substitute" else 1.0
            )
            # An explicitly malformed AI ratio is not a 1:1 substitution.
            # Reject this candidate instead of silently changing recipe quantities.
            if quantity_ratio is None:
                continue
            product_needed = needed * quantity_ratio
            conversion_ingredient = (
                product.get("ingredient_substitute") or ingredient
                if product.get("ingredient_match_type") == "substitute" else ingredient
            )
            needed_in_pack_unit, unit_conversion_note = _convert_ingredient_quantity(
                product_needed, unit, product_unit, conversion_ingredient
            )
            if needed_in_pack_unit is None:
                continue
            packs = max(1, math.ceil(needed_in_pack_unit / pack_qty))
            purchased_quantity = packs * pack_qty
            waste_in_pack_unit = max(0.0, purchased_quantity - needed_in_pack_unit)
            checkout_cost = packs * float(price)
            consumed_cost = checkout_cost * min(1.0, needed_in_pack_unit / purchased_quantity)
            # Waste is relative to the actual requirement, even when it is
            # a fractional count (e.g. half an onion) or less than one gram.
            waste_ratio = waste_in_pack_unit / max(needed_in_pack_unit, 1e-9)
            unit_price = _number(product, "unit_price", "price_per_unit", default=price / pack_qty)
            if not math.isfinite(unit_price) or unit_price < 0:
                unit_price = price / pack_qty
            score = _candidate_score(mode, checkout_cost, waste_ratio, unit_price, len(requirement.get("source_meals", [])), product)
            # Exact matches win over substitutions; a substitute is used only when
            # no exact priced/available option is present.
            if product.get("ingredient_match_type") == "substitute":
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
                "product_needed_quantity": product_needed,
                "quantity_ratio": quantity_ratio,
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

        if override_id is not None and not any(row["selected_by_user"] for row in candidates):
            # A persisted user choice must never be silently replaced by the
            # optimizer when it is absent, unavailable or no longer compatible.
            base.update({
                "semantic_suggestions": semantic_suggestions[:5],
                "match_reason": "Your previously selected product is no longer available or compatible. Please review and choose again.",
                "why": "The saved product choice could not be validated; no automatic replacement was selected.",
                "selected_by_user": False,
            })
            output.append(base)
            continue

        cheapest_total = min(row["checkout_cost"] for row in candidates)
        # Apply hard preference tiers before cost scoring: exact matches must
        # always beat substitutions, regardless of extreme price differences.
        # An explicit valid user choice is the sole exception and is honored.
        chosen = min(
            candidates,
            key=lambda row: (
                not row["selected_by_user"],
                row["product"].get("ingredient_match_type") == "substitute",
                row["score"],
            ),
        )
        badge = _badge(mode, chosen["waste_ratio"], len(requirement.get("source_meals", [])),
                       chosen["product"], cheapest_total, chosen["checkout_cost"])
        if chosen["selected_by_user"]:
            badge = "✓ Your choice"
        selected_match_type = chosen["product"].get("ingredient_match_type") or "exact"
        availability_status = str(chosen["product"].get("availability") or "unknown").lower()
        availability_note = (
            "Stock not verified — this is a recent catalog listing, not live inventory."
            if availability_status not in {"available", "in_stock"}
            else "Catalog currently marks this product as available."
        )
        base.update({
            "product": chosen["product"],
            "product_needed_quantity": round(chosen["product_needed_quantity"], 2),
            "quantity_ratio": chosen["quantity_ratio"],
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
