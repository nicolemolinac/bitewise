import ast
from pathlib import Path

from app.rewe.scraper import ReweCatalogScraper


def main():
    # Cloud migration must preserve both fields extracted from REWE product cards.
    migration_path = Path(__file__).resolve().parent / "migrate_rewe_snapshot.py"
    migration_tree = ast.parse(migration_path.read_text(encoding="utf-8"))
    product_fields = next(
        ast.literal_eval(node.value)
        for node in migration_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PRODUCT_FIELDS" for target in node.targets)
    )
    assert "product_url" in product_fields, "Cloud migration must preserve REWE product URLs"
    assert "image_url" in product_fields, "Cloud migration must preserve REWE product image URLs"

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
    expected_product_urls = {
        "123": "https://www.rewe.de/shop/p/coca-cola-1-5l/123",
        "456": "https://www.rewe.de/shop/p/bananen/456",
        "789": "https://www.rewe.de/shop/p/milch/789",
    }
    for external_id, image_url in expected.items():
        actual = by_id[external_id].get("image_url")
        assert actual == image_url, (
            f"Image extraction failed for {external_id}: expected {image_url}, got {actual}"
        )
        actual_url = by_id[external_id].get("product_url")
        assert actual_url == expected_product_urls[external_id], (
            f"Product URL extraction failed for {external_id}: "
            f"expected {expected_product_urls[external_id]}, got {actual_url}"
        )

    print(
        f"REWE extraction QA passed: {len(expected)}/{len(expected)} product images "
        f"and {len(expected_product_urls)}/{len(expected_product_urls)} exact product URLs"
    )


if __name__ == "__main__":
    main()
