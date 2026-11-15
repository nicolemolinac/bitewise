"""Regression checks for REWE structured stock availability."""
from app.rewe.scraper import _schema_availability


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
    print(f"REWE STRUCTURED AVAILABILITY: PASS ({len(cases)} cases)")


if __name__ == "__main__":
    main()
