from app.rewe.scraper import ReweCatalogScraper


def main():
    html = """
    <html><body>
      <article>
        <a href="/shop/p/coca-cola-1-5l/123">
          <img src="https://img.rewe.de/product/placeholder.gif"
               data-src="https://img.rewe.de/product/cola.jpg"
               alt="Coca-Cola">
        </a>
        <span>Coca-Cola 1,5 l</span><span>1,49 €</span>
      </article>
      <article>
        <a href="/shop/p/bananen/456">
          <picture>
            <source data-srcset="https://img.rewe.de/product/bananas-small.webp 320w, https://img.rewe.de/product/bananas-large.webp 900w">
            <img src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
                 alt="Bananen">
          </picture>
        </a>
        <span>Bananen 1 kg</span><span>1,29 €</span>
      </article>
      <article>
        <a href="/shop/p/milch/789">
          <img data-original="//img.rewe.de/product/milk.webp" alt="Milch">
        </a>
        <span>Frische Milch 1 l</span><span>1,09 €</span>
      </article>
    </body></html>
    """
    products = ReweCatalogScraper(browser_enabled=False).extract(
        html,
        "https://www.rewe.de/shop/c/getraenke-genussmittel/",
        "getraenke-genussmittel",
    )
    assert len(products) == 3, f"Expected 3 products, got {len(products)}"

    by_id = {product["external_id"]: product for product in products}
    expected = {
        "123": "https://img.rewe.de/product/cola.jpg",
        "456": "https://img.rewe.de/product/bananas-large.webp",
        "789": "https://img.rewe.de/product/milk.webp",
    }
    for external_id, image_url in expected.items():
        actual = by_id[external_id].get("image_url")
        assert actual == image_url, (
            f"Image extraction failed for {external_id}: expected {image_url}, got {actual}"
        )
        assert by_id[external_id]["product_url"].startswith("https://www.rewe.de/shop/p/")

    print(f"REWE image extraction QA passed: {len(expected)}/{len(expected)} product images found")


if __name__ == "__main__":
    main()
