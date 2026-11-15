"""Regression checks for REWE package parsing and ingredient quantities."""
from app.rewe.scraper import package
from app.shopping.optimizer import consolidate, _convert_quantity


def main():
    cases = [
        ("REWE Bio Haferflocken 500 g", (500.0, "g")),
        ("Mineralwasser 1,5 l", (1500.0, "ml")),
        ("Getränkedosen 6 x 330 ml", (1980.0, "ml")),
        ("Papiertaschentücher 2x250 Stück", (500.0, "unit")),
        ("Eier 10 St.", (10.0, "unit")),
        ("Joghurt 4 × 125 g", (500.0, "g")),
        ("Olivenöl 500 ml, Grundpreis 1 l", (500.0, "ml")),
        ("Milch 1 l", (1000.0, "ml")),
        ("Hafer 1.000 g", (1000.0, "g")),
        ("Mehl 1.000,5 g", (1000.5, "g")),
        ("Produkt ohne Mengenangabe", (None, None)),
        ("Packung 0 g", (None, None)),
        ("Packung -2 g", (None, None)),
        ("Grundpreis 1,99 € / 100 g", (None, None)),
        ("Packung 4er Pack Eier", (4.0, "unit")),
    ]
    for label, expected in cases:
        actual = package(label)
        assert actual == expected, f"{label!r}: expected {expected}, got {actual}"

    meals = [{"id": "m", "name": "Tiny amount", "ingredients": [["saffron", 0.004, "g"]]}]
    rows = consolidate(meals, {"m": 2})
    assert rows[0]["quantity"] == 0.004, rows
    assert _convert_quantity(1, "kg", "g") == 1000
    assert _convert_quantity(500, "ml", "l") == 0.5
    assert _convert_quantity(float("nan"), "g", "g") is None
    print(f"INGREDIENT REGRESSIONS: PASS ({len(cases)} package cases + precision/unit checks)")


if __name__ == "__main__":
    main()
