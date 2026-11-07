"""Deterministic QA for the semantics of Bitewise shopping strategies.

No catalog import, network, scraping or Gemini calls. Uses controlled product
fixtures to prove each strategy optimizes the metric promised by its UI label.
Run from backend/: python qa_shopping_strategy_semantics.py
"""
from app.shopping.optimizer import build_basket


class FixtureAdapter:
    def __init__(self, products):
        self.products = products

    def search(self, ingredient):
        return [dict(p) for p in self.products]

    def get_by_id(self, product_id):
        for product in self.products:
            if str(product["id"]) == str(product_id):
                return dict(product)
        return None


def product(pid, name, price, pack_qty, unit_price=None):
    return {
        "id": pid,
        "name_original": name,
        "name_normalized": name.lower(),
        "brand": name.split()[0],
        "price": price,
        "pack_qty": pack_qty,
        "unit": "g",
        "unit_price": unit_price if unit_price is not None else price / pack_qty,
        "ingredient_match_type": "exact",
        "availability": "unknown",
    }


def basket(products, strategy, quantity=100, ingredient="butter"):
    requirement = [{
        "ingredient": ingredient,
        "display_ingredient": ingredient,
        "canonical_ingredient": ingredient,
        "quantity": quantity,
        "unit": "g",
        "source_meals": ["Recipe A", "Recipe B", "Recipe C"],
    }]
    return build_basket(requirement, FixtureAdapter(products), strategy)[0]


def main():
    # Cheapest checkout must minimize the actual amount paid at checkout,
    # not the prorated value of the amount consumed.
    value_products = [
        product("small", "REWE Butter 100g", 3.20, 100),
        product("large", "ja! Butter 150g", 2.00, 150),
    ]
    cheapest = basket(value_products, "maximum-savings")
    assert cheapest["product"]["id"] == "large", cheapest
    assert cheapest["checkout_cost"] == 2.00\n    assert cheapest["badge"] == "💰 Cheapest", cheapest

    # Plan Efficiency must trade a small checkout premium for materially less
    # package waste when the objective changes the preferred candidate.
    efficiency_products = [
        product("wasteful", "REWE Butter 150g", 2.00, 150),
        product("right-size", "REWE Butter 100g", 3.40, 100),
    ]
    best_value = basket(efficiency_products, "best-value")
    plan_efficiency = basket(efficiency_products, "plan-efficiency")
    assert best_value["product"]["id"] == "wasteful", best_value
    assert plan_efficiency["product"]["id"] == "right-size", plan_efficiency\n    assert plan_efficiency["badge"] == "🔥 Best for Plan", plan_efficiency

    # Premium must prefer an actual premium signal when the price difference
    # is within the intended preference trade-off.
    premium_products = [
        product("discount", "ja! Butter 100g", 2.00, 100),
        product("bio", "REWE Bio Butter 100g", 3.40, 100),
    ]
    premium = basket(premium_products, "premium")
    assert premium["product"]["id"] == "bio", premium
    assert premium["badge"] == "✨ Premium", premium

    # Fractional ingredients: 0.2g needed, 1g package means 0.8g waste,
    # therefore 400% of requested quantity, not 80%.
    saffron = basket(
        [product("saffron", "REWE Safran 1g", 1.99, 1)],
        "best-value",
        quantity=0.2,
        ingredient="saffron",
    )
    assert saffron["waste"] == 0.8, saffron
    assert saffron["waste_ratio"] == 4.0, saffron

    # Unit mismatch must never be treated as an equivalent package.
    incompatible = basket(
        [dict(product("drink", "REWE Coconut Drink 1l", 1.99, 1), unit="l")],
        "best-value",
        quantity=100,
        ingredient="butter",
    )
    assert incompatible["match_status"] == "unmatched", incompatible

    print("STRATEGY MAXIMUM-SAVINGS: PASS")
    print("STRATEGY BEST-VALUE VS PLAN-EFFICIENCY: PASS (different justified choices)")
    print("STRATEGY PREMIUM: PASS")
    print("FRACTIONAL-QUANTITY WASTE: PASS (0.2g need / 1g pack = 400%)")
    print("INCOMPATIBLE PACKAGE UNIT: PASS")
    print("SHOPPING STRATEGY SEMANTICS QA: PASS")


if __name__ == "__main__":
    main()
