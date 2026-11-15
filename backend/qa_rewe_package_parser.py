"""Regression tests for REWE package-size parsing. Run from backend/."""
from app.rewe.scraper import package, price


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
        ("Produkt ohne Mengenangabe", (None, None)),
        ("Packung 0 g", (None, None)),
        ("Packung -2 g", (None, None)),
        ("Packung - 2 g", (None, None)),
        ("Grundpreis 1,99 € / 100 g", (None, None)),
        ("Olivenöl 500 ml, Grundpreis 0,99 € / 100 ml", (500.0, "ml")),
        ("Saft 2 x 0,5 l", (1000.0, "ml")),
        ("1 Packung Nudeln", (1.0, "pack")),
        ("1 Flasche Wasser", (1.0, "bottle")),
        ("1 Bund Petersilie", (1.0, "bunch")),
        ("1 Kopf Salat", (1.0, "head")),
        ("2 Zehen Knoblauch", (2.0, "clove")),
        ("1 Flasche Wasser 500 ml", (500.0, "ml")),
        ("1 Glas Oliven 300 g", (300.0, "g")),
        ("1 Dose Tomaten 400 g", (400.0, "g")),
        ("2 Dutzend Eier", (24.0, "unit")),
    ]
    for label, expected in cases:
        actual = package(label)
        assert actual == expected, f"{label!r}: expected {expected}, got {actual}"

    price_cases = [
        ("Grundpreis 1,99 € / 100 g", None),
        ("Grundpreis 1,99 €/kg", None),
        ("Olivenöl 1,49 € Grundpreis 0,30 €/100 ml", 1.49),
        ("Milk 0.99 EUR Grundpreis 0.10 EUR / 100 ml", 0.99),
        ("Product without price", None),
    ]
    for label, expected in price_cases:
        actual = price(label)
        assert actual == expected, f"{label!r}: expected price {expected}, got {actual}"

    print(
        f"REWE PACKAGE + PRICE PARSER: PASS "
        f"({len(cases)} package cases + {len(price_cases)} price cases)"
    )


if __name__ == "__main__":
    main()
