import ast
import csv
import tempfile
from pathlib import Path
from types import SimpleNamespace

from app.rewe.scraper import ReweCatalogScraper
from export_rewe_catalog import write_catalog_export


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

    exporter_path = Path(__file__).resolve().parent / "export_rewe_catalog.py"
    exporter_tree = ast.parse(exporter_path.read_text(encoding="utf-8"))
    export_fields = next(
        ast.literal_eval(node.value)
        for node in exporter_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "FIELDS" for target in node.targets)
    )
    assert "product_url" in export_fields, "Catalog export must preserve direct REWE product URLs"
    assert "image_url" in export_fields, "Catalog export must preserve REWE product image URLs"

    # Test actual CSV serialization, not only the presence of field names.
    fixture = SimpleNamespace(
        **{field: None for field in export_fields},
        id=987654,
        supermarket="REWE",
        external_id="qa-export-123",
        ingredient="cola",
        name_original="QA Cola",
        name_normalized="qa cola",
        package_size=1.5,
        package_unit="l",
        price=1.49,
        price_per_unit=0.993,
        currency="EUR",
        product_url="https://www.rewe.de/shop/p/qa-cola/123",
        image_url="https://img.rewe.de/product/qa-cola.webp",
    )
    with tempfile.TemporaryDirectory(prefix="bitewise-export-roundtrip-") as directory:
        output = Path(directory) / "catalog.csv"
        counts = write_catalog_export([fixture], output)
        with output.open(encoding="utf-8", newline="") as handle:
            exported = next(csv.DictReader(handle))
        assert exported["product_url"] == fixture.product_url, exported
        assert exported["image_url"] == fixture.image_url, exported
        assert counts == {"total": 1, "with_urls": 1, "with_images": 1, "with_prices": 1}, counts

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
    print("REWE export round-trip QA passed: product_url, image_url and price coverage preserved")


if __name__ == "__main__":
    main()
