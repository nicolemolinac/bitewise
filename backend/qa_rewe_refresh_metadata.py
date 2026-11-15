"""Regression checks for repair of legacy REWE package-size defaults."""
from types import SimpleNamespace

from app.rewe_refresh import (
    _repair_existing_package_metadata,
    _update_existing_price,
    _valid_rewe_price,
)


def product(size, unit, name):
    return SimpleNamespace(
        package_size=size,
        package_unit=unit,
        name_original=name,
        price_per_unit=0.25,
    )


def main():
    legacy = product(1, "unit", "REWE Bio Bananen")
    result = _repair_existing_package_metadata(legacy)
    assert result == "cleared-legacy-default"
    assert legacy.package_size == 0
    assert legacy.package_unit == "unknown"
    assert legacy.price_per_unit is None

    explicit_count = product(1, "unit", "Eier 10 St.")
    result = _repair_existing_package_metadata(explicit_count)
    assert result == "parsed-from-product-name"
    assert explicit_count.package_size == 10
    assert explicit_count.package_unit == "unit"

    wrong_old_size = product(1, "unit", "REWE Bio Vollmilch 1 l")
    _repair_existing_package_metadata(wrong_old_size)
    assert wrong_old_size.package_size == 1000
    assert wrong_old_size.package_unit == "ml"

    valid_existing = product(500, "g", "Mehl ohne Mengenangabe")
    result = _repair_existing_package_metadata(valid_existing)
    assert result == "unchanged"
    assert valid_existing.package_size == 500
    assert valid_existing.package_unit == "g"

    # A missing or invalid scrape price must not erase the last known checkout price.
    priced = SimpleNamespace(price=1.99, last_price=1.49)
    assert _update_existing_price(priced, None) == "preserved"
    assert priced.price == 1.99 and priced.last_price == 1.49
    assert _update_existing_price(priced, float("nan")) == "preserved"
    assert priced.price == 1.99 and priced.last_price == 1.49
    assert _update_existing_price(priced, -2) == "preserved"
    assert _update_existing_price(priced, True) == "preserved"

    # A valid new price updates the current price and moves the old one to last_price.
    assert _update_existing_price(priced, "2,49") == "updated"
    assert priced.price == 2.49 and priced.last_price == 1.99
    assert _valid_rewe_price(float("inf")) is None
    assert _valid_rewe_price("not a price") is None

    print("REWE LEGACY PACKAGE / PRICE METADATA REPAIR: PASS (11 cases)")


if __name__ == "__main__":
    main()
