import os
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from .database import SessionLocal, UserEvent, PantryItem, Product, AppSetting, CatalogRun, ProductOverride
from .recipes.seed import MEALS
from .recommendations.engine import score_meal
from .shopping.optimizer import consolidate, build_basket, STRATEGIES
from .rewe.adapter import ReweAdapter
from .rewe.seed_products import PRODUCTS
from .rewe.scraper import ReweCatalogScraper
from .ai.gemini import GeminiService

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
app = FastAPI(title="Bitewise API")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def rows(model):
    db=SessionLocal()
    try: return db.query(model).all()
    finally: db.close()

def setting(db, key, default):
    item=db.get(AppSetting, key)
    return item.value if item else default

def product_dict(product):
    return {"id":product.id,"supermarket":product.supermarket,"ingredient":product.ingredient,"name_original":product.name_original,"name_normalized":product.name_normalized,"translated_name":product.translated_name,"brand":product.brand,"package_size":product.package_size,"package_unit":product.package_unit,"price":product.price,"price_per_unit":product.price_per_unit,"product_url":product.product_url,"availability":product.availability,"postcode_context":product.postcode_context,"last_checked_at":product.last_checked_at}

class EventIn(BaseModel):
    meal_id: str
    action: str | None = None
    event: str | None = None
class PantryIn(BaseModel):
    ingredient: str
    quantity: float = 1
    unit: str = "unit"
    confidence: str = "user_confirmed"
    source: str = "manual"
    notes: str | None = None
    expiry_date: str | None = None
class PlanIn(BaseModel):
    meal_ids: list[str]
    servings: dict[str,int] = {}
class BasketIn(BaseModel):
    meal_ids: list[str]
    servings: dict[str,int] = {}
    owned: list[str] = []
    mode: str = "best-value"
class SettingsIn(BaseModel):
    postcode: str | None = None
    shopping_strategy: str | None = None

@app.get("/api/health")
def health(): return {"ok":True}

@app.get("/api/meals")
def get_meals(mode:str="random"):
    ev=rows(UserEvent); pan=rows(PantryItem)
    meals=sorted(MEALS,key=lambda m:score_meal(m,ev,pan,mode),reverse=True)
    seen={e.meal_id for e in ev if e.action in ("like","skip","cooked","eaten")}
    fresh=[m for m in meals if m["id"] not in seen]
    return {"meals":(fresh+meals)[:12],"mode":mode}

@app.post("/api/events")
def add_event(payload:EventIn):
    action=payload.action or payload.event
    if action not in {"like","skip","dislike","cooked","eaten"}: raise HTTPException(422,"Unsupported event")
    if payload.meal_id not in {m["id"] for m in MEALS}: raise HTTPException(404,"Meal not found")
    db=SessionLocal(); db.add(UserEvent(meal_id=payload.meal_id,action=action)); db.commit(); db.close()
    return {"ok":True,"action":action}

@app.post("/api/meals/{meal_id}/eaten")
def eaten(meal_id:str):
    meal=next((m for m in MEALS if m["id"]==meal_id),None)
    if not meal: raise HTTPException(404,"Meal not found")
    db=SessionLocal()
    for ingredient, amount, unit in meal["ingredients"]:
        item=db.query(PantryItem).filter(PantryItem.ingredient.ilike(ingredient)).first()
        if item and item.unit == unit: item.quantity=max(0,item.quantity-amount)
    db.add(UserEvent(meal_id=meal_id,action="eaten")); db.commit(); db.close()
    return {"ok":True,"message":"Estimated pantry quantities updated."}

@app.get("/api/pantry")
def get_pantry():
    return [{"id":p.id,"ingredient":p.ingredient,"quantity":p.quantity,"unit":p.unit,"confidence":p.confidence,"source":p.source,"notes":p.notes,"expiry_date":p.expiry_date} for p in rows(PantryItem)]

@app.post("/api/pantry")
def add_pantry(payload:PantryIn):
    db=SessionLocal(); old=db.query(PantryItem).filter(PantryItem.ingredient.ilike(payload.ingredient)).first()
    if old:
        for key,value in payload.model_dump().items(): setattr(old,key,value)
    else: db.add(PantryItem(**payload.model_dump()))
    db.commit(); db.close(); return {"ok":True}

@app.patch("/api/pantry/{item_id}")
def update_pantry(item_id:int,payload:PantryIn):
    db=SessionLocal(); row=db.get(PantryItem,item_id)
    if not row: db.close(); raise HTTPException(404,"Pantry item not found")
    for key,value in payload.model_dump().items(): setattr(row,key,value)
    row.confidence="manually_corrected"; db.commit(); db.close(); return {"ok":True}

@app.delete("/api/pantry/{item_id}")
def del_pantry(item_id:int):
    db=SessionLocal(); row=db.get(PantryItem,item_id)
    if row: db.delete(row); db.commit()
    db.close(); return {"ok":True}

@app.get("/api/settings")
def get_settings():
    db=SessionLocal(); data={"postcode":setting(db,"postcode","13353"),"shopping_strategy":setting(db,"shopping_strategy","best-value")}; db.close(); return data

@app.patch("/api/settings")
def update_settings(payload:SettingsIn):
    db=SessionLocal()
    for key,value in payload.model_dump(exclude_none=True).items():
        if key=="shopping_strategy" and value not in STRATEGIES: db.close(); raise HTTPException(422,"Unknown strategy")
        item=db.get(AppSetting,key)
        if item: item.value=value
        else: db.add(AppSetting(key=key,value=value))
    db.commit(); db.close(); return {"ok":True}

@app.get("/api/products")
def products(q:str=""):
    db=SessionLocal(); query=db.query(Product)
    if q: query=query.filter(Product.name_normalized.ilike(f"%{q.lower()}%"))
    data=[product_dict(p) for p in query.limit(50).all()]; db.close(); return {"products":data}

@app.get("/api/rewe/status")
def rewe_status():
    db=SessionLocal(); last=db.query(CatalogRun).order_by(CatalogRun.id.desc()).first(); count=db.query(Product).filter(Product.supermarket=="REWE").count()
    response={"provider":"REWE","postcode":setting(db,"postcode","13353"),"products":count,"status":last.status if last else "not refreshed","last_updated":last.finished_at if last else None,"errors":last.errors if last else 0,"live_data":bool(last)}
    db.close(); return response

@app.post("/api/rewe/refresh")
def rewe_refresh():
    db=SessionLocal(); postcode=setting(db,"postcode","13353"); run=CatalogRun(status="running"); db.add(run); db.commit()
    def upsert(data, postcode):
        existing=db.query(Product).filter_by(supermarket="REWE",external_id=data["external_id"]).first()
        if existing:
            if existing.price != data.get("price"): existing.last_price=existing.price
            for key,value in data.items():
                if hasattr(existing,key): setattr(existing,key,value)
            existing.postcode_context=postcode; existing.last_seen_at=datetime.utcnow(); existing.last_checked_at=datetime.utcnow()
            return False
        db.add(Product(supermarket="REWE",postcode_context=postcode,**data)); return True
    report=ReweCatalogScraper().run(upsert,postcode)
    run.status=report["status"]; run.products_seen=report["products_found"]; run.errors=len(report["errors"]); run.finished_at=datetime.utcnow(); db.commit(); db.close()
    return {"ok":True,**report,"message":"Manual public-category refresh. Prices are a catalog snapshot, not live."}


class PurchaseIn(BaseModel):
    product_id: int
    packs: int = 1
@app.post("/api/shopping/purchase")
def purchase(payload:PurchaseIn):
    db=SessionLocal(); product=db.get(Product,payload.product_id)
    if not product: db.close(); raise HTTPException(404,"Product not found")
    item=db.query(PantryItem).filter(PantryItem.ingredient==product.ingredient).first()
    amount=product.package_size*payload.packs
    if item and item.unit==product.package_unit:
        item.quantity+=amount; item.confidence="estimated"; item.source="purchase"
    else:
        db.add(PantryItem(ingredient=product.ingredient,quantity=amount,unit=product.package_unit,confidence="estimated",source="purchase"))
    db.commit();db.close();return {"ok":True,"added":amount,"unit":product.package_unit}
@app.post("/api/brain-dump")
def brain_dump(prompt:str):
    text=prompt.lower(); mode="random"
    if "cheap" in text or "budget" in text: mode="cheap"
    elif "quick" in text or "easy" in text or "dont want to cook" in text: mode="quick"
    elif "protein" in text: mode="high-protein"
    for cuisine in ("asian","mexican","italian","mediterranean","german"):
        if cuisine in text: mode=cuisine
    return {"mode":mode,"constraints":{"prompt":prompt,"mode":mode}}

class ProductOverrideIn(BaseModel):
    ingredient: str
    product_id: int
@app.post("/api/products/replace")
def replace_product(payload:ProductOverrideIn):
    db=SessionLocal(); product=db.get(Product,payload.product_id)
    if not product or product.ingredient != payload.ingredient.lower(): db.close(); raise HTTPException(422,"Incompatible product")
    row=db.query(ProductOverride).filter_by(ingredient=payload.ingredient.lower()).first()
    if row: row.product_id=product.id
    else: db.add(ProductOverride(ingredient=payload.ingredient.lower(),product_id=product.id))
    db.commit();db.close();return {"ok":True,"product":product_dict(product)}
@app.delete("/api/products/replace/{ingredient}")
def restore_product(ingredient:str):
    db=SessionLocal(); row=db.query(ProductOverride).filter_by(ingredient=ingredient.lower()).first()
    if row: db.delete(row);db.commit()
    db.close();return {"ok":True}

@app.get("/api/products/{product_id}/alternatives")
def alternatives(product_id:int):
    db=SessionLocal(); current=db.get(Product,product_id)
    if not current: db.close(); raise HTTPException(404,"Product not found")
    products=db.query(Product).filter(Product.ingredient==current.ingredient,Product.id!=product_id).limit(20).all()
    result=[product_dict(x) for x in products]; db.close()
    return {"current":product_dict(current),"alternatives":result}

@app.get("/api/products/search")
def search_products(q:str, ingredient:str|None=None):
    db=SessionLocal(); query=db.query(Product).filter(Product.name_normalized.ilike(f"%{q.lower()}%"))
    if ingredient: query=query.filter(Product.ingredient==ingredient.lower())
    result=[product_dict(x) for x in query.limit(30).all()];db.close();return {"products":result}

@app.post("/api/shopping")
def shopping(payload:BasketIn):
    if payload.mode not in STRATEGIES: raise HTTPException(422,"Unknown shopping strategy")
    selected=[m for m in MEALS if m["id"] in payload.meal_ids]
    reqs=consolidate(selected,payload.servings)
    basket=build_basket(reqs,ReweAdapter(os.getenv("REWE_LIVE_ENABLED","false").lower()=="true"),payload.mode,payload.owned)
    total=round(sum(x["total"] for x in basket),2); servings=sum(payload.servings.get(m["id"],2) for m in selected)
    return {"requirements":reqs,"basket":basket,"total":total,"meals":len(selected),"servings":servings,"cost_per_serving":round(total/servings,2) if servings else 0,"waste":round(sum(x["waste"] for x in basket),1),"strategy":payload.mode}

@app.post("/api/ai/meals")
def ai_meals(prompt:str): return {"meals":GeminiService().generate_meals(prompt) or []}
