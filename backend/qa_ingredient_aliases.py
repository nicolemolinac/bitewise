"""Deterministic QA for ingredient alias specificity. Run from backend/."""
from app.ingredient_aliases import ingredient_aliases


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def query(self, _model):
        return FakeQuery(self.rows)


def _product(product_id, name):
    from types import SimpleNamespace
    normalized = " ".join(name.lower().replace("%", " ").split())
    return SimpleNamespace(
        id=product_id, supermarket="REWE", external_id=str(product_id),
        ingredient=normalized, name_original=name, name_normalized=normalized,
        translated_name=None, brand=None, category=None, package_size=1000.0,
        package_unit="ml", price=1.19, price_per_unit=0.00119, currency="EUR",
        product_url=None, image_url=None, availability="available",
        postcode_context="13353", last_checked_at=None,
    )


def main():
    from app.server import _multilingual_catalog_search

    catalog_rows = [
        _product(1, "REWE Bio Frische Vollmilch 3,5%"),
        _product(2, "Alpro Kokosmilch"),
        _product(3, "REWE Bio Olivenöl Nativ Extra"),
        _product(4, "Hähnchenbrustfilet"),
    ]
    adapter = type("Adapter", (), {"db": FakeSession(catalog_rows)})()
    milk_matches = _multilingual_catalog_search(adapter, "milk")
    assert [row["id"] for row in milk_matches] == [1], milk_matches
    oil_matches = _multilingual_catalog_search(adapter, "olive oil")
    assert [row["id"] for row in oil_matches] == [3], oil_matches
    chicken_matches = _multilingual_catalog_search(adapter, "chicken breast")
    assert [row["id"] for row in chicken_matches] == [4], chicken_matches
    chicken_generic_matches = _multilingual_catalog_search(adapter, "chicken")
    assert chicken_generic_matches == [], chicken_generic_matches

    oil = ingredient_aliases("oil")
    assert "olive oil" not in oil
    assert "olivenöl" not in oil
    assert "oil" in oil

    olive_oil = ingredient_aliases("olive oil")
    assert "olivenöl" in olive_oil
    assert "oil" not in olive_oil

    chicken = ingredient_aliases("chicken")
    assert "chicken breast" not in chicken
    assert "hähnchenbrust" not in chicken

    chicken_breast = ingredient_aliases("fresh chicken breast")
    assert "hähnchenbrust" in chicken_breast
    assert "hähnchen" not in chicken_breast

    milk = ingredient_aliases("milk")
    assert "coconut milk" not in milk
    assert "kokosmilch" not in milk

    from app.ingredient_aliases import canonical_ingredient, ingredient_matches_product

    assert ingredient_matches_product("milk", "REWE Bio Frische Vollmilch 3,5%")
    assert not ingredient_matches_product("milk", "Alpro Kokosmilch")
    assert not ingredient_matches_product("oil", "REWE Bio Olivenöl Nativ Extra")
    assert ingredient_matches_product("olive oil", "REWE Bio Olivenöl Nativ Extra")
    assert not ingredient_matches_product("chicken", "Hähnchenbrustfilet")
    assert ingredient_matches_product("chicken breast", "Hähnchenbrustfilet")
    assert not ingredient_matches_product("pepper", "Schwarzer Pfeffer")
    assert ingredient_matches_product("bell pepper", "Rote Paprika")
    assert ingredient_matches_product("saffron", "Safran gemahlen")
    assert canonical_ingredient("tomatoes") == "tomato"
    assert canonical_ingredient("Tomate") == "tomato"
    assert canonical_ingredient("potatoes") == "potato"
    assert canonical_ingredient("chicken breasts") == "chicken breast"
    assert canonical_ingredient("olive oil") == "olive oil"
    assert canonical_ingredient("rice noodles") == "rice noodle"
    # Singular nouns ending in s must not be corrupted as if they were plurals.
    assert canonical_ingredient("couscous") == "couscous"
    assert canonical_ingredient("hummus") == "hummus"
    assert canonical_ingredient("watercress") == "watercress"
    assert canonical_ingredient("molasses") == "molasses"
    assert canonical_ingredient("asparagus") == "asparagus"
    assert "hummu" not in ingredient_aliases("hummus")
    assert "watercres" not in ingredient_aliases("watercress")
    assert ingredient_matches_product("hummus", "REWE Bio Hummus Natur")
    assert ingredient_matches_product("leek", "Porree frisch")
    assert ingredient_matches_product("asparagus", "Grüner Spargel")
    assert ingredient_matches_product("lamb", "Lammfleisch")
    assert ingredient_matches_product("sesame oil", "Sesamöl")
    assert ingredient_matches_product("red cabbage", "Rotkohl frisch")
    assert ingredient_matches_product("white cabbage", "Weißkohl")
    assert not ingredient_matches_product("red cabbage", "Weißkohl")
    assert not ingredient_matches_product("cabbage", "Rotkohl frisch")
    assert not ingredient_matches_product("milk", "Mandelmilch")
    assert not ingredient_matches_product("cream", "Frischkäse")
    assert not ingredient_matches_product("milk", "Milchschokolade")

    print("GENERIC OIL DOES NOT BROADEN TO OLIVE OIL: PASS")
    print("OLIVE OIL KEEPS ITS SPECIFIC GERMAN ALIAS: PASS")
    print("CHICKEN DOES NOT BROADEN TO CHICKEN BREAST: PASS")
    print("CHICKEN BREAST PHRASE RETAINS GERMAN ALIAS: PASS")
    print("MILK DOES NOT BROADEN TO COCONUT MILK: PASS")
    print("BRAND / PRODUCT TITLE MATCHING AND SPECIFICITY COLLISION REGRESSIONS: PASS")


if __name__ == "__main__":
    main()
