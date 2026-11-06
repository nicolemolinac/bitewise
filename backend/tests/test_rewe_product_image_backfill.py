from fill_rewe_product_images import _product_image_from_html


def test_prefers_product_og_image():
    html = """
    <html><head>
      <meta property="og:image" content="//img.rewe.de/product/main.jpg">
    </head><body></body></html>
    """
    assert _product_image_from_html(html, "https://www.rewe.de/shop/p/product-123") == (
        "https://img.rewe.de/product/main.jpg"
    )


def test_extracts_product_json_ld_image():
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"https://schema.org/Product",
       "name":"Test product","image":["https://img.rewe.de/products/test.jpg"]}
      </script>
    </head><body></body></html>
    """
    assert _product_image_from_html(html, "https://www.rewe.de/shop/p/product-123") == (
        "https://img.rewe.de/products/test.jpg"
    )


def test_extracts_lazy_loaded_product_image_when_metadata_missing():
    html = """
    <html><body><main>
      <img src="data:image/gif;base64,placeholder"
           data-src="https://img.rewe.de/products/lazy.jpg">
    </main></body></html>
    """
    assert _product_image_from_html(html, "https://www.rewe.de/shop/p/product-123") == (
        "https://img.rewe.de/products/lazy.jpg"
    )


def test_ignores_placeholder_images():
    html = """
    <html><head><meta property="og:image" content="https://www.rewe.de/logo-placeholder.jpg"></head>
    <body><img src="https://www.rewe.de/assets/logo.png"></body></html>
    """
    assert _product_image_from_html(html, "https://www.rewe.de/shop/p/product-123") is None
