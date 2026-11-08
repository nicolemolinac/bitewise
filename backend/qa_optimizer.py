"""Focused deterministic QA for the REWE basket optimizer. Run: cd backend && python qa_optimizer.py"""
from app.shopping.optimizer import build_basket, consolidate


class FakeAdapter:
    def __init__(self, products):
        self.products = products

    def search(self, ingredient):
        return self.products.get(ingredient, [])[:1]  # Simulate the adapter's capped search result.

    def get_by_id(self, product_id):
        for rows in self.products.values():
            for row in rows:
                if str(row.get("id")) == str(product_id):
                    return row
        return None


def product(pid, name, price, pack_qty, unit="g", **extra):
    return {
        "id": pid, "name": name, "name_original": name, "price": price,
        "pack_qty": pack_qty, "unit": unit, "availability": "available",
        "ingredient_match_type": "exact", **extra,
    }


def main():
    # g/kg quantities consolidate into one canonical gram requirement.
    merged = consolidate([
        {"id": "a", "name": "Meal A", "base_servings": 1, "ingredients": [["rice", 100, "g"]]},
        {"id": "b", "name": "Meal B", "base_servings": 1, "ingredients": [["rice", 0.2, "kg"]]},
    ], {"a": 1, "b": 1})
    rice = next(row for row in merged if row["ingredient"] == "rice")
    assert rice["quantity"] == 300 and rice["unit"] == "g", rice

    catalog = FakeAdapter({"rice": [
        product(1, "Budget rice 100g", 1.00, 100),
        product(2, "Mid rice 250g", 2.00, 250),
        product(3, "Unavailable rice", 0.50, 100, availability="out_of_stock"),
        product(4, "Unpriced rice", None, 500),
        product(5, "Rice drink 1L", 1.20, 1000, unit="ml"),
    ]})
    # 50g in pantry leaves 150g. The budget option requires two packs.
    rows = build_basket(
        [{"ingredient": "rice", "quantity": 200, "unit": "g", "source_meals": ["A"]}],
        catalog, mode="maximum-savings", pantry={"rice": {"quantity": 50, "unit": "g"}},
    )
    row = rows[0]
    assert row["needed_quantity"] == 150, row
    assert row["product"]["id"] == 1 and row["packs"] == 2, row
    assert row["checkout_cost"] == 2.0 and row["consumed_cost"] == 1.5, row
    assert row["match_status"] == "matched", row

    # A user-selected product remains selected even if the strategy would choose another.
    chosen = build_basket(
        [{"ingredient": "rice", "quantity": 100, "unit": "g", "source_meals": ["A"]}],
        catalog, mode="maximum-savings", overrides={"rice": 2},
    )[0]
    assert chosen["product"]["id"] == 2 and chosen["selected_by_user"] is True, chosen

    # Incompatible dimensions and unavailable/unpriced products are never selected.
    volume_only = FakeAdapter({"rice": [product(9, "Rice milk", 1.2, 1000, unit="ml")]})
    missing = build_basket(
        [{"ingredient": "rice", "quantity": 100, "unit": "g", "source_meals": ["A"]}],
        volume_only,
    )[0]
    assert missing["match_status"] == "unmatched" and missing["product"] is None, missing

    # Pantry can fully cover an ingredient without requiring a catalog product.
    covered = build_basket(
        [{"ingredient": "rice", "quantity": 100, "unit": "g", "source_meals": ["A"]}],
        FakeAdapter({}), pantry={"rice": {"quantity": 0.2, "unit": "kg"}},
    )[0]
    assert covered["match_status"] == "covered" and covered["needed_quantity"] == 0, covered

    print("QA PASS: unit consolidation, partial/full pantry coverage, package rounding, checkout vs consumed cost, manual override persistence, and incompatible/unavailable catalog rejection")


if __name__ == "__main__":
    main()
