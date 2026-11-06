"""Regression checks for REWE scraper package sizes and prices.

Run from backend/: python qa_rewe_pricing.py
"""
from app.rewe.scraper import package, price, price_details


def main():
    assert package("2x200ml") == (400.0, "ml")
    assert package("4 x 50g") == (200.0, "g")
    assert package("500g") == (500.0, "g")

    pack_price, unit_price = price_details(
        "Alete bewusst Kinderkeks Schoko 180g (1 kg = 11,06 €)", 180, "g"
    )
    assert pack_price == 1.99, pack_price
    assert round(unit_price, 5) == 0.01106, unit_price

    pack_price, unit_price = price_details("Barilla Pasta 500g 2,49 €", 500, "g")
    assert pack_price == 2.49, pack_price
    assert round(unit_price, 5) == 0.00498, unit_price

    pack_price, unit_price = price_details("Milch 1l (1 l = 1,29 €)", 1000, "ml")
    assert pack_price == 1.29, pack_price
    assert round(unit_price, 5) == 0.00129, unit_price

    print("REWE scraper pricing QA PASS: multipacks, package checkout prices and normalized unit prices")


if __name__ == "__main__":
    main()
