from app.rewe.scraper import ReweCatalogScraper


def main():
    html = '''<html><body><article><a href="/shop/p/coca-cola-1-5l/123"><img src="https://img.rewe.de/product/cola.jpg" alt="Coca-Cola"></a><span>Coca-Cola 1,5 l</span><span>1,49 €</span></article></body></html>'''
    products = ReweCatalogScraper(browser_enabled=False).extract(html, "https://www.rewe.de/shop/c/getraenke-genussmittel/", "getraenke-genussmittel")
    assert products, "Expected one product from REWE product card"
    cola = products[0]
    assert cola["product_url"].startswith("https://www.rewe.de/shop/p/"), cola
    assert cola.get("image_url") == "https://img.rewe.de/product/cola.jpg", cola
    print("REWE product image extraction QA passed")


if __name__ == "__main__":
    main()
