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

    assert package("Spice (100 g = 1,49 €)") == (None, None)
    size, unit = package("Spice 200g (100 g = 1,49 €)")
    pack_price, per_gram = price_details("Spice 200g (100 g = 1,49 €)", size, unit)
    assert pack_price == 2.98
    assert abs(per_gram - 0.0149) < 1e-9

    size, unit = package("Sparkling water 2 Stück (1 Stück = 0,50 €)")
    assert size == 2 and unit == "unit"
    pack_price, per_piece = price_details("Sparkling water 2 Stück (1 Stück = 0,50 €)", size, unit)
    assert pack_price == 1.00 and per_piece == 0.50

    size, unit = package("Drink 250ml (100 ml = 0,39 €)")
    assert size == 250 and unit == "ml"
    pack_price, per_ml = price_details("Drink 250ml (100 ml = 0,39 €)", size, unit)
    assert pack_price == 0.98 and abs(per_ml - 0.0039) < 1e-9

    assert package("Invalid product 0g") == (None, None)

    assert package("Rice (1 kg = 4,00 €)") == (None, None)
    assert package("Rice 500g (1 kg = 4,00 €)") == (500.0, "g")
    assert package("Cheese (100 g = 1,99 €)") == (None, None)
    assert package("Cheese 200g (100 g = 1,99 €)") == (200.0, "g")
    pack_price, per_gram = price_details("Cheese 200g (100 g = 1,99 €)", 200, "g")
    assert pack_price == 3.98
    assert abs(per_gram - 0.0199) < 1e-9
    sale_price, sale_per_gram = price_details(
        "Cheese 200g €1,79 (100 g = 0,99 €)", 200, "g"
    )
    assert sale_price == 1.79
    assert abs(sale_per_gram - 0.00895) < 1e-9
    pack_price, per_ml = price_details("Drink 250ml (100 ml = 0,49 €)", 250, "ml")
    assert pack_price == 1.23
    assert abs(per_ml - 0.0049) < 1e-9
    size, unit = package("Rice 500g")
    pack_price, per_gram = price_details("Rice 2,49 €", size, unit)
    assert pack_price == 2.49
    assert abs(per_gram - 0.00498) < 0.000001

    # A reference price must never be mistaken for a checkout price when the
    # package size could not be parsed or its unit does not match.
    assert price_details("Rice (1 kg = 4,00 €)", None, None) == (None, None)
    assert price_details("Rice (1 kg = 4,00 €)", float("nan"), "g") == (None, None)
    assert price_details("Rice (1 kg = 4,00 €)", 500, "ml") == (None, None)
    direct, _ = price_details("Rice 500g (1 kg = 4,00 €) €2,49", None, None)
    assert direct == 2.49

    assert _offer_availability({"price": "2.99"}) == "unknown"
    assert _offer_availability({"price": "2.99", "availability": "https://schema.org/InStock"}) == "available"
    assert _offer_availability({"availability": "https://schema.org/OutOfStock"}) == "unavailable"
    assert _offer_availability([
        {"availability": "https://schema.org/OutOfStock"},
        {"price": "2.99"},
    ]) == "unknown"
    assert _offer_availability([
        {"availability": "https://schema.org/OutOfStock"},
        {"availability": "https://schema.org/InStock"},
    ]) == "available"

    html = """<script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",
    "name":"Rice 500g","description":"1 kg = 4,00 €",
    "offers":{"@type":"Offer","price":"1.79","priceCurrency":"EUR"}}}]}
    </script>"""
    extracted = _json_ld_products(BeautifulSoup(html, "html.parser"), "https://www.rewe.de", "Lebensmittel")
    assert extracted[0]["price"] == 1.79, extracted[0]
    assert extracted[0]["price_per_unit"] == 1.79 / 500
    assert extracted[0]["availability"] == "unknown", extracted[0]

    unparsed_html = """<script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",
    "name":"Loose produce","offers":{"@type":"Offer","price":"0.99",
    "availability":"https://schema.org/InStock"}}}]}
    </script>"""
    unparsed = _json_ld_products(BeautifulSoup(unparsed_html, "html.parser"), "https://www.rewe.de", "Obst & Gemüse")
    assert unparsed[0]["package_size"] == 1
    assert unparsed[0]["package_unit"] == "unknown"
    assert unparsed[0]["price"] == 0.99

    mixed_offer_html = """<script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",
    "name":"Rice 500g","offers":[
      {"@type":"Offer","price":"1.79","availability":"https://schema.org/OutOfStock"},
      {"@type":"Offer","price":"2.49","availability":"https://schema.org/InStock"}
    ]}}]}
    </script>"""
    mixed = _json_ld_products(BeautifulSoup(mixed_offer_html, "html.parser"), "https://www.rewe.de", "Lebensmittel")
    assert mixed[0]["price"] == 2.49
    assert mixed[0]["availability"] == "available"

    mixed_unknown_html = """<script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",
    "name":"Rice 500g","offers":[
      {"@type":"Offer","price":"1.79"},
      {"@type":"Offer","price":"2.49","availability":"https://schema.org/InStock"}
    ]}}]}
    </script>"""
    mixed_unknown = _json_ld_products(BeautifulSoup(mixed_unknown_html, "html.parser"), "https://www.rewe.de", "Lebensmittel")
    assert mixed_unknown[0]["price"] == 2.49
    assert mixed_unknown[0]["availability"] == "available"

    duplicate_source_html = """<html><head><script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",
    "sku":"SKU-ABC","name":"Rice 500g","url":"/shop/p/rice-500g/12345",
    "offers":{"@type":"Offer","price":"1.79","availability":"https://schema.org/InStock"}}}]}
    </script></head><body><article>
    <a href="/shop/p/rice-500g/12345">Rice 500g</a><span>1,79 €</span>
    </article></body></html>"""
    from app.rewe.scraper import ReweCatalogScraper
    from app.rewe.scraper import _canonical_product_url
    assert _canonical_product_url("https://www.rewe.de/shop/p/rice/12345?source=search#details") == "https://www.rewe.de/shop/p/rice/12345/"

    duplicate_source = ReweCatalogScraper(delay=0, browser_enabled=False).extract(
        duplicate_source_html, "https://www.rewe.de/shop/c/kochen-backen/", "Kochen & Backen"
    )
    assert len(duplicate_source) == 1, duplicate_source
    assert duplicate_source[0]["external_id"] == "12345"
    assert duplicate_source[0]["price"] == 1.79

    print("REWE price QA PASS: €/kg and €/l converted to pack prices; multipacks normalized")


if __name__ == "__main__":
    main()
