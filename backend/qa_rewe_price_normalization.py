"""Regression QA for REWE package prices and multi-pack quantity normalization."""
from bs4 import BeautifulSoup
from app.rewe.scraper import _json_ld_products, _offer_availability, package, price_details


def main():
    size, unit = package("Alete Kinderkeks 180g (1 kg = 11,06 €)")
    assert size == 180 and unit == "g"
    pack_price, per_gram = price_details(
        "Alete Kinderkeks 180g (1 kg = 11,06 €)", size, unit
    )
    assert pack_price == 1.99
    assert abs(per_gram - 0.01106) < 0.000001

    size, unit = package("Alete Drink 2x200ml (1 l = 5,48 €)")
    assert size == 400 and unit == "ml"
    pack_price, per_ml = price_details(
        "Alete Drink 2x200ml (1 l = 5,48 €)", size, unit
    )
    assert pack_price == 2.19
    assert abs(per_ml - 0.00548) < 0.000001

    size, unit = package("Rice 500g")
    pack_price, per_gram = price_details("Rice 2,49 €", size, unit)
    assert pack_price == 2.49
    assert abs(per_gram - 0.00498) < 0.000001

    assert _offer_availability({"price": "2.99"}) == "unknown"
    assert _offer_availability({"price": "2.99", "availability": "https://schema.org/InStock"}) == "available"
    assert _offer_availability({"availability": "https://schema.org/OutOfStock"}) == "unavailable"

    html = """<script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",
    "name":"Rice 500g","description":"1 kg = 4,00 €",
    "offers":{"@type":"Offer","price":"1.79","priceCurrency":"EUR"}}}]}
    </script>"""
    extracted = _json_ld_products(BeautifulSoup(html, "html.parser"), "https://www.rewe.de", "Lebensmittel")
    assert extracted[0]["price"] == 1.79, extracted[0]
    assert extracted[0]["price_per_unit"] == 1.79 / 500
    assert extracted[0]["availability"] == "unknown", extracted[0]

    print("REWE price QA PASS: €/kg and €/l converted to pack prices; multipacks normalized")


if __name__ == "__main__":
    main()
