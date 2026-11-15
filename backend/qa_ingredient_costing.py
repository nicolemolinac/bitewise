"""Deterministic QA for REWE ingredient matching and checkout/consumption costing.

Run from backend/: python qa_ingredient_costing.py
"""
from app.shopping.optimizer import _convert_ingredient_quantity, _convert_quantity, build_basket, consolidate
from app.database import _snapshot_float, _snapshot_package_dimensions, _snapshot_package_size, _snapshot_pack_pricing
from app.rewe.scraper import _displayed_unit_price, _json_ld_products, _merge_duplicate_product, package, price_details, ReweCatalogScraper
from app.rewe_refresh import _refresh_is_complete_healthy
from app.main import _purchase_pantry_identity, consume_meal_from_pantry, pantry_snapshot
from app.ingredient_aliases import ingredient_name_matches, ingredient_product_match_type, ingredient_substitution_name, ingredient_search_terms


class FakeCatalog:
    def __init__(self, products):
        self.products = products

    def search(self, ingredient):
        return self.products.get(ingredient, [])


class FakePantryQuery:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items


class FakePantryDB:
    def __init__(self, items):
        self.items = items

    def query(self, model):
        return FakePantryQuery(self.items)


def run():
    for malformed_recipe in (
        {"id": "bad-ingredients", "name": "Broken", "ingredients": [["rice", 1]]},
        {"id": "missing-ingredients", "name": "Broken", "ingredients": None},
        {"id": "blank-ingredient", "name": "Broken", "ingredients": [[" ", 1, "g"]]},
    ):
        try:
            consolidate([malformed_recipe], {malformed_recipe["id"]: 2})
        except ValueError:
            pass
        else:
            raise AssertionError("Malformed recipe ingredient structure was silently accepted")
    assert _purchase_pantry_identity("pine nuts", "sunflower seeds", True) == (
        "pine nuts", "sunflower seeds"
    )
    try:
        _purchase_pantry_identity("pine nuts", None, True)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 422
    else:
        raise AssertionError("Substitute purchase without replacement identity was accepted")
    try:
        _purchase_pantry_identity("pine nuts", "pine nuts", True)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 422
    else:
        raise AssertionError("Substitute purchase was stored under the original ingredient")
    _healthy_catalog_report = {
        "status": "healthy",
        "categories_failed": 0,
        "categories_processed": 17,
        "categories_successful": 17,
        "products_found": 12000,
        "products_skipped": 120,
    }
    assert _refresh_is_complete_healthy(_healthy_catalog_report) is True
    _too_many_skips = {**_healthy_catalog_report, "products_skipped": 121}
    assert _refresh_is_complete_healthy(_too_many_skips) is False
    _partial_catalog = {**_healthy_catalog_report, "categories_failed": 1}
    assert _refresh_is_complete_healthy(_partial_catalog) is False
    # Pantry consumption uses compatible units, serving scaling and
    # rejects missing/ambiguous or non-finite inventory records.
    _rice_stock = type("PantryRow", (), {
        "ingredient": "rice", "quantity": 500.0, "unit": "g"
    })()
    _rice_consumed = consume_meal_from_pantry(
        FakePantryDB([_rice_stock]),
        {"base_servings": 2, "ingredients": [["rice", 1, "kg"]]},
        servings=2,
    )
    assert _rice_consumed == [{"ingredient": "rice", "quantity": 0.5, "unit": "kg"}]
    assert _rice_stock.quantity == 0
    _missing_unit_stock = type("PantryRow", (), {
        "ingredient": "onion", "quantity": 4.0, "unit": ""
    })()
    assert consume_meal_from_pantry(
        FakePantryDB([_missing_unit_stock]),
        {"base_servings": 2, "ingredients": [["onion", 2, "piece"]]},
        servings=2,
    ) == []
    assert _missing_unit_stock.quantity == 4.0
    _duplicate_stock_a = type("PantryRow", (), {
        "ingredient": "red onion", "quantity": 1.0, "unit": "piece"
    })()
    _duplicate_stock_b = type("PantryRow", (), {
        "ingredient": "Red-onion", "quantity": 2.0, "unit": "piece"
    })()
    assert consume_meal_from_pantry(
        FakePantryDB([_duplicate_stock_a, _duplicate_stock_b]),
        {"base_servings": 2, "ingredients": [["red onion", 1, "piece"]]},
        servings=2,
    ) == []
    assert _duplicate_stock_a.quantity == 1.0 and _duplicate_stock_b.quantity == 2.0

    _snapshot_duplicate_a = type("PantryRow", (), {
        "ingredient": "red onion", "quantity": 1.0, "unit": "piece", "confidence": "manual"
    })()
    _snapshot_duplicate_b = type("PantryRow", (), {
        "ingredient": "Red-onion", "quantity": 2.0, "unit": "piece", "confidence": "manual"
    })()
    _snapshot_rice = type("PantryRow", (), {
        "ingredient": "rice", "quantity": 500.0, "unit": "g", "confidence": "manual"
    })()
    _pantry_snapshot = pantry_snapshot(FakePantryDB([
        _snapshot_duplicate_a, _snapshot_duplicate_b, _snapshot_rice
    ]))
    assert "red onion" not in _pantry_snapshot
    assert _pantry_snapshot["rice"] == {
        "quantity": 500.0, "unit": "g", "confidence": "manual"
    }

    # Snapshot numeric parsing must reject infinities/NaN and non-positive
    # checkout prices instead of persisting unusable catalog values.
    assert _snapshot_float("nan", 7) == 7
    assert _snapshot_float("inf", 7) == 7
    assert _snapshot_float("1e999", 7) == 7
    assert _snapshot_float("2,50") == 2.5
    assert _snapshot_pack_pricing("Product", 500, "g", "-1.00", "0")[0] is None
    assert _snapshot_pack_pricing("Product", None, "g", "2.50", None) == (None, None)
    assert _snapshot_pack_pricing("Product", "not-a-size", "g", "2.50", None) == (None, None)
    assert _snapshot_pack_pricing("Product", 500, "g", "2.50", "-0.1") == (2.5, 0.005)
    assert _snapshot_pack_pricing("Product 1kg = 0,00 €", 500, "g", "2.50", None) == (None, None)
    assert _snapshot_pack_pricing("Product 100g = 1,20 €", 500, "g", 9.99, 0.0999) == (6.0, 0.012)
    assert _snapshot_pack_pricing("Product 100ml = 0,50 €", 500, "ml", 9.99, 0.0999) == (2.5, 0.005)
    assert _snapshot_pack_pricing("Product 1g = 0,02 €", 100, "g", 9.99, 0.0999) == (2.0, 0.02)
    assert _snapshot_pack_pricing("Product 100g = 1,20 €", 500, "g", None, None) == (6.0, 0.012)
    assert _snapshot_pack_pricing("Product 100ml = 0,50 €", 500, "ml", None, None) == (2.5, 0.005)
    assert _snapshot_pack_pricing("Product 250g = 2,50 €", 500, "g", None, None) == (5.0, 0.01)
    assert _snapshot_pack_pricing("Product 500ml = 1,25 €", 1000, "ml", None, None) == (2.5, 0.0025)
    assert _snapshot_pack_pricing("Product 0g = 1,00 €", 500, "g", 2.5, None) == (None, None)
    assert _snapshot_pack_pricing("Egg 1 St. = 0,30 €", 6, "unit", None, None) == (1.8, 0.3)
    assert _snapshot_pack_pricing("Product 500ml €2,99 (1kg = 5,00 €)", 500, "ml", 5.0, None) == (2.99, 2.99 / 500)
    assert _snapshot_pack_pricing("Product 500g €2,49 (1kg = 5,00 €)", 500, "g", 5.0, None) == (2.49, 2.49 / 500)
    assert _snapshot_pack_pricing(
        "Bebivita 4x90ml 4x90g (1 kg = 7,47 €)", 360, "g", None, None
    ) == (2.69, 7.47 / 1000)
    assert _snapshot_pack_pricing(
        "Hipp juice 330g 330ml (1 l = 4,82 €)", 330, "ml", None, None
    ) == (1.59, 4.82 / 1000)
    assert _snapshot_pack_pricing(
        "Maggi soup 52g 500ml (1 l = 3,18 €)", 52, "g", None, None
    ) == (1.59, 1.59 / 52)
    assert _snapshot_pack_pricing(
        "Maggi soup 108g ergibt 6l (1 l = 0,38 €)", 108, "g", None, None
    ) == (2.28, 2.28 / 108)
    assert _snapshot_pack_pricing("Product 1kg = 5,00 €", 500, "ml", 2.50, None) == (None, None)
    assert _snapshot_package_size("Alete biscuits 180g (1 kg = 11,06 €)", 180, "g") == 180
    # Duplicate SKU observations allow later valid values to replace invalid
    # earlier values, while preserving descriptive data from the first card.
    _merged_duplicate = _merge_duplicate_product(
        {"external_id": "sku-1", "price": 0, "price_per_unit": float("nan"), "package_size": None, "package_unit": None, "name_original": "First title"},
        {"external_id": "sku-1", "price": 2.49, "price_per_unit": 0.00498, "package_size": 500, "package_unit": "g", "name_original": "Second title"},
    )
    assert _merged_duplicate["price"] == 2.49
    assert _merged_duplicate["price_per_unit"] == 0.00498
    assert _merged_duplicate["package_size"] == 500
    assert _merged_duplicate["package_unit"] == "g"
    assert _merged_duplicate["name_original"] == "First title"
    _invalid_duplicate = _merge_duplicate_product(
        {"price": 2.49, "price_per_unit": 0.00498, "package_size": 500, "package_unit": "g"},
        {"price": -1, "price_per_unit": 0, "package_size": float("inf"), "package_unit": ""},
    )
    assert _invalid_duplicate["price"] == 2.49
    assert _invalid_duplicate["price_per_unit"] == 0.00498
    assert _invalid_duplicate["package_size"] == 500
    assert _invalid_duplicate["package_unit"] == "g"
    # When a valid checkout price repairs an invalid observation, its unit
    # price must be recalculated rather than inherited from stale metadata.
    _repaired_price = _merge_duplicate_product(
        {"price": 0, "price_per_unit": 9.99, "package_size": 500, "package_unit": "g"},
        {"price": 2.50, "price_per_unit": float("nan")},
    )
    assert _repaired_price["price"] == 2.50
    assert abs(_repaired_price["price_per_unit"] - 0.005) < 1e-12
    _duplicate_with_stale_positive_unit_price = _merge_duplicate_product(
        {"price": 2.50, "price_per_unit": 0.5, "package_size": 500, "package_unit": "g"},
        {"price": 2.50, "price_per_unit": 0.5, "package_size": 500, "package_unit": "g"},
    )
    assert abs(_duplicate_with_stale_positive_unit_price["price_per_unit"] - 0.005) < 1e-12
    _repaired_without_size = _merge_duplicate_product(
        {"price": 0, "price_per_unit": 9.99, "package_size": None, "package_unit": None},
        {"price": 2.50, "price_per_unit": 0},
    )
    assert _repaired_without_size["price"] == 2.50
    assert _repaired_without_size["price_per_unit"] is None
    # Whitespace-only supplier SKUs are absent IDs, not a shared product key.
    _jsonld_html = BeautifulSoup(
        '<script type="application/ld+json">' + json.dumps({
            "@type": "ItemList",
            "itemListElement": [{
                "item": {
                    "@type": "Product", "sku": "   ",
                    "name": "Chicken Breast 500g",
                    "url": "https://www.rewe.de/shop/p/chicken-breast-500g/123456",
                },
                {
                    "item": {
                        "@type": "Product", "sku": "sku-offer-price",
                        "name": "Chicken Breast 500g",
                        "description": "Former price EUR 9.99",
                        "url": "https://www.rewe.de/shop/p/chicken-breast-500g/654321",
                        "offers": {"@type": "Offer", "price": "2.49", "priceCurrency": "EUR"},
                    }
                }
            }]
        }) + '</script>',
        "html.parser",
    )
    _jsonld_rows = _json_ld_products(_jsonld_html, "https://www.rewe.de", "test")
    assert len(_jsonld_rows) == 2
    assert _jsonld_rows[0]["external_id"]
    assert _jsonld_rows[0]["external_id"].strip() == _jsonld_rows[0]["external_id"]
    _offer_price_row = next(row for row in _jsonld_rows if row["external_id"] == "sku-offer-price")
    assert _offer_price_row["price"] == 2.49
    assert _offer_price_row["price_per_unit"] == 2.49 / 500
    # Catalog health must count only usable checkout prices. Zero, negative,
    # NaN, infinity and malformed strings must not satisfy the HTTP fallback ratio.
    _ingest_report = {"products_created": 0, "products_updated": 0, "products_found": 0, "products_with_price": 0}
    ReweCatalogScraper(browser_enabled=False)._ingest_products(
        _ingest_report,
        [{"price": 0}, {"price": -1}, {"price": "nan"}, {"price": "inf"}, {"price": "bad"}, {"price": 1.25}],
        lambda product, postcode: None if product.get("price") == 0 else True,
        "13353",
    )
    assert _ingest_report["products_found"] == 6
    assert _ingest_report["products_with_price"] == 1
    assert _ingest_report["products_skipped"] == 1
    assert _ingest_report["products_created"] == 5
    # Live REWE parsing must reject non-finite/zero package quantities and
    # prices before they can enter the product catalog.
    assert package("Product 0g") == (None, None)
    assert package("Product 999999999999999999999999999999999999999999999999kg") == (None, None)
    assert package("Product 2x500ml") == (1000, "ml")
    assert package("Product 500g (1 kg = 11,06 €)") == (500, "g")
    assert package("Product 500ml (100 ml = 0,50 €)") == (500, "ml")
    assert _displayed_unit_price("1 kg = 0,00 €") == (None, None)
    assert _displayed_unit_price("1 kg = 999999999999999999999999999999999999999999999999 €") == (None, None)
    assert _displayed_unit_price("1 g = 2,00 €") == (2000.0, "g")
    assert _displayed_unit_price("1 ml = 0,50 €") == (500.0, "ml")
    assert _displayed_unit_price("100 g = 1,20 €") == (12.0, "g")
    assert price_details("€ 0,00", 500, "g") == (None, None)
    assert price_details("€ 2,50", float("inf"), "g") == (2.5, None)
    assert price_details("100 g = 1,20 €", 500, "g") == (6.0, 0.012)
    assert price_details("1 g = 2,00 €", 100, "g") == (200.0, 2.0)
    # Snapshot imports must choose the same final physical size as the live
    # scraper, rather than an earlier partial size embedded in a product title.
    assert _snapshot_package_size("Drink 0,75ml bottle 0,75l", 0.75, "ml") == 750
    assert _snapshot_package_size("Juice 0,75ml pack 2x200ml", 0.75, "ml") == 400
    assert _snapshot_package_size("Yogurt 4x50g family pack 200g", 200, "g") == 200
    assert _snapshot_package_size("Water 2x500ml", 500, "ml") == 1000
    assert _snapshot_package_dimensions("Milk 1l", None, None) == (None, None)
    assert _snapshot_package_dimensions("Milk 1l", 0, "ml") == (None, None)
    assert _snapshot_package_dimensions("Milk 1l", 1000, "ml") == (1000, "ml")
    assert _snapshot_package_dimensions(
        "Hähnchenbrustfilet 1 Stück ca. 450g (1 kg = 16,90 €)", 1, "unit"
    ) == (450.0, "g")
    assert _snapshot_package_dimensions(
        "Bifi 5 Stück 100g (1 kg = 29,90 €)", 5, "unit"
    ) == (100.0, "g")
    assert _snapshot_package_dimensions(
        "Bebivita 4x90ml 4x90g (1 kg = 7,47 €)", 360, "ml"
    ) == (360.0, "g")
    assert _snapshot_package_dimensions(
        "Hipp juice 330g 330ml (1 l = 4,82 €)", 330, "g"
    ) == (330.0, "ml")
    assert _snapshot_package_dimensions(
        "Kneipp shower gel 2x200ml (1 l = 19,98 €)", 1, "g"
    ) == (400.0, "ml")
    assert _snapshot_package_dimensions(
        "Maggi soup 52g 500ml (1 l = 3,18 €)", 52, "g"
    ) == (52.0, "g")
    assert _snapshot_package_dimensions(
        "Maggi soup 52g 500ml (1 l = 3,18 €)", 1, "g"
    ) == (52.0, "g")
    assert _snapshot_package_size("Water 9" + "9" * 400 + "kg", 500, "g") == 500
    assert _snapshot_package_size("Water " + "9" * 5000 + "x500ml", 500, "ml") == 500
    assert _snapshot_package_size("Water 2x500ml", 1, "l") == 1
    # A TypeError inside an intelligence-aware adapter is a real failure, not
    # evidence that it uses the legacy one-argument search signature.
    class BrokenCatalog:
        def search(self, ingredient, intelligence=None):
            raise TypeError("internal catalog normalization failed")

    try:
        build_basket(
            [{"ingredient": "onion", "quantity": 1, "unit": "piece"}],
            BrokenCatalog(),
        )
    except TypeError as exc:
        assert "internal catalog normalization failed" in str(exc)
    else:
        raise AssertionError("Internal catalog TypeError must not be swallowed")

    # The actual product title, not a broad catalog label, must confirm the ingredient.
    assert ingredient_name_matches("trofie pasta", "REWE Trofie") is True
    assert ingredient_name_matches("trofie pasta", "REWE Fusilli") is False
    assert ingredient_name_matches("trofie pasta", "REWE Udon Nudeln") is False
    assert ingredient_name_matches("rice", "REWE Beste Wahl Langkornreis 500g") is True
    assert ingredient_product_match_type("onions", "REWE Speisezwiebeln 1kg") == "exact"
    assert ingredient_product_match_type("frozen french fries", "REWE Beste Wahl Pommes Frites 750g") == "exact"
    assert ingredient_product_match_type("frozen french fries", "ja! Tiefkühlpommes 1kg") == "exact"
    assert "pommes frites" in ingredient_search_terms("frozen french fries")
    assert ingredient_name_matches("parmesan", "Parmigiano Reggiano") is True
    assert ingredient_name_matches("parmesan", "Käse-Wiener") is False
    assert ingredient_name_matches("fresh basil pesto", "Basilikum Pesto") is True
    assert ingredient_name_matches("fresh basil pesto", "Basilikum-Pesto 190g") is True
    assert ingredient_name_matches("cherry tomato", "REWE Cocktailtomaten 250g") is True
    assert ingredient_name_matches("greek yogurt", "Joghurt griechischer Art 500g") is True
    assert ingredient_product_match_type("greek yogurt", "Skyr Natur 500g") == "substitute"
    assert ingredient_name_matches("pine nuts", "Pinienkerne natur") is True
    assert ingredient_product_match_type("trofie pasta", "REWE Fusilli") == "substitute"
    assert ingredient_product_match_type("trofie pasta", "REWE Udon Nudeln") is None
    assert ingredient_product_match_type("parmesan", "Grana Padano") == "substitute"
    assert ingredient_product_match_type("pine nuts", "Sonnenblumenkerne 200g") == "substitute"
    assert ingredient_substitution_name("pine nuts", "REWE Bio Sonnenblumenkerne 200g") == "sunflower seeds"

    catalog = FakeCatalog({
        "rice": [{
            "id": 1, "name_original": "REWE Rice 500g", "package_size": 500,
            "package_unit": "g", "price": 1.50, "price_per_unit": 0.003,
            "availability": "available",
        }],
        "milk": [{
            "id": 2, "name_original": "Milk 1L", "package_size": 1,
            "package_unit": "l", "price": 1.19, "availability": "available",
        }],
        "unknown": [{
            "id": 3, "name_original": "Unknown unit product", "package_size": 1,
            "package_unit": "piece", "price": 2.0, "availability": "available",
        }],
        "unpriced": [{
            "id": 4, "name_original": "No price", "package_size": 100,
            "package_unit": "g", "price": None, "availability": "available",
        }],
        "pine nuts": [{
            "id": 5, "ingredient": "sunflower seeds", "ingredient_match_type": "substitute",
            "ingredient_substitute": "sunflower seeds",
            "name_original": "REWE Bio Sonnenblumenkerne 200g",
            "package_size": 200, "package_unit": "g", "price": 1.29,
            "availability": "available",
        }],
    })
    requirements = [
        {"ingredient": "rice", "quantity": 0.25, "unit": "kg", "source_meals": ["Rice bowl"]},
        {"ingredient": "milk", "quantity": 500, "unit": "ml", "source_meals": ["Pancakes"]},
        {"ingredient": "unknown", "quantity": 2, "unit": "tbsp", "source_meals": ["Sauce"]},
        {"ingredient": "unpriced", "quantity": 50, "unit": "g", "source_meals": ["Soup"]},
    ]
    basket = build_basket(requirements, catalog, mode="cheapest")
    rice, milk, unknown, unpriced = basket

    assert rice["match_status"] == "matched"
    assert rice["packs"] == 1 and rice["checkout_cost"] == 1.5
    assert rice["consumed_cost"] == 0.75
    assert rice["package_quantity"] == 500 and rice["package_unit"] == "g"

    assert milk["match_status"] == "matched"
    assert milk["checkout_cost"] == 1.19 and milk["consumed_cost"] == 0.59

    # Catalog unit-price metadata may be invalid or stale even when positive.
    # Ranking and displayed unit cost derive from checkout price/package size.
    for invalid_unit_price in (0, -0.25, 0.5, 0.000001):
        row = build_basket(
            [{"ingredient": "unit price QA", "quantity": 100, "unit": "g"}],
            FakeCatalog({"unit price QA": [{
                "id": 990, "name_original": "Unit price QA 500g",
                "package_size": 500, "package_unit": "g",
                "price": 2.0, "price_per_unit": invalid_unit_price,
                "availability": "available",
            }]}),
            mode="premium",
        )[0]
        assert row["match_status"] == "matched"
        assert row["unit_cost"] == 0.004

    # A plausible-looking but mismatched positive reference price must not
    # distort ranking or the unit cost shown to the user.
    mismatched_unit_price = build_basket(
        [{"ingredient": "mismatched unit price", "quantity": 100, "unit": "g"}],
        FakeCatalog({"mismatched unit price": [{
            "id": 991, "name_original": "Mismatched Unit Price 500g",
            "package_size": 500, "package_unit": "g",
            "price": 2.0, "price_per_unit": 0.5,
            "availability": "available",
        }]}),
        mode="premium",
    )[0]
    assert mismatched_unit_price["match_status"] == "matched"
    assert mismatched_unit_price["unit_cost"] == 0.004

    # Cross-dimension product packages must report unit cost in the
    # recipe's requested unit, using only an explicit ingredient density.
    honey_cross_unit = build_basket(
        [{"ingredient": "honey", "quantity": 100, "unit": "g"}],
        FakeCatalog({"honey": [{
            "id": 992, "name_original": "Honey 500ml",
            "package_size": 500, "package_unit": "ml",
            "price": 3.0, "price_per_unit": 0.006,
            "availability": "available",
        }]}),
        mode="premium",
    )[0]
    assert honey_cross_unit["match_status"] == "matched"
    assert abs(honey_cross_unit["unit_cost"] - (3.0 / 710.0)) < 1e-6

    # Exact package multiples must not round up because of binary floating
    # point noise (0.30000000000000004 / 0.1 is slightly above three).
    decimal_pack = build_basket(
        [{"ingredient": "decimal rice", "quantity": 0.30000000000000004,
          "unit": "g", "source_meals": ["QA"]}],
        FakeCatalog({"decimal rice": [{
            "id": 301, "name_original": "Tiny rice pack", "package_size": 0.1,
            "package_unit": "g", "price": 0.1, "availability": "available",
        }]}),
    )[0]
    assert decimal_pack["match_status"] == "matched"
    assert decimal_pack["packs"] == 3
    assert decimal_pack["checkout_cost"] == 0.3

    # Basket pack counts must respect the REWE cart endpoint's 99-pack limit;
    # do not advertise a matched quantity that cart handoff silently truncates.
    over_cart_limit = build_basket(
        [{"ingredient": "bulk rice", "quantity": 100, "unit": "g",
          "source_meals": ["QA"]}],
        FakeCatalog({"bulk rice": [{
            "id": 302, "name_original": "One gram rice pack", "package_size": 1,
            "package_unit": "g", "price": 0.01, "availability": "available",
        }]}),
    )[0]
    assert over_cart_limit["match_status"] == "unmatched"
    assert over_cart_limit["packs"] == 0

    assert unknown["match_status"] == "unmatched"
    assert unknown["checkout_cost"] == 0
    assert unpriced["match_status"] == "unmatched"
    assert unpriced["checkout_cost"] == 0

    # Fractional count requirements must measure waste against the actual
    # amount needed; max(needed, 1) understated half-onion leftovers.
    half_onion_catalog = FakeCatalog({
        "onion": [{
            "id": 24, "name_original": "REWE Zwiebel 1 Stück", "package_size": 1,
            "package_unit": "piece", "price": 1.0, "availability": "available",
        }],
    })
    half_onion = build_basket(
        [{"ingredient": "onion", "quantity": 0.5, "unit": "piece", "source_meals": ["QA"]}],
        half_onion_catalog, mode="best-value",
    )[0]
    assert half_onion["waste"] == 0.5
    assert half_onion["waste_ratio"] == 1.0

    malformed_catalog = FakeCatalog({
        "negative price": [{
            "id": 20, "name_original": "Invalid negative price", "package_size": 100,
            "package_unit": "g", "price": -1.0, "availability": "available",
        }],
        "nan price": [{
            "id": 21, "name_original": "Invalid NaN price", "package_size": 100,
            "package_unit": "g", "price": float("nan"), "availability": "available",
        }],
        "zero price": [{
            "id": 24, "name_original": "Invalid zero price", "package_size": 100,
            "package_unit": "g", "price": 0.0, "availability": "available",
        }],
        "zero pack": [{
            "id": 22, "name_original": "Invalid zero pack", "package_size": 0,
            "package_unit": "g", "price": 1.0, "availability": "available",
        }],
        "nan pack": [{
            "id": 23, "name_original": "Invalid NaN pack", "package_size": float("nan"),
            "package_unit": "g", "price": 1.0, "availability": "available",
        }],
        "boolean pack": [{
            "id": 25, "name_original": "Invalid boolean pack", "package_size": True,
            "package_unit": "g", "price": 1.0, "availability": "available",
        }],
        "boolean price": [{
            "id": 26, "name_original": "Invalid boolean price", "package_size": 100,
            "package_unit": "g", "price": True, "availability": "available",
        }],
        "overflow pack": [{
            "id": 28, "name_original": "Invalid overflowing pack",
            "package_size": 10 ** 10000, "package_unit": "g",
            "price": 1.0, "availability": "available",
        }],
    })
    malformed_rows = build_basket([
        {"ingredient": name, "quantity": 10, "unit": "g", "source_meals": ["QA"]}
        for name in ("negative price", "nan price", "zero price", "zero pack", "nan pack", "boolean pack", "boolean price", "overflow pack")
    ], malformed_catalog)
    assert all(row["match_status"] == "unmatched" and row["packs"] == 0 for row in malformed_rows)

    missing_pack_unit_catalog = FakeCatalog({
        "ambiguous pack": [{
            "id": 91, "name_original": "Ambiguous pack size 500",
            "package_size": 500, "price": 2.0, "availability": "available",
        }],
    })
    missing_pack_unit = build_basket(
        [{"ingredient": "ambiguous pack", "quantity": 100, "unit": "g"}],
        missing_pack_unit_catalog,
    )[0]
    assert missing_pack_unit["match_status"] == "unmatched"
    assert missing_pack_unit["product"] is None

    substitute_basket = build_basket(
        [{
            "ingredient": "pine nuts", "quantity": 30, "unit": "g",
            "source_meals": ["Pesto pasta"],
            "ingredient_intelligence": {
                "canonical": "pine nuts",
                "substitution_options": [{
                    "name": "sunflower seeds", "quantity_ratio": 1.5, "confidence": 0.99, "role_preserved": True, "safe_to_auto_apply": True,
                }],
            },
        }],
        catalog,
    )
    assert substitute_basket[0]["match_status"] == "substituted"

    # Exact identity is a hard preference tier, not a finite score bonus:
    # an unusually expensive exact product must not lose to a cheap substitute.
    exact_priority_catalog = FakeCatalog({
        "special ingredient": [
            {"id": 81, "name_original": "Exact special ingredient 100g",
             "package_size": 100, "package_unit": "g", "price": 2000,
             "availability": "available", "ingredient_match_type": "exact"},
            {"id": 82, "name_original": "Cheap substitute 100g",
             "package_size": 100, "package_unit": "g", "price": 1,
             "availability": "available", "ingredient_match_type": "substitute",
             "ingredient_substitute": "replacement ingredient"},
        ],
    })
    exact_priority = build_basket(
        [{"ingredient": "special ingredient", "quantity": 10, "unit": "g"}],
        exact_priority_catalog, mode="cheapest",
    )[0]
    assert exact_priority["product"]["id"] == 81
    assert exact_priority["match_status"] == "matched"

    # An invalid explicit AI ratio must not degrade to a 1:1 substitution.
    malformed_ratio_catalog = FakeCatalog({
        "custom cooking fat": [{
            "id": 6, "name_original": "REWE Rapsöl 500ml", "package_size": 500,
            "package_unit": "ml", "price": 1.50, "price_per_unit": 0.003,
            "availability": "available", "ingredient_match_type": "substitute",
            "ingredient_substitute": "rapeseed oil",
        }],
    })
    malformed_ratio_basket = build_basket(
        [{
            "ingredient": "custom cooking fat", "quantity": 20, "unit": "ml",
            "source_meals": ["Test"],
            "ingredient_intelligence": {
                "canonical": "custom cooking fat",
                "substitution_options": [{
                    "name": "rapeseed oil", "quantity_ratio": 0,
                }],
            },
        }],
        malformed_ratio_catalog, mode="cheapest",
    )
    assert malformed_ratio_basket[0]["match_status"] == "unmatched"
    assert malformed_ratio_basket[0]["product"] is None
    assert substitute_basket[0]["product"]["ingredient_substitute"] == "sunflower seeds"
    assert substitute_basket[0]["quantity_ratio"] == 1.5
    assert substitute_basket[0]["product_needed_quantity"] == 45
    assert substitute_basket[0]["checkout_cost"] == 1.29

    # A substitute must identify the replacement ingredient as well as
    # declare its ratio; otherwise the original quantity cannot be reused.
    unidentified_substitute = build_basket(
        [{"ingredient": "custom cooking fat", "quantity": 20, "unit": "ml",
          "ingredient_intelligence": {"canonical": "custom cooking fat",
              "substitution_options": [{"name": "rapeseed oil", "quantity_ratio": 1.0, "confidence": 0.99, "role_preserved": True, "safe_to_auto_apply": True}]}}],
        FakeCatalog({"custom cooking fat": [{
            "id": 27, "name_original": "REWE Rapsöl 500ml", "package_size": 500,
            "package_unit": "ml", "price": 1.5, "availability": "available",
            "ingredient_match_type": "substitute",
        }]}),
    )[0]
    assert unidentified_substitute["match_status"] == "unmatched"
    assert unidentified_substitute["product"] is None

    # Unknown or uncurated substitution ratios must not silently become 1:1.
    uncurated_substitute = build_basket(
        [{"ingredient": "pine nuts", "quantity": 30, "unit": "g",
          "source_meals": ["Pesto pasta"]}],
        catalog,
    )[0]
    assert uncurated_substitute["match_status"] == "unmatched"
    assert uncurated_substitute["product"] is None

    pantry_basket = build_basket(
        [{"ingredient": "rice", "quantity": 1, "unit": "kg", "source_meals": ["Meal"]}],
        catalog, pantry={"rice": {"quantity": 250, "unit": "g"}},
    )
    pantry_rice = pantry_basket[0]
    assert pantry_rice["pantry_used"] == 0.25
    assert pantry_rice["needed_quantity"] == 0.75
    assert pantry_rice["checkout_cost"] == 3.0
    assert pantry_rice["consumed_cost"] == 2.25

    # Shared pantry stock is consumed once across separate requirement rows,
    # including different but convertible units.
    shared_pantry_lines = build_basket([
        {"ingredient": "onion", "quantity": 1, "unit": "piece",
         "unit_validation": {"valid": True}, "source_meals": ["Meal A"]},
        {"ingredient": "onion", "quantity": 100, "unit": "g",
         "unit_validation": {"valid": True}, "source_meals": ["Meal B"]},
    ], FakeCatalog({}), pantry={"onion": {"quantity": 200, "unit": "g"}})
    assert shared_pantry_lines[0]["pantry_used"] == 1
    assert shared_pantry_lines[1]["pantry_used"] == 50
    assert shared_pantry_lines[1]["needed_quantity"] == 50

    # Pantry has no form/preparation metadata, so it cannot be allocated to
    # two conflicting forms of the same named ingredient in one basket.
    ambiguous_form_lines = build_basket([
        {"ingredient": "cumin", "quantity": 100, "unit": "g",
         "ingredient_form": "whole", "unit_validation": {"valid": True}},
        {"ingredient": "cumin", "quantity": 100, "unit": "g",
         "ingredient_form": "powder", "unit_validation": {"valid": True}},
    ], FakeCatalog({}), pantry={"cumin": {"quantity": 200, "unit": "g"}})
    assert [row["pantry_used"] for row in ambiguous_form_lines] == [0, 0]
    assert [row["needed_quantity"] for row in ambiguous_form_lines] == [100, 100]

    mixed_units = consolidate([
        {"id": "a", "name": "Chicken bowl", "ingredients": [["chicken breast", 200, "g"], ["milk", 100, "ml"], ["garlic", 2, "cloves"]]},
        {"id": "b", "name": "Chicken pasta", "ingredients": [["chicken breast", 0.3, "kg"], ["milk", 0.5, "l"], ["garlic", 1, "unit"]]},
    ], {"a": 2, "b": 2})
    chicken = next(row for row in mixed_units if row["ingredient"] == "chicken breast")
    milk_total = next(row for row in mixed_units if row["ingredient"] == "milk")
    garlic_rows = [row for row in mixed_units if row["ingredient"] == "garlic"]
    assert chicken["quantity"] == 500 and chicken["unit"] == "g"
    assert milk_total["quantity"] == 600 and milk_total["unit"] == "ml"
    assert len(garlic_rows) == 2, "Cloves and whole units must not be silently merged"

    # German spoon abbreviations and singular clove are valid recipe units.
    # Spoon measures must convert to ml for real REWE pack-size calculations;
    # cloves remain a distinct count unit and must not merge with whole pieces.
    spoon_units = consolidate([
        {"id": "spoons", "name": "Seasoning", "ingredients": [
            ["olive oil", 1, "EL"], ["curry powder", 1, "TL"],
            ["garlic", 1, "clove"], ["garlic", 2, "cloves"],
        ]},
    ], {"spoons": 2})
    oil_spoon = next(row for row in spoon_units if row["ingredient"] == "olive oil")
    curry_spoon = next(row for row in spoon_units if row["ingredient"] == "curry powder")
    garlic_cloves = next(row for row in spoon_units if row["ingredient"] == "garlic")
    assert oil_spoon["quantity"] == 15 and oil_spoon["unit"] == "ml"
    assert curry_spoon["quantity"] == 5 and curry_spoon["unit"] == "ml"
    assert garlic_cloves["quantity"] == 3 and garlic_cloves["unit"] == "cloves"

    # Common US recipe units and additional metric volume units must normalize
    # to the same canonical mass/volume dimensions before basket costing.
    international_units = consolidate([
        {"id": "us-units", "name": "US recipe units", "base_servings": 1,
         "ingredients": [
             ["chicken breast", 8, "oz"], ["milk", 1, "cup"],
             ["olive oil", 2, "fl oz"], ["flour", 1, "lb"],
             ["vegetable stock", 2, "dl"],
         ]},
    ], {"us-units": 1})
    international = {row["ingredient"]: row for row in international_units}
    assert round(international["chicken breast"]["quantity"], 2) == 226.8
    assert international["chicken breast"]["unit"] == "g"
    assert international["milk"]["quantity"] == 250
    assert international["milk"]["unit"] == "ml"
    assert round(international["olive oil"]["quantity"], 2) == 59.15
    assert round(international["flour"]["quantity"], 2) == 453.59
    assert international["vegetable stock"]["quantity"] == 200

    herb_counts = consolidate([
        {"id": "herbs-a", "name": "Herb salad", "ingredients": [
            ["fresh cilantro", 1, "bunch"], ["fresh cilantro", 2, "piece"],
        ]},
        {"id": "herbs-b", "name": "Herb rice", "ingredients": [
            ["fresh cilantro", 1, "Bund"],
        ]},
    ], {"herbs-a": 2, "herbs-b": 2})
    cilantro_bunches = next(row for row in herb_counts if row["unit"] == "bunch")
    cilantro_pieces = next(row for row in herb_counts if row["unit"] == "piece")
    assert cilantro_bunches["quantity"] == 2
    assert cilantro_pieces["quantity"] == 2
    assert len(herb_counts) == 2, "Bunches and loose pieces must not be silently merged"

    # Same ingredient/form/preparation with conflicting substitution ratios
    # must stay as separate basket requirements instead of inheriting the last recipe's ratio.
    profile_ratio_a = {
        "canonical": "neutral cooking fat", "form": "liquid",
        "substitution_options": [{"name": "rapeseed oil", "quantity_ratio": 1.0}],
    }
    profile_ratio_b = {
        "canonical": "neutral cooking fat", "form": "liquid",
        "substitution_options": [{"name": "rapeseed oil", "quantity_ratio": 1.5, "confidence": 0.99, "role_preserved": True, "safe_to_auto_apply": True}],
    }
    profile_separated = consolidate([
        {"id": "ratio-a", "name": "Recipe A", "base_servings": 1,
         "ingredients": [["neutral cooking fat", 10, "ml"]],
         "ingredient_intelligence": {"neutral cooking fat": profile_ratio_a}},
        {"id": "ratio-b", "name": "Recipe B", "base_servings": 1,
         "ingredients": [["neutral cooking fat", 20, "ml"]],
         "ingredient_intelligence": {"neutral cooking fat": profile_ratio_b}},
    ], {"ratio-a": 1, "ratio-b": 1})
    assert len(profile_separated) == 2
    assert {row["quantity"] for row in profile_separated} == {10, 20}
    assert {
        row["ingredient_intelligence"]["substitution_options"][0]["quantity_ratio"]
        for row in profile_separated
    } == {1.0, 1.5}

    assert _convert_quantity(1, "bunch", "piece") is None
    assert _convert_quantity(1, "piece", "bunch") is None
    # Unit validation and shopping normalization must agree on all
    # supported plural/German aliases; otherwise accepted units fail at costing.
    assert _convert_quantity(2, "pinches", "ml") == 0.6
    assert _convert_quantity(1, "stueck", "piece") == 1
    assert _convert_quantity(1, "bundles", "bunch") == 1
    assert _convert_quantity(2, "millilitres", "ml") == 2
    assert _convert_quantity(2, "centilitres", "ml") == 20
    assert _convert_quantity(2, "decilitres", "ml") == 200
    assert _convert_quantity(1, "essloffel", "ml") == 15
    assert _convert_quantity(1, "teeloffel", "ml") == 5

    substitute_catalog = FakeCatalog({
        "trofie pasta": [{
            "id": 5, "name_original": "REWE Fusilli 500g", "package_size": 500,
            "package_unit": "g", "price": 1.50, "price_per_unit": 0.003,
            "availability": "available", "ingredient_match_type": "substitute",
        }],
    })
    substitute_basket = build_basket(
        [{"ingredient": "trofie pasta", "quantity": 200, "unit": "g", "source_meals": ["Pasta"]}],
        substitute_catalog, mode="cheapest",
    )
    assert substitute_basket[0]["match_status"] == "substituted"
    assert substitute_basket[0]["checkout_cost"] == 1.5


    # Whole onions are sold by weight in REWE; use an explicit average-weight estimate.
    onion_catalog = FakeCatalog({
        "onions": [{
            "id": 6, "name_original": "REWE Speisezwiebeln 1kg",
            "package_size": 1000, "package_unit": "g", "price": 1.49,
            "availability": "available", "ingredient_match_type": "exact",
        }],
    })
    onion_basket = build_basket(
        [{"ingredient": "onions", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest",
    )
    assert onion_basket[0]["match_status"] == "matched"
    assert onion_basket[0]["unit_conversion_note"] == "Estimated 150 g per piece of onion."
    assert onion_basket[0]["needed_quantity"] == 2
    assert onion_basket[0]["checkout_cost"] == 1.49
    stale_override_basket = build_basket(
        [{"ingredient": "onions", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest", overrides={"onions": 999},
    )
    assert stale_override_basket[0]["match_status"] == "unmatched"
    assert stale_override_basket[0]["product"] is None
    assert "previously selected product" in stale_override_basket[0]["match_reason"]
    ambiguous_override_basket = build_basket(
        [{"ingredient": "onion", "quantity": 2, "unit": "piece"}],
        FakeCatalog({"onion": [{
            "id": 78, "name_original": "Onion 1kg",
            "package_size": 1000, "package_unit": "g",
            "price": 1.5, "availability": "available",
        }]}),
        overrides={"onion": 78, "Onion!": 79},
    )
    assert ambiguous_override_basket[0]["match_status"] == "unmatched"
    assert "Multiple saved product overrides" in ambiguous_override_basket[0]["match_reason"]
    covered_with_ambiguous_override = build_basket(
        [{"ingredient": "onion", "quantity": 1, "unit": "piece"}],
        FakeCatalog({}),
        overrides={"onion": 78, "Onion!": 79},
        pantry={"onion": {"quantity": 1, "unit": "piece"}},
    )
    assert covered_with_ambiguous_override[0]["match_status"] == "covered"
    punctuation_pantry_basket = build_basket(
        [{"ingredient": "Red-onion", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest",
        pantry={"red onion": {"quantity": 1, "unit": "piece"}},
    )
    assert punctuation_pantry_basket[0]["pantry_used"] == 1
    assert punctuation_pantry_basket[0]["needed_quantity"] == 1
    punctuation_owned_basket = build_basket(
        [{"ingredient": "Red-onion", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest", owned=["red onion"],
    )
    assert punctuation_owned_basket[0]["match_status"] == "covered"
    infinite_pantry_basket = build_basket(
        [{"ingredient": "onion", "quantity": 2, "unit": "piece", "source_meals": ["Chorrillana"]}],
        onion_catalog, mode="cheapest",
        pantry={"onion": {"quantity": float("inf"), "unit": "piece"}},
    )
    assert infinite_pantry_basket[0]["match_status"] == "matched"
    assert infinite_pantry_basket[0]["pantry_used"] == 0
    malformed_pantry_basket = build_basket(
        [{"ingredient": "onion", "quantity": 2, "unit": "piece", "source_meals": ["QA"]}],
        onion_catalog, mode="cheapest", pantry={"onion": "two onions"},
    )
    assert malformed_pantry_basket[0]["pantry_used"] == 0
    assert malformed_pantry_basket[0]["needed_quantity"] == 2
    missing_unit_pantry_basket = build_basket(
        [{"ingredient": "onion", "quantity": 2, "unit": "piece", "source_meals": ["QA"]}],
        onion_catalog, mode="cheapest",
        pantry={"onion": {"quantity": 2}},
    )
    assert missing_unit_pantry_basket[0]["pantry_used"] == 0
    assert missing_unit_pantry_basket[0]["needed_quantity"] == 2
    ambiguous_pantry_basket = build_basket(
        [{"ingredient": "red onion", "quantity": 3, "unit": "piece", "source_meals": ["QA"]}],
        onion_catalog, mode="cheapest",
        pantry={
            "red onion": {"quantity": 1, "unit": "piece"},
            "Red-onion": {"quantity": 2, "unit": "piece"},
        },
    )
    # Normalized duplicate keys are ambiguous; neither entry may silently
    # overwrite the other or make the recipe appear covered.
    assert ambiguous_pantry_basket[0]["pantry_used"] == 0
    assert ambiguous_pantry_basket[0]["needed_quantity"] == 3
    assert ambiguous_pantry_basket[0]["match_status"] == "matched"

    fries_catalog = FakeCatalog({
        "frozen french fries": [{
            "id": 7, "name_original": "REWE Beste Wahl Pommes Frites 750g",
            "package_size": 750, "package_unit": "g", "price": 1.99,
            "availability": "available", "ingredient_match_type": "exact",
        }],
    })
    fries_basket = build_basket(
        [{"ingredient": "frozen french fries", "quantity": 300, "unit": "g", "source_meals": ["Chorrillana"]}],
        fries_catalog, mode="cheapest",
    )
    assert fries_basket[0]["match_status"] == "matched"
    assert fries_basket[0]["checkout_cost"] == 1.99

    # Explicit mass/volume estimates for dressings and count/weight estimates for Romaine.
    mayo_ml, mayo_note = _convert_ingredient_quantity(30, "g", "ml", "mayonnaise")
    caesar_ml, caesar_note = _convert_ingredient_quantity(40, "g", "ml", "caesar dressing")
    romaine_pieces, romaine_note = _convert_ingredient_quantity(150, "g", "piece", "romaine lettuce")
    assert round(mayo_ml, 1) == 31.6 and "0.95 g/ml" in mayo_note
    assert caesar_ml == 40 and "1 g/ml" in caesar_note
    flour_grams, flour_note = _convert_ingredient_quantity(250, "ml", "g", "wheat flour")
    assert flour_grams == 120 and "0.48 g/ml" in flour_note
    cheese_grams, cheese_note = _convert_ingredient_quantity(2, "slice", "g", "cheese slices")
    assert cheese_grams == 40 and "20 g per slice" in cheese_note
    assert romaine_pieces == 1.5 and "100 g per piece" in romaine_note
    for invalid_amount in (-1, float("nan"), float("inf"), True):
        assert _convert_ingredient_quantity(invalid_amount, "g", "g", "onion") == (None, None)
    # Search aliases are broader than safe quantity aliases: bare pepper/paprika
    # can mean seasoning and must not inherit a whole bell-pepper weight.
    assert _convert_ingredient_quantity(1, "piece", "g", "pepper") == (None, None)
    assert _convert_ingredient_quantity(1, "piece", "g", "paprika") == (None, None)
    assert _convert_ingredient_quantity(1, "piece", "g", "salat") == (None, None)
    assert _convert_ingredient_quantity(1, "piece", "g", "salad") == (None, None)

    chicken_grams, chicken_note = _convert_ingredient_quantity(2, "piece", "g", "chicken breast")
    broccoli_grams, broccoli_note = _convert_ingredient_quantity(1, "piece", "g", "broccoli")
    cilantro_grams, cilantro_note = _convert_ingredient_quantity(1, "bunch", "g", "fresh cilantro")
    bacon_grams, bacon_note = _convert_ingredient_quantity(3, "slice", "g", "bacon")
    assert chicken_grams == 300 and "150 g per piece" in chicken_note
    assert _convert_ingredient_quantity(1, "piece", "g", "turkey bacon") == (None, None)
    assert broccoli_grams == 300 and "300 g per piece" in broccoli_note
    assert cilantro_grams == 30 and "30 g per bunch" in cilantro_note
    # Bunches must not inherit the per-piece estimate for unrelated produce,
    # and a single loose herb piece must not be treated as a whole bunch.
    assert _convert_ingredient_quantity(1, "bunch", "g", "potato") == (None, None)
    assert _convert_ingredient_quantity(1, "piece", "g", "fresh cilantro") == (None, None)
    assert _convert_ingredient_quantity(30, "g", "piece", "fresh cilantro") == (None, None)
    assert bacon_grams == 45 and "15 g per slice" in bacon_note

    honey_grams, honey_note = _convert_ingredient_quantity(15, "ml", "g", "honey")
    cornstarch_grams, starch_note = _convert_ingredient_quantity(15, "ml", "g", "cornstarch")
    tomato_paste_grams, paste_note = _convert_ingredient_quantity(15, "ml", "g", "tomato paste")
    pesto_grams, pesto_note = _convert_ingredient_quantity(15, "ml", "g", "fresh basil pesto")
    assert round(honey_grams, 1) == 21.3 and "1.42 g/ml" in honey_note
    assert round(cornstarch_grams, 2) == 8.25 and "0.55 g/ml" in starch_note
    assert round(tomato_paste_grams, 2) == 15.75 and "1.05 g/ml" in paste_note
    assert pesto_grams == 15 and "1 g/ml" in pesto_note

    # Recipe ingredient quantities are generated for 2 servings and scaled exactly once.
    one_serving = consolidate([
        {"id": "single", "name": "Single portion", "base_servings": 2,
         "ingredients": [["rice", 150, "g"]]},
    ], {"single": 1})
    assert one_serving[0]["quantity"] == 75

    duplicate_names = consolidate([
        {"id": "duplicates", "name": "Duplicate ingredient QA", "base_servings": 1,
         "ingredients": [["Red-onion", 50, "g"], ["red onion", 20, "g"], ["RED ONION", 10, "g"]]},
    ], {"duplicates": 1})
    assert len(duplicate_names) == 1
    assert duplicate_names[0]["ingredient"] == "Red-onion"
    assert duplicate_names[0]["quantity"] == 80

    # Identical ingredient names and units must remain separate when recipe
    # intent differs materially (whole vs ground spice form).
    form_split = consolidate([
        {"id": "whole-cumin", "name": "Whole cumin", "base_servings": 1,
         "ingredients": [["cumin", 5, "g"]],
         "ingredient_intelligence": {"cumin": {"form": "whole"}}},
        {"id": "ground-cumin", "name": "Ground cumin", "base_servings": 1,
         "ingredients": [["cumin", 5, "g"]],
         "ingredient_intelligence": {"cumin": {"form": "powder"}}},
    ], {"whole-cumin": 1, "ground-cumin": 1})
    assert len(form_split) == 2
    assert {row["ingredient_intelligence"]["form"] for row in form_split} == {"whole", "powder"}
    assert {row["ingredient_form"] for row in form_split} == {"whole", "powder"}
    assert sum(row["quantity"] for row in form_split) == 10
    # Metadata lookup must normalize punctuation exactly like the matcher.
    punctuation_profile = consolidate([{
        "id": "punctuation-profile", "name": "Herb QA", "base_servings": 1,
        "ingredients": [["fresh cilantro", 1, "bunch"]],
        "ingredient_intelligence": {
            "fresh-cilantro": {"form": "fresh", "preparation": "chopped"}
        },
    }], {"punctuation-profile": 1})
    assert punctuation_profile[0]["ingredient_form"] == "fresh"
    assert punctuation_profile[0]["ingredient_preparation"] == "chopped"
    preparation_split = consolidate([
        {"id": "chopped-garlic", "name": "Chopped garlic", "base_servings": 1,
         "ingredients": [["garlic", 1, "tbsp"]],
         "ingredient_intelligence": {"garlic": {"form": "fresh", "preparation": "chopped"}}},
        {"id": "whole-garlic", "name": "Whole garlic", "base_servings": 1,
         "ingredients": [["garlic", 1, "tbsp"]],
         "ingredient_intelligence": {"garlic": {"form": "fresh", "preparation": "whole"}}},
    ], {"chopped-garlic": 1, "whole-garlic": 1})
    assert len(preparation_split) == 2
    assert {row["unit_validation"]["valid"] for row in preparation_split} == {True, False}

    bunch_requirement = consolidate([
        {"id": "herbs", "name": "Herb recipe", "base_servings": 1,
         "ingredients": [["fresh cilantro", 1, "Bund"]]},
    ], {"herbs": 1})
    assert bunch_requirement[0]["unit"] == "bunch"
    assert bunch_requirement[0]["quantity"] == 1

    # Invalid generated quantities must never be mistaken for pantry-covered
    # ingredients or silently converted into a zero-quantity shopping row.
    for invalid_quantity in (-2, 0, float("nan"), float("inf"), "not-a-number", True):
        invalid_requirements = consolidate([
            {"id": "invalid", "name": "Invalid quantity", "base_servings": 1,
             "ingredients": [["onion", invalid_quantity, "piece"]]},
        ], {"invalid": 1})
        assert invalid_requirements[0]["quantity"] == 0
        assert invalid_requirements[0]["quantity_validation"]["valid"] is False
        invalid_basket = build_basket(
            invalid_requirements, FakeCatalog({"onion": []}), owned=["onion"]
        )
        assert invalid_basket[0]["match_status"] == "unmatched"
        assert invalid_basket[0]["quantity_validation"]["valid"] is False

    missing_unit_requirement = consolidate([
        {"id": "missing-unit", "name": "Missing unit", "base_servings": 1,
         "ingredients": [["onion", 100, None]]},
    ], {"missing-unit": 1})
    assert missing_unit_requirement[0]["unit"] == ""
    assert missing_unit_requirement[0]["unit_validation"]["valid"] is False
    direct_missing_unit = build_basket(
        [{"ingredient": "onion", "quantity": 1, "source_meals": ["Direct input"]}],
        FakeCatalog({"onion": [{"id": 99, "name_original": "REWE Zwiebel 1 Stück",
                                "package_size": 1, "package_unit": "piece",
                                "price": 0.99, "availability": "available"}]}),
    )[0]
    assert direct_missing_unit["match_status"] == "unmatched"
    assert direct_missing_unit["unit_validation"]["valid"] is False
    missing_unit_basket = build_basket(
        missing_unit_requirement, FakeCatalog({"onion": []}), owned=["onion"]
    )
    assert missing_unit_basket[0]["match_status"] == "unmatched"

    # Invalid serving counts must not crash consolidation or create a
    # plausible-looking zero/incorrect shopping quantity.
    for bad_servings in ("not-a-number", float("nan"), float("inf"), 0, True):
        invalid_scaling = consolidate([
            {"id": "bad-serving", "name": "Bad serving count", "base_servings": 2,
             "ingredients": [["rice", 100, "g"]]},
        ], {"bad-serving": bad_servings})
        assert invalid_scaling[0]["quantity"] == 0
        assert invalid_scaling[0]["quantity_validation"]["valid"] is False
        assert "Serving count" in invalid_scaling[0]["quantity_validation"]["reason"]

    for bad_base in ("not-a-number", float("nan"), float("inf"), 0, True):
        invalid_base = consolidate([
            {"id": "bad-base", "name": "Bad base servings", "base_servings": bad_base,
             "ingredients": [["rice", 100, "g"]]},
        ], {"bad-base": 2})
        assert invalid_base[0]["quantity"] == 0
        assert invalid_base[0]["quantity_validation"]["valid"] is False

    four_servings = consolidate([
        {"id": "four", "name": "Four portions", "base_servings": 2,
         "ingredients": [["rice", 150, "g"]]},
    ], {"four": 4})
    assert four_servings[0]["quantity"] == 300

    print("PASS: strict title matching, culinary substitutions, portion scaling, unit conversions, pantry deductions, checkout vs consumed cost, and unmatched handling")


if __name__ == "__main__":
    run()
