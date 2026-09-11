"""Manual REWE public-category ingestion. No login or checkout automation."""
import json,re,time,hashlib
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

REWE_CATEGORY_URLS=[
"https://www.rewe.de/shop/bonus/","https://www.rewe.de/shop/c/obst-gemuese/","https://www.rewe.de/shop/c/fleisch-wurst-fisch/","https://www.rewe.de/shop/c/kaese-eier-molkerei/","https://www.rewe.de/shop/c/tiefkuehlkost/","https://www.rewe.de/shop/c/brot-cerealien-aufstriche/","https://www.rewe.de/shop/c/kochen-backen/","https://www.rewe.de/shop/c/oele-sossen-gewuerze/","https://www.rewe.de/shop/c/fertiggerichte-konserven/","https://www.rewe.de/shop/c/suesses-salziges/","https://www.rewe.de/shop/c/kaffee-tee-kakao/","https://www.rewe.de/shop/c/getraenke-genussmittel/","https://www.rewe.de/shop/c/drogerie-gesundheit/","https://www.rewe.de/shop/c/baby-kind/","https://www.rewe.de/shop/c/tierbedarf/","https://www.rewe.de/shop/c/kueche-haushalt/","https://www.rewe.de/shop/c/haus-freizeit/"]
HEADERS={"User-Agent":"Bitewise catalog refresher/1.0 (manual local use)","Accept":"text/html,application/xhtml+xml"}
def normalize(value):
 return re.sub(r"[A-Za-z0-9]+"," ",value.lower()).strip()
def package(text):
 m=re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|stk|stk|st\.)",text,re.I)
 if not m:return None,None
 n=float(m.group(1).replace(",","."));u=m.group(2).lower()
 return (n*1000,"g") if u=="kg" else ((n*1000,"ml") if u=="l" else (n,"unit") if u in ("stk","stk","st.") else (n,u))
def price(text):
 m=re.search(r"(\d+[,.]\d{2})\s*(?:eur|euro)",text,re.I)
 return float(m.group(1).replace(",",".")) if m else None
class ReweCatalogScraper:
 def __init__(self,delay=.7,session=None):self.delay=delay;self.session=session or requests.Session()
 def pages(self,start):
  seen=set(); pending=[start]
  while pending:
   url=pending.pop(0).split("#")[0]
   if url in seen:continue
   seen.add(url)
   response=self.session.get(url,headers=HEADERS,timeout=20);response.raise_for_status()
   yield url,response.text
   soup=BeautifulSoup(response.text,"html.parser")
   for a in soup.select("a[href]"):
    href=urljoin(url,a["href"])
    if "/shop/c/" in href and ("page=" in href or "seite=" in href) and href not in seen:pending.append(href)
   time.sleep(self.delay)
 def extract(self,html,url,category):
  soup=BeautifulSoup(html,"html.parser"); found=[]
  for a in soup.select('a[href*="/shop/p/"]'):
   href=urljoin(url,a.get("href","")); text=" ".join(a.stripped_strings)
   if len(text)<4:continue
   box=a.find_parent(["article","li","div"]) or a
   raw=" ".join(box.stripped_strings); size,unit=package(raw); cost=price(raw)
   key=href.rsplit("/",1)[-1].split("?")[0] or hashlib.sha256((text+href).encode()).hexdigest()[:20]
   found.append({"external_id":key,"name_original":text[:300],"name_normalized":normalize(text),"ingredient":normalize(text),"brand":None,"category":category,"package_size":size or 1,"package_unit":unit or "unit","price":cost,"price_per_unit":None,"product_url":href,"availability":"unknown"})
  unique={p["external_id"]:p for p in found};return list(unique.values())
 def run(self,upsert,postcode,urls=REWE_CATEGORY_URLS):
  report={"categories_processed":0,"categories_successful":0,"categories_failed":0,"products_found":0,"products_created":0,"products_updated":0,"errors":[]}
  for start in urls:
   report["categories_processed"]+=1; category=start.rstrip("/").split("/")[-1]
   try:
    count=0
    for url,html in self.pages(start):
     for product in self.extract(html,url,category):
      created=upsert(product,postcode);report["products_created" if created else "products_updated"]+=1;count+=1
    report["products_found"]+=count;report["categories_successful"]+=1
   except Exception as exc:report["categories_failed"]+=1;report["errors"].append({"category":category,"error":str(exc)[:180]})
  report["status"]="failed" if not report["categories_successful"] else ("partial" if report["categories_failed"] else "healthy");return report
