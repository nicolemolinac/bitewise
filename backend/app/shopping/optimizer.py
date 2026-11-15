import math
from collections import defaultdict

from ..ingredient_aliases import canonical_ingredient


STRATEGIES = {
    "maximum-savings",
    "best-value",
    "plan-efficiency",
    "premium",
    "cheapest",
    "less-waste",
}


def consolidate(meals, servings_map):
    grouped = defaultdict(lambda: {"quantity": 0.0, "source_meals": []})
    canonical_units = {"mass": "g", "volume": "ml", "count": "piece"}
    for meal in meals:
        try:
            servings = float(servings_map.get(meal["id"], 2))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid serving count for meal {meal.get('id')}")
        if not math.isfinite(servings) or servings <= 0:
            raise ValueError(f"Invalid serving count for meal {meal.get('id')}")
        factor = servings / 2  # generated recipes are normalized to 2 servings
        for name, quantity, unit in meal["ingredients"]:
            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                continue
            if not name or not math.isfinite(quantity) or quantity <= 0:
                continue
            normalized_unit = _normal_unit(unit)
            unit_info = _UNIT_BASE.get(normalized_unit)
            if unit_info:
                dimension, multiplier = unit_info
                normalized_unit = canonical_units[dimension]
                normalized_quantity = float(quantity) * multiplier
            else:
                # Keep semantically different units (e.g. cloves vs pieces) separate.
                normalized_quantity = float(quantity)
            key = (canonical_ingredient(name), normalized_unit)
            row = grouped[key]
            row["quantity"] += normalized_quantity * factor
            row["source_meals"].append(meal["name"])
    return [
        {
            "ingredient": ingredient,
            "quantity": round(value["quantity"], 6),
            "unit": unit,
            "source_meals": list(dict.fromkeys(value["source_meals"])),
        }
        for (ingredient, unit), value in grouped.items()
    ]


_UNIT_ALIASES = {
    "gram": "g", "grams": "g", "gr": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kg": "kg",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "ml": "ml",
    "liter": "l", "litre": "l", "liters": "l", "litres": "l", "l": "l",
    "stück": "piece", "stuck": "piece", "pcs": "piece", "pc": "piece",
    "pieces": "piece", "piece": "piece", "unit": "piece", "units": "piece",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "cup": "cup", "cups": "cup",
    "clove": "clove", "cloves": "clove",
    "milligram": "mg", "milligrams": "mg", "mg": "mg",
    "centiliter": "cl", "centiliters": "cl", "centilitre": "cl", "centilitres": "cl", "cl": "cl",
    "ounce": "oz", "ounces": "oz", "oz": "oz",
    "pound": "lb", "pounds": "lb", "lbs": "lb", "lb": "lb",
    "fluid ounce": "fl oz", "fluid ounces": "fl oz", "fl oz": "fl oz", "floz": "fl oz",
    "dozen": "dozen", "dozens": "dozen", "dutzend": "dozen",
    "pinch": "pinch", "pinches": "pinch",
}
_UNIT_BASE = {
    "mg": ("mass", 0.001), "g": ("mass", 1.0), "kg": ("mass", 1000.0),
    "oz": ("mass", 28.349523125), "lb": ("mass", 453.59237),
    "ml": ("volume", 1.0), "cl": ("volume", 10.0), "l": ("volume", 1000.0),
    "fl oz": ("volume", 29.5735295625),
    "tsp": ("volume", 5.0), "tbsp": ("volume", 15.0), "cup": ("volume", 250.0),
    "piece": ("count", 1.0), "dozen": ("count", 12.0),
}


def _normal_unit(value):
    raw = str(value or "piece").strip().lower()
    return _UNIT_ALIASES.get(raw, raw)


def _convert_quantity(quantity, from_unit, to_unit):
    """Convert only well-defined mass, volume and count units; otherwise return None."""
    source, target = _normal_unit(from_unit), _normal_unit(to_unit)
    try:
        amount = float(quantity)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount):
        return None
    if source == target:
        return amount
    source_info, target_info = _UNIT_BASE.get(source), _UNIT_BASE.get(target)
    if not source_info or not target_info or source_info[0] != target_info[0]:
        return None
    converted = amount * source_info[1] / target_info[1]
    return converted if math.isfinite(converted) else None


def _number(product, *keys, default=0.0):
    for key in keys:
        value = product.get(key)
        if value is not None:
            try:
                number = float(value)
                if math.isfinite(number):
                    return number
            except (TypeError, ValueError):
                pass
    return default


def _package(product):
    qty = _number(product, "pack_qty", "package_size", default=0.0)
    unit = product.get("unit") or product.get("package_unit") or "piece"
    # Invalid package sizes must never be clamped to a tiny positive quantity:
    # doing so can create millions of fictitious packs and corrupt checkout costs.
    if not math.isfinite(qty) or qty <= 0:
        return None, _normal_unit(unit)
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
    owned = {canonical_ingredient(x) for x in (owned or [])}
    overrides = {
        canonical_ingredient(key): value
        for key, value in (overrides or {}).items()
    }
    pantry = pantry or {}
    output = []

    for requirement in requirements:
        ingredient = canonical_ingredient(requirement["ingredient"])
        requested = float(requirement["quantity"])
        unit = _normal_unit(requirement["unit"])
        pantry_available = 0.0
        # Pantry labels may use a singular, plural, or German synonym of the
        # recipe ingredient. Sum only compatible units; never infer mass from count.
        for pantry_name, pantry_row in pantry.items():
            if canonical_ingredient(pantry_name) != ingredient or not isinstance(pantry_row, dict):
                continue
            converted_pantry = _convert_quantity(
                pantry_row.get("quantity", 0), pantry_row.get("unit"), unit
            )
            if converted_pantry is not None:
                pantry_available += max(0.0, converted_pantry)
        pantry_used = min(requested, pantry_available)
        needed = max(0.0, requested - pantry_used)

        base = {
            **requirement,
            "ingredient": ingredient,
            "needed_quantity": round(needed, 6),
            "pantry_used": round(pantry_used, 6),
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
            "match_status": "unmatched",
            "match_reason": None,
            "why": None,
            "badge": "Availability unknown",
            "selected_by_user": False,
        }

        if ingredient in owned or needed <= 0:
            base.update({
                "needed_quantity": 0.0 if ingredient in owned else 0.0,
                "pantry_used": round(requested if ingredient in owned else pantry_used, 6),
                "match_status": "covered",
                "match_reason": "Covered by pantry / marked as owned.",
                "why": "Covered by pantry / marked as owned.",
                "badge": "🏠 Uses Pantry",
            })
            output.append(base)
            continue

        candidates = []
        raw_products = list(adapter.search(ingredient) or [])
        override_id = overrides.get(ingredient)
        for product in raw_products:
            price = product.get("price")
            if price is None or str(product.get("availability") or "").lower() in {
                "unavailable", "out_of_stock", "not_available", "discontinued"
            }:
                continue
            pack_qty, product_unit = _package(product)
            if pack_qty is None:
                continue
            try:
                numeric_price = float(price)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric_price) or numeric_price < 0:
                continue
            needed_in_pack_unit = _convert_quantity(needed, unit, product_unit)
            if needed_in_pack_unit is None or needed_in_pack_unit <= 0:
                continue
            pack_ratio = needed_in_pack_unit / pack_qty
            # The REWE cart handoff accepts at most 99 packs per product.
            # Do not show a basket quantity that checkout would silently truncate.
            if not math.isfinite(pack_ratio) or pack_ratio > 99:
                continue
            packs = max(1, math.ceil(pack_ratio))
            purchased_quantity = packs * pack_qty
            waste_in_pack_unit = max(0.0, purchased_quantity - needed_in_pack_unit)
            checkout_cost = packs * numeric_price
            if not math.isfinite(checkout_cost):
                continue
            consumed_cost = checkout_cost * min(1.0, needed_in_pack_unit / purchased_quantity)
            # Waste is relative to the amount actually required. A 0.2g need
            # with 0.8g leftover is 400% waste, not 80%.
            waste_ratio = waste_in_pack_unit / needed_in_pack_unit if needed_in_pack_unit > 0 else 0.0
            fallback_unit_price = numeric_price / pack_qty
            unit_price = _number(product, "unit_price", "price_per_unit", default=fallback_unit_price)
            if unit_price < 0:
                unit_price = fallback_unit_price
            score = _candidate_score(mode, checkout_cost, waste_ratio, unit_price, len(requirement.get("source_meals", [])), product)
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
            })

        if not candidates:
            base.update({
                "match_reason": "No available catalog product with a compatible unit and a real price was found.",
                "why": "No compatible priced REWE product found.",
            })
            output.append(base)
            continue

        cheapest_total = min(row["checkout_cost"] for row in candidates)
        chosen = min(candidates, key=lambda row: row["score"])
        badge = _badge(mode, chosen["waste_ratio"], len(requirement.get("source_meals", [])),
                       chosen["product"], cheapest_total, chosen["checkout_cost"])
        if chosen["selected_by_user"]:
            badge = "✓ Your choice"
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
            "match_status": "matched",
            "match_reason": "Matched against a priced, available catalog product using compatible units.",
            "why": f"Used in {len(requirement.get('source_meals', []))} meal(s); {round(chosen['waste_ratio'] * 100)}% estimated package leftover.",
            "badge": badge,
            "selected_by_user": chosen["selected_by_user"],
        })
        output.append(base)

    return output



def summarize_waste(items):
    """Aggregate leftover quantities without mixing incompatible units."""
    totals = defaultdict(float)
    for item in items or []:
        try:
            quantity = float(item.get("waste", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(quantity) or quantity <= 0:
            continue
        unit = _normal_unit(item.get("package_unit") or "piece")
        totals[unit] += quantity
    return {unit: round(quantity, 2) for unit, quantity in totals.items()}
