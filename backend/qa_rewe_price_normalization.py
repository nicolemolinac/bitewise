"""Regression QA for REWE package prices and multi-pack quantity normalization."""
from bs4 import BeautifulSoup
from app.rewe.scraper import _json_ld_products, _offer_availability, package, price_details, ReweCatalogScraper


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

    granini_title = "Granini Fresh Schorle 0,75ml (EINWEG) 0,75l (1 l = 2,12 €)"
    granini_size, granini_unit = package(granini_title)
    assert granini_size == 750 and granini_unit == "ml"
    assert price_details(granini_title, granini_size, granini_unit)[0] == 1.59
    assert package("Babywell Aqua Tücher 2x80 Stück 2x80 Stück") == (160, "unit")
    assert package("Toilettenpapier 8x150 Blatt 8x150 Stück") == (1200, "unit")

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
    assert price_details("Drink 250ml (100 ml = 0,49 €)", 250, "ml")[0] == 1.23
    size, unit = package("Rice 500g")
    pack_price, per_gram = price_details("Rice 2,49 €", size, unit)
    assert pack_price == 2.49
    assert abs(per_gram - 0.00498) < 0.000001

    # Repeated REWE title metadata: use the full multipack and the content
    # unit rather than an outer piece count or an earlier malformed size.
    assert package("Wipes 2x80 Stück 2x80 Stück") == (160, "unit")
    assert package("Vape 2x2ml 2 Stück") == (4, "ml")
    assert package("Wine 0,75ml 0,75l (1 l = 10,65 €)") == (750, "ml")
    assert package("Fruit pouch 4x90ml 4x90g (1 kg = 7,47 €)") == (360, "g")

    assert package("Soup 400g 380ml (1 kg = 4,98 €)") == (400, "g")
    assert package("Aioli 250g 235ml (1 kg = 9,16 €)") == (250, "g")
    # Refundable bottle deposits must never be counted as the food's price.
    deposit_only = "Protein drink 330ml (1 l = 9,06 €) zzgl. 0,25 € Pfand"
    deposit_size, deposit_unit = package(deposit_only)
    assert deposit_size == 330 and deposit_unit == "ml"
    deposit_price, deposit_per_ml = price_details(deposit_only, deposit_size, deposit_unit)
    assert deposit_price == 2.99 and abs(deposit_per_ml - (9.06 / 1000)) < 1e-9

    deposit_with_pack_price = "Protein drink 330ml 2,99 € zzgl. 0,25 € Pfand"
    assert price_details(deposit_with_pack_price, 330, "ml")[0] == 2.99
    assert price_details("Water 1L zzgl. 0,25 € Pfand", 1000, "ml")[0] is None
    assert price_details("Water 1L Pfand 0,25 €", 1000, "ml")[0] is None
    assert price_details("Rice 500g 0,00 €", 500, "g")[0] is None
    assert price_details("Rice 500g 0,00 € (1 kg = 4,00 €)", 500, "g")[0] == 2.00

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

    near_match_html = """<html><head><script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",
    "sku":"SKU-MILK","name":"Milk","offers":{"@type":"Offer","price":"1.19"}}}]}
    </script></head><body><article>
    <a href="/shop/p/milk-chocolate/999">Milk chocolate 100g</a>
    </article></body></html>"""
    near_match = ReweCatalogScraper(delay=0, browser_enabled=False).extract(
        near_match_html, "https://www.rewe.de/shop/c/kaffee-tee-kakao/", "Kaffee & Kakao"
    )
    milk_rows = [row for row in near_match if row["name_original"] == "Milk"]
    assert len(milk_rows) == 1 and milk_rows[0]["product_url"] is None

    # Nested title wrappers must not hide the product's own pack size and price.
    nested_card_html = """<html><body><script type="application/ld+json">
      {"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",
      "name":"Rice","offers":{"@type":"Offer","price":"1.79","priceCurrency":"EUR"}}}]}
    </script><div class="product-grid">
      <div class="product-card">
        <div class="product-title"><a href="/shop/p/rice/123">Rice</a></div>
        <div class="product-details"><span>500g</span><span>1,79 €</span></div>
      </div>
      <div class="product-card">
        <div class="product-title"><a href="/shop/p/milk/456">Milk</a></div>
        <div class="product-details"><span>1L</span><span>0,99 €</span></div>
      </div>
    </div></body></html>"""
    extracted_cards = ReweCatalogScraper(delay=0, browser_enabled=False).extract(
        nested_card_html, "https://www.rewe.de/shop/c/test/", "Lebensmittel"
    )
    by_name = {row["name_original"]: row for row in extracted_cards}
    assert by_name["Rice"]["package_size"] == 500 and by_name["Rice"]["package_unit"] == "g"
    assert by_name["Rice"]["price"] == 1.79
    assert by_name["Rice"]["product_url"].rstrip("/").endswith("/rice/123")
    assert by_name["Milk"]["package_size"] == 1000 and by_name["Milk"]["package_unit"] == "ml"
    assert by_name["Milk"]["price"] == 0.99

    print("REWE price QA PASS: reference prices converted to pack prices; multipacks and offers normalized")


if __name__ == "__main__":
    main()
