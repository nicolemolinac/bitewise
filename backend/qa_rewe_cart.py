"""Offline contract checks for safe REWE cart handoff URL validation."""
from app.rewe.scraper import _canonical_product_url


def main():
    assert _canonical_product_url("https://www.rewe.de/shop/p/test-product/123456") == "https://www.rewe.de/shop/p/test-product/123456"
    assert _canonical_product_url("https://rewe.de/shop/p/test-product/123456?foo=bar") == "https://rewe.de/shop/p/test-product/123456?foo=bar"
    for unsafe in (
        "https://evil.example/shop/p/test/1",
        "https://www.rewe.de/shop/c/tiefkuehlkost/",
        "javascript:alert(1)",
        "https://rewe.de.evil.example/shop/p/test/1",
        "",
    ):
        assert _canonical_product_url(unsafe) is None, unsafe
    print("REWE cart handoff QA PASS: only exact REWE product-detail URLs are accepted")


if __name__ == "__main__":
    main()
