"""Regression QA for REWE package prices and multi-pack quantity normalization."""
from app.rewe.scraper import package, price_details


def main():
    size, unit = package("Alete Kinderkeks 180g (1 kg = 11,06 €)")
    assert size == 180 and unit == "g"
    assert package("Alete Kinderkeks (1 kg = 11,06 €)") == (None, None)
    pack_price, per_gram = price_details(
        "Alete Kinderkeks 180g (1 kg = 11,06 €)", size, unit
    )
    assert pack_price == 1.99
    assert abs(per_gram - 0.01106) < 0.000001
    # Promotional checkout price takes precedence over a stale/reference unit price.
    promo_price, promo_per_gram = price_details(
        "Alete Kinderkeks 1,79 € (1 kg = 11,06 €)", size, unit
    )
    assert promo_price == 1.79
    assert abs(promo_per_gram - (1.79 / 180)) < 0.000001

    size, unit = package("Alete Drink 2x200ml (1 l = 5,48 €)")
    assert size == 400 and unit == "ml"
    pack_price, per_ml = price_details(
        "Alete Drink 2x200ml (1 l = 5,48 €)", size, unit
    )
    assert pack_price == 2.19
    assert abs(per_ml - 0.00548) < 0.000001

    # A reference price without a known pack size must never be mistaken for
    # the checkout price; a separate explicit pack price may still be parsed.
    assert price_details("Alete Kinderkeks (1 kg = 11,06 €)") == (None, None)
    assert price_details("Alete Kinderkeks 2,49 € (1 kg = 11,06 €)")[0] == 2.49

    size, unit = package("Rice 500g")
    pack_price, per_gram = price_details("Rice 2,49 €", size, unit)
    assert pack_price == 2.49
    assert abs(per_gram - 0.00498) < 0.000001

    print("REWE price QA PASS: €/kg and €/l converted to pack prices; multipacks normalized")


if __name__ == "__main__":
    main()
