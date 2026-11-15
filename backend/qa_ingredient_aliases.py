"""Deterministic QA for ingredient alias specificity. Run from backend/."""
from app.ingredient_aliases import ingredient_aliases


def main():
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
    assert canonical_ingredient("chicken breasts") == "chicken breast"
    assert canonical_ingredient("olive oil") == "olive oil"
    assert canonical_ingredient("rice noodles") == "rice noodle"
    assert ingredient_matches_product("leek", "Porree frisch")
    assert ingredient_matches_product("asparagus", "Grüner Spargel")
    assert ingredient_matches_product("lamb", "Lammfleisch")
    assert ingredient_matches_product("sesame oil", "Sesamöl")
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
