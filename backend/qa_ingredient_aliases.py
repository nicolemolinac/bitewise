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
        _product(5, "REWE Risottoreis Arborio"),
        _product(6, "Ziegenkäse mild"),
        _product(7, "Halloumi Grillkäse"),
        _product(8, "Rucola frisch"),
        _product(9, "Passierte Tomaten"),
        _product(10, "Schwarze Bohnen"),
        _product(11, "Hühnerbrühe"),
        _product(12, "Gemüsebrühe"),
        _product(13, "Grüne Currypaste"),
        _product(14, "Balsamicoessig"),
        _product(15, "Rotweinessig"),
        _product(16, "Tagliatelle"),
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
    for ingredient, product_id in [
        ("arborio rice", 5), ("goat cheese", 6), ("rocket", 8),
        ("passata", 9), ("green curry paste", 13), ("tagliatelle", 16),
    ]:
        results = _multilingual_catalog_search(adapter, ingredient)
        assert any(row["id"] == product_id for row in results), (ingredient, results)

    # Exercise the real SQLAlchemy candidate prefilter, not only the Python
    # semantic matcher. This catches SQL alias/ILIKE regressions.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Product

    engine = create_engine("sqlite:///:memory:")
    Product.__table__.create(engine)
    SqlSession = sessionmaker(bind=engine)
    sql_db = SqlSession()
    try:
        sql_db.add_all([
            Product(
                supermarket="REWE", external_id="sql-1", ingredient="milk",
                name_original="REWE Bio Frische Vollmilch 3,5%",
                name_normalized="rewe bio frische vollmilch 3 5",
                package_size=1000, package_unit="ml", price=1.19,
                price_per_unit=0.00119, availability="available",
            ),
            Product(
                supermarket="REWE", external_id="sql-2", ingredient="coconut milk",
                name_original="Alpro Kokosmilch", name_normalized="alpro kokosmilch",
                package_size=1000, package_unit="ml", price=1.99,
                price_per_unit=0.00199, availability="available",
            ),
            Product(
                supermarket="REWE", external_id="sql-3", ingredient="olive oil",
                name_original="REWE Bio Olivenöl Nativ Extra",
                name_normalized="rewe bio olivenoel nativ extra",
                package_size=500, package_unit="ml", price=4.99,
                price_per_unit=0.00998, availability="available",
            ),
            Product(
                supermarket="REWE", external_id="sql-4", ingredient="chicken breast",
                name_original="Hähnchenbrustfilet", name_normalized="haehnchenbrustfilet",
                package_size=400, package_unit="g", price=4.49,
                price_per_unit=0.011225, availability="available",
            ),
        ])
        sql_db.commit()
        sql_adapter = type("Adapter", (), {"db": sql_db})()
        assert len(_multilingual_catalog_search(sql_adapter, "milk")) == 1
        assert len(_multilingual_catalog_search(sql_adapter, "olive oil")) == 1
        assert len(_multilingual_catalog_search(sql_adapter, "chicken breast")) == 1
        assert _multilingual_catalog_search(sql_adapter, "chicken") == []
    finally:
        sql_db.close()
        engine.dispose()

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
    assert ingredient_matches_product("arborio rice", "REWE Risottoreis")
    assert ingredient_matches_product("goat cheese", "Ziegenkäse")
    assert ingredient_matches_product("halloumi", "Halloumi Grillkäse")
    assert ingredient_matches_product("rocket", "Rucola")
    assert ingredient_matches_product("passata", "Passierte Tomaten")
    assert ingredient_matches_product("black beans", "Schwarze Bohnen")
    assert ingredient_matches_product("chicken stock", "Hühnerbrühe")
    assert ingredient_matches_product("vegetable stock", "Gemüsebrühe")
    assert ingredient_matches_product("green curry paste", "Grüne Currypaste")
    assert ingredient_matches_product("balsamic vinegar", "Balsamicoessig")
    assert ingredient_matches_product("red wine vinegar", "Rotweinessig")
    assert ingredient_matches_product("tagliatelle", "REWE Tagliatelle")
    assert canonical_ingredient("passierte tomaten") == "passata"
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
