import math
from collections import defaultdict

STRATEGIES = {
    "maximum-savings",
    "best-value",
    "plan-efficiency",
    "premium",
    "cheapest",
    "less-waste",
}


def consolidate(meals, servings_map):
    grouped = defaultdict(lambda: {"quantity": 0.0, "unit": "", "source_meals": []})
    for meal in meals:
        servings = servings_map.get(meal["id"], 2)
        factor = servings / 2
        for name, quantity, unit in meal["ingredients"]:
            key = name.lower().strip()
            row = grouped[key]
            row["quantity"] += float(quantity) * factor
            row["unit"] = unit
            row["source_meals"].append(meal["name"])
    return [
        {
            "ingredient": key,
            "quantity": round(value["quantity"], 2),
            "unit": value["unit"],
            "source_meals": list(dict.fromkeys(value["source_meals"])),
        }
        for key, value in grouped.items()
    ]


def _number(product, *keys, default=0.0):
    for key in keys:
        value = product.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return default


def _package(product):
    qty = _number(product, "pack_qty", "package_size", default=1.0)
    unit = product.get("unit") or product.get("package_unit") or "unit"
    return max(qty, 0.0001), unit


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
    # Best Value balances checkout cost, waste, unit economics and reuse.
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
        needed = float(requirement["quantity"])
        unit = requirement["unit"]

        pantry_row = pantry.get(ingredient)
        pantry_used = 0.0
        if pantry_row and pantry_row.get("unit") == unit:
            pantry_used = min(needed, max(0.0, float(pantry_row.get("quantity", 0))))
            needed = max(0.0, needed - pantry_used)

        if ingredient in owned or needed <= 0:
            output.append(
                {
                    **requirement,
                    "needed_quantity": round(needed, 2),
                    "pantry_used": round(pantry_used, 2),
                    "product": None,
                    "packs": 0,
                    "total": 0,
                    "waste": 0,
                    "badge": "🏠 Uses Pantry",
                    "why": "Covered by pantry / marked as owned.",
                    "selected_by_user": False,
                }
            )
            continue

        candidates = []
        raw_products = list(adapter.search(ingredient) or [])
        override_id = overrides.get(ingredient)

        for product in raw_products:
            price = product.get("price")
            if price is None:
                continue
            pack_qty, product_unit = _package(product)
            if product_unit != unit and not ({product_unit, unit} <= {"g", "ml"}):
                # Keep units conservative: never pretend incompatible quantities match.
                continue
            packs = max(1, math.ceil(needed / pack_qty))
            waste = max(0.0, packs * pack_qty - needed)
            total = packs * float(price)
            waste_ratio = waste / max(needed, 1.0)
            unit_price = _number(product, "unit_price", "price_per_unit", default=float(price) / pack_qty)
            score = _candidate_score(mode, total, waste_ratio, unit_price, len(requirement["source_meals"]), product)
            product_id = product.get("id")
            selected_by_user = override_id is not None and str(product_id) == str(override_id)
            if selected_by_user:
                score -= 1_000_000
            candidates.append(
                {
                    "score": score,
                    "packs": packs,
                    "total": total,
                    "waste": waste,
                    "waste_ratio": waste_ratio,
                    "unit_price": unit_price,
                    "product": product,
                    "selected_by_user": selected_by_user,
                }
            )

        if not candidates:
            output.append(
                {
                    **requirement,
                    "needed_quantity": round(needed, 2),
                    "pantry_used": round(pantry_used, 2),
                    "product": None,
                    "packs": 0,
                    "total": 0,
                    "waste": 0,
                    "badge": "Availability unknown",
                    "why": "No compatible catalog product found for this quantity/unit.",
                    "selected_by_user": False,
                }
            )
            continue

        cheapest_total = min(row["total"] for row in candidates)
        chosen = min(candidates, key=lambda row: row["score"])
        badge = _badge(
            mode,
            chosen["waste_ratio"],
            len(requirement["source_meals"]),
            chosen["product"],
            cheapest_total,
            chosen["total"],
        )
        if chosen["selected_by_user"]:
            badge = "✓ Your choice"

        output.append(
            {
                **requirement,
                "needed_quantity": round(needed, 2),
                "pantry_used": round(pantry_used, 2),
                "product": chosen["product"],
                "packs": chosen["packs"],
                "total": round(chosen["total"], 2),
                "waste": round(chosen["waste"], 2),
                "waste_ratio": round(chosen["waste_ratio"], 4),
                "badge": badge,
                "why": (
                    f"Used in {len(requirement['source_meals'])} meal(s); "
                    f"{round(chosen['waste_ratio'] * 100)}% estimated package leftover."
                ),
                "selected_by_user": chosen["selected_by_user"],
            }
        )

    return output
