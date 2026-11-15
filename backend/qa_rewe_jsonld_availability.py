"""Regression checks for REWE structured stock availability."""
from app.rewe.scraper import _offer_price, _schema_availability


def main():
    cases = [
        ({"availability": "https://schema.org/InStock"}, "available"),
        ({"availability": "https://schema.org/LimitedAvailability"}, "available"),
        ({"availability": "https://schema.org/OutOfStock"}, "unavailable"),
        ({"availability": "https://schema.org/SoldOut"}, "unavailable"),
        ({"availability": "https://schema.org/Discontinued"}, "unavailable"),
        ({"price": "1.99"}, "unknown"),
        ({}, "unknown"),
        (None, "unknown"),
    ]
    for offers, expected in cases:
        actual = _schema_availability(offers)
        assert actual == expected, (offers, expected, actual)
    price_cases = [
        (1.99, 1.99),
        ("1,99", 1.99),
        ("1.234,56", 1234.56),
        ("1.234", 1234.0),
        (None, None),
        ("", None),
        ("not a price", None),
        (-1, None),
        (float("nan"), None),
        (float("inf"), None),
        (True, None),
    ]
    for raw, expected in price_cases:
        actual = _offer_price(raw)
        assert actual == expected, (raw, expected, actual)

    print(
        "REWE STRUCTURED AVAILABILITY / PRICE: PASS "
        f"({len(cases)} availability + {len(price_cases)} price cases)"
    )


if __name__ == "__main__":
    main()
