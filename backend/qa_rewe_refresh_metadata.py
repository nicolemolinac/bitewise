"""Regression checks for repair of legacy REWE package-size defaults."""
from types import SimpleNamespace

from app.rewe_refresh import _repair_existing_package_metadata


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

    print("REWE LEGACY PACKAGE METADATA REPAIR: PASS (4 cases)")


if __name__ == "__main__":
    main()
