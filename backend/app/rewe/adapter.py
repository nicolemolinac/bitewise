import re, requests
from bs4 import BeautifulSoup
from .seed_products import PRODUCTS

class ReweAdapter:
    def __init__(self, live=False): self.live = live

    def search(self, ingredient):
        if self.live:
            try:
                url = "https://www.rewe.de/shop/suche?q=" + requests.utils.quote(ingredient)
                html = requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"}).text
                soup = BeautifulSoup(html, "html.parser")
                results=[]
                for a in soup.select('a[href*="/shop/p/"]')[:8]:
                    text=" ".join(a.stripped_strings)
                    if text and len(text)>3: results.append({"ingredient":ingredient,"name":text,"brand":"REWE","pack_qty":1,"unit":"unit","price":None,"unit_price":None,"url":"https://www.rewe.de"+a.get('href')})
                if results: return results
            except Exception: pass
        exact=[p for p in PRODUCTS if p["ingredient"]==ingredient]
        if exact: return exact
        # fuzzy seed fallback
        return [p for p in PRODUCTS if ingredient.lower() in p["ingredient"].lower() or p["ingredient"].lower() in ingredient.lower()][:3]
