import asyncio
import json
import math
import os
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import or_

from .ai.gemini import GeminiService
from .ai.image_resolver import resolve_meal_images
from .database import AppSetting, CatalogRun, PantryConsumption, PantryItem, Plan, PlannedMeal, Product, ProductDetails, ProductIntelligence, ProductOverride, RecipeHistory, SessionLocal, ShoppingState, UserEvent
from .recommendations.engine import build_preference_profile, rank_meals, score_meal
from .recipes.seed import MEALS
from .rewe.scraper import ReweCatalogScraper
from .rewe.seed_products import PRODUCTS
from .ingredient_aliases import ingredient_product_match_type, ingredient_search_terms
from .catalog.intelligence import classify_product
from .shopping.optimizer import STRATEGIES, _convert_quantity, build_basket, consolidate

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
app = FastAPI(title='Bitewise API', version='2.0')
@app.post("/api/meal-photos")
async def meal_photos(request: Request):
    """Resolve aesthetic Google Images photos for a batch of generated meals.

    This route lives in main.py so both app.main:app (local launcher) and
    app.server:app (cloud/extended launcher) expose the same endpoint.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    meals = payload.get("meals", []) if isinstance(payload, dict) else []
    if not isinstance(meals, list):
        raise HTTPException(422, "meals must be a list")
    meals = [
        meal for meal in meals[:12]
        if isinstance(meal, dict) and str(meal.get("name") or "").strip()
    ]
    photos = await asyncio.to_thread(resolve_meal_images, meals)
    return {"photos": photos}


app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.getenv('CORS_ORIGINS','http://localhost:5173').split(',') if x.strip()],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

def rows(model):
 db=SessionLocal()
 try:return db.query(model).all()
 finally:db.close()
def setting(db,key,default):
 item=db.get(AppSetting,key);return item.value if item else default
def normalize_ingredient(value):return re.sub(r'\s+',' ',value.lower().strip())
def product_dict(p):
 if p is None:return None
 return {'id':p.id,'supermarket':p.supermarket,'external_id':p.external_id,'ingredient':p.ingredient,'name_original':p.name_original,'name_normalized':p.name_normalized,'translated_name':p.translated_name,'brand':p.brand,'category':p.category,'package_size':p.package_size,'package_unit':p.package_unit,'price':p.price,'price_per_unit':p.price_per_unit,'currency':p.currency,'product_url':p.product_url,'image_url':p.image_url,'availability':p.availability,'postcode_context':p.postcode_context,'last_checked_at':p.last_checked_at}
def meal_by_id(meal_id):return next((m for m in MEALS if m['id']==meal_id),None)
def pantry_snapshot(db):return {r.ingredient.lower():{'quantity':r.quantity,'unit':r.unit,'confidence':r.confidence} for r in db.query(PantryItem).all()}

class CatalogAdapter:
 def __init__(self,db):self.db=db
 def get_by_id(self,product_id):
  product=self.db.get(Product,product_id)
  return product_dict(product) if product else None
 def _profile(self,product,stored=None):
  if stored is not None:
   return {
    'product_type':stored.product_type,
    'culinary_role':stored.culinary_role,
    'dish_families':json.loads(stored.dish_families_json or '[]'),
    'preparation_state':stored.preparation_state,
    'storage_type':stored.storage_type,
    'convenience_level':stored.convenience_level,
    'is_complete_meal':stored.is_complete_meal,
    'confidence':stored.confidence,
    'evidence':json.loads(stored.evidence_json or '[]'),
    'classifier_version':stored.classifier_version,
   }
  return classify_product({
   'name_original':product.name_original,'name_normalized':product.name_normalized,
   'translated_name':product.translated_name,'brand':product.brand,'category':product.category,
  }).as_dict()
 def search(self,ingredient):
  needle=normalize_ingredient(ingredient)
  # Search aliases against actual product titles across the complete REWE catalog.
  # Product.ingredient is only an import hint; it is never accepted as proof of a match.
  terms=ingredient_search_terms(needle)
  title_filters=[]
  for term in terms:
   pattern=f'%{term}%'
   title_filters.extend([
    Product.name_original.ilike(pattern),Product.name_normalized.ilike(pattern),
    Product.translated_name.ilike(pattern),
   ])
  if not title_filters:return []
  rows=self.db.query(Product).filter(
   Product.supermarket=='REWE'
  ).filter(or_(*title_filters)).all()
  if not rows:
   # Keep the small legacy fixture fallback for isolated demo data, but validate
   # its displayed title with the same strict matcher as real catalog products.
   fallback=[]
   for item in PRODUCTS:
    title=item.get('name') or item.get('ingredient') or ''
    match_type=ingredient_product_match_type(needle,title)
    if not match_type:continue
    fallback.append({
     'id':None,'supermarket':'REWE','ingredient':item.get('ingredient',needle),
     'name_original':title,'name_normalized':title.lower(),'brand':item.get('brand'),
     'package_size':item.get('pack_qty',1),'package_unit':item.get('unit','unit'),
     'price':item.get('price'),'price_per_unit':item.get('unit_price'),
     'product_url':item.get('url'),'availability':'fixture',
     'ingredient_match_type':match_type,
    })
   return fallback
  profile_rows=self.db.query(ProductIntelligence).filter(
   ProductIntelligence.product_id.in_([product.id for product in rows])
  ).all()
  profiles={profile.product_id:profile for profile in profile_rows}
  candidates=[]
  for product in rows:
   title=' '.join(str(value or '') for value in (
    product.name_original,product.name_normalized,product.translated_name
   ))
   match_type=ingredient_product_match_type(needle,title)
   if not match_type:continue
   intelligence=self._profile(product,profiles.get(product.id))
   # A complete prepared dish is not an ingredient match, even when its title
   # happens to contain the requested ingredient (e.g. shrimp curry ready meal).
   if intelligence.get('is_complete_meal'):continue
   item=product_dict(product)
   item['ingredient_match_type']=match_type
   item['intelligence']=intelligence
   candidates.append(item)
  # Return every validated candidate; the basket optimizer, not an arbitrary
  # SQL LIMIT 40, chooses the best package/price/waste trade-off.
  candidates.sort(key=lambda item: (
   0 if item['ingredient_match_type']=='exact' else 1,
   -float(item['intelligence'].get('confidence') or 0),
   float(item.get('price') or 1e12),
  ))
  return candidates

class EventIn(BaseModel):meal_id:str;action:str|None=None;event:str|None=None
class PantryIn(BaseModel):ingredient:str;quantity:float=1;unit:str='unit';confidence:str='user_confirmed';source:str='manual';notes:str|None=None;expiry_date:str|None=None
class PantryPatch(BaseModel):ingredient:str|None=None;quantity:float|None=None;unit:str|None=None;notes:str|None=None;expiry_date:str|None=None
class BasketIn(BaseModel):meal_ids:list[str];servings:dict[str,float]=Field(default_factory=dict);owned:list[str]=Field(default_factory=list);mode:str='best-value'
class SettingsIn(BaseModel):postcode:str|None=None;shopping_strategy:str|None=None
class BrainDumpIn(BaseModel):prompt:str
class PurchaseIn(BaseModel):product_id:int;packs:int=1;ingredient:str|None=None
class ProductOverrideIn(BaseModel):ingredient:str;product_id:int
class ShoppingStateIn(BaseModel):ingredient:str;state:str;product_id:int|None=None;purchased_quantity:float|None=None;purchased_unit:str|None=None
class PlanCreateIn(BaseModel):weeks:int=1;servings:int=2;strategy:str='best-value';budget:float|None=None;start_date:str|None=None;meal_ids:list[str]=Field(default_factory=list)
class PlannedMealPatch(BaseModel):day_index:int|None=None;meal_type:str|None=None;servings:int|None=None
class PlannedMealStatusIn(BaseModel):status:str
class SwapMealIn(BaseModel):meal_id:str|None=None

@app.get('/api/health')
def health():return {'ok':True,'version':'2.0'}
@app.get('/api/meals')
def get_meals(mode:str='random'):
 events=rows(UserEvent);pantry=rows(PantryItem);meals=rank_meals(MEALS,events,pantry,mode);disliked={e.meal_id for e in events if e.action=='dislike'};seen={e.meal_id for e in events if e.action in ('like','skip','cooked','eaten')};eligible=[m for m in meals if m['id'] not in disliked];fresh=[m for m in eligible if m['id'] not in seen];return {'meals':(fresh+eligible)[:12],'mode':mode}
@app.get('/api/meals/{meal_id}')
def get_meal(meal_id:str):
 meal=meal_by_id(meal_id)
 if not meal:raise HTTPException(404,'Meal not found')
 return meal
@app.post('/api/events')
def add_event(payload:EventIn,request:Request):
 action=payload.action or payload.event
 if action not in {'like','skip','dislike','cooked','eaten','undo-dislike'}:raise HTTPException(422,'Unsupported event')
 db=SessionLocal()
 try:
  # AI concepts are persisted independently from the static seed-meal list.
  user=getattr(request.state,'bitewise_user',None) or {}
  owner=str(user.get('id') or user.get('email') or 'local')[:160]
  history=db.query(RecipeHistory).filter_by(user_id=owner,record_key=payload.meal_id).first()
  if not meal_by_id(payload.meal_id) and history is None:raise HTTPException(404,'Meal not found')
  if action=='undo-dislike':
   db.query(UserEvent).filter(UserEvent.meal_id==payload.meal_id,UserEvent.action=='dislike').delete()
   if history:history.status='discovered'
  else:
   db.add(UserEvent(meal_id=payload.meal_id,action=action))
   if history:
    history.status={'like':'saved','skip':'skipped','dislike':'disliked','cooked':'cooked','eaten':'cooked'}.get(action,history.status)
    history.updated_at=datetime.utcnow()
  db.commit()
 finally:db.close()
 return {'ok':True,'action':action}
@app.get('/api/events/dislikes')
def dislikes():
 db=SessionLocal()
 try:ids=[x.meal_id for x in db.query(UserEvent).filter(UserEvent.action=='dislike').all()];return {'meals':[m for m in MEALS if m['id'] in ids]}
 finally:db.close()
def _pantry_unit_base(unit):
 unit=str(unit or '').strip().lower()
 aliases={
  'g':('mass',1.0),'gram':('mass',1.0),'grams':('mass',1.0),
  'kg':('mass',1000.0),'kilogram':('mass',1000.0),'kilograms':('mass',1000.0),
  'ml':('volume',1.0),'milliliter':('volume',1.0),'milliliters':('volume',1.0),
  'l':('volume',1000.0),'liter':('volume',1000.0),'liters':('volume',1000.0),
  'tbsp':('volume',15.0),'tablespoon':('volume',15.0),'tablespoons':('volume',15.0),
  'tsp':('volume',5.0),'teaspoon':('volume',5.0),'teaspoons':('volume',5.0),
  'cup':('volume',250.0),'cups':('volume',250.0),
  'piece':('count',1.0),'pieces':('count',1.0),'pc':('count',1.0),'pcs':('count',1.0),
  'unit':('count',1.0),'units':('count',1.0),'stk':('count',1.0),'st':('count',1.0),
 }
 return aliases.get(unit)


def consume_meal_from_pantry(db,meal,servings=2):
 factor=servings/2
 consumed=[]
 if not meal or not isinstance(meal.get('ingredients'),list):
  return consumed
 for entry in meal['ingredients']:
  if not isinstance(entry,(list,tuple)) or len(entry)<3:
   continue
  ingredient,amount,unit=entry[:3]
  try:
   required=float(amount)*factor
  except (TypeError,ValueError):
   continue
  if required<=0:
   continue
  item=db.query(PantryItem).filter(PantryItem.ingredient.ilike(str(ingredient))).first()
  if not item or item.quantity<=0:
   continue
  recipe_unit=_pantry_unit_base(unit)
  pantry_unit=_pantry_unit_base(item.unit)
  if recipe_unit and pantry_unit:
   if recipe_unit[0]!=pantry_unit[0]:
    continue
   required_base=required*recipe_unit[1]
   available_base=float(item.quantity)*pantry_unit[1]
   used_base=min(available_base,required_base)
   item.quantity=max(0.0,float(item.quantity)-used_base/pantry_unit[1])
   used=used_base/recipe_unit[1]
  elif str(item.unit or '').strip().lower()==str(unit or '').strip().lower():
   used=min(float(item.quantity),required)
   item.quantity=max(0.0,float(item.quantity)-used)
  else:
   # Unknown or incompatible units must never be guessed or consumed.
   continue
  consumed.append({'ingredient':ingredient,'quantity':round(used,3),'unit':unit})
 return consumed
@app.post('/api/meals/{meal_id}/eaten')
def eaten(meal_id:str,servings:int=2):
 meal=meal_by_id(meal_id)
 if not meal:raise HTTPException(404,'Meal not found')
 db=SessionLocal()
 try:consumed=consume_meal_from_pantry(db,meal,servings);db.add(UserEvent(meal_id=meal_id,action='eaten'));db.commit();return {'ok':True,'consumed':consumed,'message':'Estimated pantry quantities updated.'}
 finally:db.close()
@app.get('/api/pantry')
def get_pantry():
 db=SessionLocal()
 try:return [{'id':p.id,'ingredient':p.ingredient,'quantity':p.quantity,'unit':p.unit,'confidence':p.confidence,'source':p.source,'notes':p.notes,'expiry_date':p.expiry_date,'status':'out' if p.quantity<=0 else ('running-low' if p.quantity<=1 else 'available')} for p in db.query(PantryItem).order_by(PantryItem.ingredient).all()]
 finally:db.close()
@app.post('/api/pantry')
def add_pantry(payload:PantryIn):
 if payload.quantity<0:raise HTTPException(422,'Quantity cannot be negative')
 ingredient=normalize_ingredient(payload.ingredient)
 if not ingredient:raise HTTPException(422,'Ingredient is required')
 db=SessionLocal()
 try:
  old=db.query(PantryItem).filter(PantryItem.ingredient.ilike(ingredient)).first();values=payload.model_dump();values['ingredient']=ingredient
  if old:
   for k,v in values.items():setattr(old,k,v)
  else:db.add(PantryItem(**values))
  db.commit();return {'ok':True}
 finally:db.close()
@app.patch('/api/pantry/{item_id}')
def update_pantry(item_id:int,payload:PantryPatch):
 db=SessionLocal()
 try:
  row=db.get(PantryItem,item_id)
  if not row:raise HTTPException(404,'Pantry item not found')
  values=payload.model_dump(exclude_unset=True)
  if 'quantity' in values and values['quantity'] is not None and values['quantity']<0:raise HTTPException(422,'Quantity cannot be negative')
  if values.get('ingredient'):values['ingredient']=normalize_ingredient(values['ingredient'])
  for k,v in values.items():setattr(row,k,v)
  row.confidence='manually_corrected';row.source='manual';db.commit();return {'ok':True}
 finally:db.close()
@app.delete('/api/pantry/{item_id}')
def del_pantry(item_id:int):
 db=SessionLocal()
 try:
  row=db.get(PantryItem,item_id)
  if row:db.delete(row);db.commit()
  return {'ok':True}
 finally:db.close()
@app.get('/api/settings')
def get_settings():
 db=SessionLocal()
 try:return {'postcode':setting(db,'postcode','13353'),'shopping_strategy':setting(db,'shopping_strategy','best-value')}
 finally:db.close()
@app.patch('/api/settings')
def update_settings(payload:SettingsIn):
 db=SessionLocal()
 try:
  values=payload.model_dump(exclude_none=True)
  if 'postcode' in values and not re.fullmatch(r'\d{5}',values['postcode']):raise HTTPException(422,'Postcode must be a 5-digit German postcode')
  if 'shopping_strategy' in values and values['shopping_strategy'] not in STRATEGIES:raise HTTPException(422,'Unknown strategy')
  for k,v in values.items():
   item=db.get(AppSetting,k)
   if item:item.value=v
   else:db.add(AppSetting(key=k,value=v))
  db.commit();return {'ok':True,**values}
 finally:db.close()
@app.get('/api/products')
def products(q:str='',ingredient:str|None=None):
 db=SessionLocal()
 try:
  query=db.query(Product)
  if ingredient:query=query.filter(Product.ingredient==normalize_ingredient(ingredient))
  if q:
   needle=q.lower().strip();query=query.filter(or_(Product.name_normalized.ilike(f'%{needle}%'),Product.name_original.ilike(f'%{needle}%'),Product.translated_name.ilike(f'%{needle}%'),Product.brand.ilike(f'%{needle}%'),Product.ingredient.ilike(f'%{needle}%')))
  return {'products':[product_dict(p) for p in query.limit(80).all()]}
 finally:db.close()
@app.get('/api/products/search')
def search_products(q:str='',ingredient:str|None=None):return products(q=q,ingredient=ingredient)

@app.get('/api/products/intelligence')
def products_intelligence(role:str|None=None,family:str|None=None,complete_meals:bool|None=None,limit:int=40):
 db=SessionLocal()
 try:
  query=db.query(Product,ProductIntelligence).join(ProductIntelligence,ProductIntelligence.product_id==Product.id)
  if role:query=query.filter(ProductIntelligence.culinary_role==role.strip().lower())
  if family:query=query.filter(ProductIntelligence.dish_families_json.ilike(f'%"{family.strip().lower()}"%'))
  if complete_meals is not None:query=query.filter(ProductIntelligence.is_complete_meal==complete_meals)
  rows=query.order_by(ProductIntelligence.confidence.desc(),Product.price.asc()).limit(max(1,min(limit,100))).all()
  items=[]
  for product,profile in rows:
   item=product_dict(product)
   item['intelligence']={'product_type':profile.product_type,'culinary_role':profile.culinary_role,'dish_families':json.loads(profile.dish_families_json or '[]'),'preparation_state':profile.preparation_state,'storage_type':profile.storage_type,'convenience_level':profile.convenience_level,'is_complete_meal':profile.is_complete_meal,'confidence':profile.confidence,'evidence':json.loads(profile.evidence_json or '[]'),'classifier_version':profile.classifier_version}
   items.append(item)
  return {'items':items,'count':len(items),'filters':{'role':role,'family':family,'complete_meals':complete_meals}}
 finally:db.close()
@app.get('/api/catalog/intelligence/status')
def catalog_intelligence_status():
 db=SessionLocal()
 try:
  total=db.query(Product).filter(Product.supermarket=='REWE').count()
  classified=db.query(ProductIntelligence).join(Product,Product.id==ProductIntelligence.product_id).filter(Product.supermarket=='REWE').count()
  meals=db.query(ProductIntelligence).join(Product,Product.id==ProductIntelligence.product_id).filter(Product.supermarket=='REWE',ProductIntelligence.is_complete_meal.is_(True)).count()
  details=db.query(ProductDetails).join(Product,Product.id==ProductDetails.product_id).filter(Product.supermarket=='REWE').count()
  return {'products':total,'classified':classified,'classification_pending':max(0,total-classified),'complete_meal_candidates':meals,'product_details_records':details,'details_scraping_started':False}
 finally:db.close()
@app.get('/api/products/{product_id}/details')
def product_details(product_id:int):
 db=SessionLocal()
 try:
  product=db.get(Product,product_id)
  if not product:raise HTTPException(404,'Product not found')
  details=db.query(ProductDetails).filter_by(product_id=product_id).first()
  if not details:return {'product_id':product_id,'status':'pending','nutrition':None,'ingredients':None,'allergens':None}
  return {'product_id':product_id,'status':details.details_status,'source':details.source,'source_url':details.source_url,'ean':details.ean,'ingredients':details.ingredients_text,'allergens':json.loads(details.allergens_json) if details.allergens_json else None,'traces':json.loads(details.traces_json) if details.traces_json else None,'additives':json.loads(details.additives_json) if details.additives_json else None,'nutrition':{'basis':details.nutrition_basis,'energy_kj':details.energy_kj,'energy_kcal':details.energy_kcal,'fat_g':details.fat_g,'saturated_fat_g':details.saturated_fat_g,'carbohydrates_g':details.carbohydrates_g,'sugars_g':details.sugars_g,'fibre_g':details.fibre_g,'protein_g':details.protein_g,'salt_g':details.salt_g},'preparation':json.loads(details.preparation_json) if details.preparation_json else None,'storage_instructions':details.storage_instructions,'origin':details.origin,'fetched_at':details.fetched_at}
 finally:db.close()

@app.get('/api/products/validate')
def validate_product(product_id:int):
 db=SessionLocal()
 try:
  product=db.get(Product,product_id)
  if not product:raise HTTPException(404,'Product not found')
  return {'valid':True,'product':product_dict(product)}
 finally:db.close()
@app.get('/api/products/{product_id}/alternatives')
def alternatives(product_id:int,needed_qty:float|None=None,unit:str|None=None):
 db=SessionLocal()
 try:
  current=db.get(Product,product_id)
  if not current:raise HTTPException(404,'Product not found')
  query=db.query(Product).filter(Product.id!=product_id).filter(or_(Product.ingredient==current.ingredient,Product.category==current.category));prs=query.limit(100).all()
  requested_unit=unit or current.package_unit
  ingredient=normalize_ingredient(current.ingredient)
  compatible=[]
  for candidate in prs:
   if str(candidate.supermarket or '').strip().lower()!='rewe':
    continue
   if candidate.price is None or candidate.price<=0 or not candidate.package_size or candidate.package_size<=0:
    continue
   if str(candidate.availability or '').strip().lower() in {'unavailable','out_of_stock','not_available','discontinued'}:
    continue
   title=' '.join(str(value or '') for value in (candidate.name_original,candidate.name_normalized,candidate.translated_name))
   match_type=ingredient_product_match_type(ingredient,title)
   if not match_type:
    continue
   if _convert_quantity(1,requested_unit,candidate.package_unit) is None:
    continue
   compatible.append((candidate,match_type))
  def estimate(entry):
   row=entry[0]
   quantity=float(needed_qty) if needed_qty is not None else float(current.package_size or row.package_size or 1)
   converted=_convert_quantity(quantity,requested_unit,row.package_unit)
   if converted is None:
    return float('inf')
   packs=max(1,math.ceil(converted/row.package_size))
   waste=max(0.0,packs*row.package_size-converted)
   return packs*float(row.price)+waste/max(converted,1.0)
  compatible.sort(key=estimate)
  alternatives=[]
  for candidate,match_type in compatible[:20]:
   item=product_dict(candidate);item['ingredient_match_type']=match_type;alternatives.append(item)
  return {'current':product_dict(current),'alternatives':alternatives}
 finally:db.close()
@app.post('/api/products/replace')
def replace_product(payload:ProductOverrideIn):
 ingredient=normalize_ingredient(payload.ingredient);db=SessionLocal()
 try:
  product=db.get(Product,payload.product_id)
  if not product:raise HTTPException(404,'Product not found')
  if str(product.supermarket or '').strip().lower()!='rewe':
   raise HTTPException(422,'Only REWE catalog products can be selected for a REWE ingredient')
  if product.price is None or product.price<=0:
   raise HTTPException(422,'Selected product has no valid price and cannot be used in the shopping basket')
  if str(product.availability or '').strip().lower() in {'unavailable','out_of_stock','not_available','discontinued'}:
   raise HTTPException(422,'Selected product is marked unavailable')
  product_title=' '.join(str(value or '') for value in (product.name_original,product.name_normalized,product.translated_name))
  match_type=ingredient_product_match_type(ingredient,product_title)
  if not match_type:
   raise HTTPException(422,'Selected product is not a compatible exact match or curated culinary substitute')
  row=db.query(ProductOverride).filter_by(ingredient=ingredient).first()
  if row:row.product_id=product.id
  else:db.add(ProductOverride(ingredient=ingredient,product_id=product.id))
  db.commit();return {'ok':True,'product':product_dict(product),'ingredient':ingredient,'match_type':match_type}
 finally:db.close()
@app.delete('/api/products/replace/{ingredient}')
def restore_product(ingredient:str):
 db=SessionLocal()
 try:
  row=db.query(ProductOverride).filter_by(ingredient=normalize_ingredient(ingredient)).first()
  if row:db.delete(row);db.commit()
  return {'ok':True}
 finally:db.close()
@app.get('/api/rewe/status')
def rewe_status():
 db=SessionLocal()
 try:
  last=db.query(CatalogRun).order_by(CatalogRun.id.desc()).first();count=db.query(Product).filter(Product.supermarket=='REWE').count();return {'provider':'REWE','postcode':setting(db,'postcode','13353'),'products':count,'status':last.status if last else 'not-refreshed','last_updated':last.finished_at if last else None,'errors':last.errors if last else 0,'categories_processed':last.categories_processed if last else 0,'categories_successful':last.categories_successful if last else 0,'categories_failed':last.categories_failed if last else 0,'live_data':False,'data_freshness':'catalog_snapshot'}
 finally:db.close()
@app.post('/api/rewe/refresh')
def rewe_refresh():
 db=SessionLocal();postcode=setting(db,'postcode','13353');run=CatalogRun(status='running');db.add(run);db.commit()
 try:
  def upsert(data,current_postcode):
   existing=db.query(Product).filter_by(supermarket='REWE',external_id=data['external_id']).first();now=datetime.utcnow()
   if existing:
    if existing.price!=data.get('price'):existing.last_price=existing.price
    for k,v in data.items():
     if hasattr(existing,k) and not (k in {'image_url','product_url'} and not v):setattr(existing,k,v)
    existing.postcode_context=current_postcode;existing.last_seen_at=now;existing.last_checked_at=now;db.flush();return False
   db.add(Product(supermarket='REWE',postcode_context=current_postcode,**data));db.flush();return True
  report=ReweCatalogScraper().run(upsert,postcode);run.status=report['status'];run.products_seen=report['products_found'];run.errors=len(report['errors']);run.categories_processed=report['categories_processed'];run.categories_successful=report['categories_successful'];run.categories_failed=report['categories_failed'];run.finished_at=datetime.utcnow();db.commit();return {'ok':report['status']!='failed',**report,'message':'Manual public-category refresh. Prices are a catalog snapshot, not real-time checkout data.'}
 except Exception as exc:run.status='failed';run.errors=max(1,run.errors or 0);run.finished_at=datetime.utcnow();db.commit();raise HTTPException(502,f'REWE refresh failed: {str(exc)[:180]}')
 finally:db.close()
@app.get('/api/shopping/state')
def get_shopping_state():
 db=SessionLocal()
 try:return {'items':[{'ingredient':r.ingredient,'state':r.state,'product_id':r.product_id,'purchased_quantity':r.purchased_quantity,'purchased_unit':r.purchased_unit} for r in db.query(ShoppingState).all()]}
 finally:db.close()
@app.put('/api/shopping/state')
def set_shopping_state(payload:ShoppingStateIn):
 if payload.state not in {'needed','partial','purchased','owned'}:raise HTTPException(422,'Unsupported shopping state')
 ingredient=normalize_ingredient(payload.ingredient);db=SessionLocal()
 try:
  row=db.query(ShoppingState).filter_by(ingredient=ingredient).first()
  if not row:row=ShoppingState(ingredient=ingredient);db.add(row)
  row.state=payload.state;row.product_id=payload.product_id;row.purchased_quantity=payload.purchased_quantity if payload.state=='partial' else None;row.purchased_unit=payload.purchased_unit if payload.state=='partial' else None;db.commit();return {'ok':True}
 finally:db.close()
@app.post('/api/shopping/purchase')
def purchase(payload:PurchaseIn):
 if payload.packs<1:raise HTTPException(422,'Packs must be at least 1')
 db=SessionLocal()
 try:
  product=db.get(Product,payload.product_id)
  if not product:raise HTTPException(404,'Product not found')
  ingredient=normalize_ingredient(payload.ingredient or product.ingredient);amount=product.package_size*payload.packs;item=db.query(PantryItem).filter(PantryItem.ingredient.ilike(ingredient)).first()
  if item and item.unit!=product.package_unit:raise HTTPException(409,f'Pantry already tracks {ingredient} in {item.unit}; cannot safely merge {product.package_unit}.')
  if item:item.quantity+=amount;item.confidence='estimated';item.source='purchase'
  else:db.add(PantryItem(ingredient=ingredient,quantity=amount,unit=product.package_unit,confidence='estimated',source='purchase'))
  state=db.query(ShoppingState).filter_by(ingredient=ingredient).first()
  if not state:state=ShoppingState(ingredient=ingredient);db.add(state)
  state.state='purchased';state.product_id=product.id;state.purchased_quantity=amount;state.purchased_unit=product.package_unit;db.commit();return {'ok':True,'ingredient':ingredient,'added':amount,'unit':product.package_unit}
 finally:db.close()
@app.post('/api/brain-dump')
def brain_dump(payload:BrainDumpIn):
 prompt=payload.prompt.strip();text=prompt.lower();mode='random';constraints={'prompt':prompt,'mode':mode,'max_time':None,'max_cost':None,'spicy':None,'effort':None,'occasion':None,'use_pantry':False};cuisine_map={'asian':('asian','asiático','asiatica','asiática'),'mexican':('mexican','mexicano','mexicana'),'italian':('italian','italiano','italiana'),'mediterranean':('mediterranean','mediterráneo','mediterranea','mediterránea'),'german':('german','alemán','alemana'),'latin-american':('latin','latino','latina')}
 if any(x in text for x in ('cheap','budget','barato','barata','económico','economico')):mode='cheap';constraints['max_cost']=5
 if any(x in text for x in ('quick','easy',"don't want to cook",'dont want to cook','rápido','rapido','fácil','facil','no quiero cocinar')):mode='quick';constraints['max_time']=30;constraints['effort']='low'
 if any(x in text for x in ('protein','proteína','proteina')):mode='high-protein'
 if any(x in text for x in ('healthy','saludable')):mode='healthy'
 if any(x in text for x in ('fancy','guests','invitados','elegante')):constraints['occasion']='fancy'
 if any(x in text for x in ('not spicy','no spicy','sin picante','no picante')):constraints['spicy']=False
 if any(x in text for x in ('at home','pantry','en casa','despensa')):constraints['use_pantry']=True
 for cuisine,aliases in cuisine_map.items():
  if any(alias in text for alias in aliases):mode=cuisine;break
 constraints['mode']=mode;return {'mode':mode,'constraints':constraints}
@app.post('/api/shopping')
def shopping(payload:BasketIn,request:Request):
 if payload.mode not in STRATEGIES:raise HTTPException(422,'Unknown shopping strategy')
 db=SessionLocal()
 try:
  selected=[m for m in MEALS if m['id'] in payload.meal_ids]
  selected_ids={m['id'] for m in selected}
  user=getattr(request.state,'bitewise_user',None) or {}
  owner=str(user.get('id') or user.get('email') or 'local')[:160]
  if len(selected_ids)<len(set(payload.meal_ids)):
   history_rows=db.query(RecipeHistory).filter_by(user_id=owner,record_type='recipe').filter(RecipeHistory.status.in_(['saved','cooked'])).all()
   for row in history_rows:
    try:meal=json.loads(row.meal_json)
    except Exception:continue
    if isinstance(meal,dict) and meal.get('id') in payload.meal_ids and meal['id'] not in selected_ids:
     selected.append(meal);selected_ids.add(meal['id'])
  if not selected:raise HTTPException(422,'Select at least one valid saved recipe')
  servings_map={m['id']:max(0.1,float(payload.servings.get(m['id'],2))) for m in selected};requirements=consolidate(selected,servings_map)
  overrides={r.ingredient:r.product_id for r in db.query(ProductOverride).all()};basket=build_basket(requirements,CatalogAdapter(db),payload.mode,payload.owned,overrides=overrides,pantry=pantry_snapshot(db));total=round(sum(x['checkout_cost'] for x in basket),2);consumed_total=round(sum(x['consumed_cost'] for x in basket),2);total_servings=sum(servings_map.values());waste=round(sum(x['waste'] for x in basket),2);return {'requirements':requirements,'basket':basket,'items':basket,'total':total,'checkout_total':total,'consumed_cost':consumed_total,'meals':len(selected),'servings':total_servings,'cost_per_serving':round(total/total_servings,2) if total_servings else 0,'checkout_cost_per_serving':round(total/total_servings,2) if total_servings else 0,'consumed_cost_per_serving':round(consumed_total/total_servings,2) if total_servings else 0,'waste':waste,'strategy':payload.mode,'pantry_savings_items':sum(1 for x in basket if x.get('pantry_used',0)>0)}
 finally:db.close()
def serialize_planned_meal(row):
 meal=meal_by_id(row.meal_id);return {'id':row.id,'plan_id':row.plan_id,'meal_id':row.meal_id,'day_index':row.day_index,'meal_type':row.meal_type,'servings':row.servings,'status':row.status,'meal':meal}
def serialize_plan(db,plan):
 meals=db.query(PlannedMeal).filter(PlannedMeal.plan_id==plan.id).order_by(PlannedMeal.day_index,PlannedMeal.meal_type).all();return {'id':plan.id,'weeks':plan.weeks,'servings':plan.servings,'strategy':plan.strategy,'budget':plan.budget,'start_date':plan.start_date,'status':plan.status,'meals':[serialize_planned_meal(r) for r in meals]}
def ranked_plan_candidates(db,requested_ids=None):
 events=db.query(UserEvent).all();pantry=db.query(PantryItem).all();pool=[m for m in MEALS if not requested_ids or m['id'] in requested_ids];disliked={e.meal_id for e in events if e.action=='dislike'};pool=[m for m in pool if m['id'] not in disliked];return rank_meals(pool,events,pantry,'random')
@app.post('/api/plans')
def create_plan(payload:PlanCreateIn):
 if payload.weeks not in (1,2,4):raise HTTPException(422,'Weeks must be 1, 2, or 4')
 if payload.strategy not in STRATEGIES:raise HTTPException(422,'Unknown shopping strategy')
 if payload.budget is not None and payload.budget<0:raise HTTPException(422,'Budget cannot be negative')
 if payload.servings<1 or payload.servings>12:raise HTTPException(422,'Servings must be between 1 and 12')
 try:start=date.fromisoformat(payload.start_date) if payload.start_date else date.today()
 except ValueError:raise HTTPException(422,'start_date must be YYYY-MM-DD')
 db=SessionLocal()
 try:
  candidates=ranked_plan_candidates(db,payload.meal_ids or None)
  if not candidates:raise HTTPException(422,'No eligible meals available')
  plan=Plan(weeks=payload.weeks,servings=payload.servings,strategy=payload.strategy,budget=payload.budget,start_date=start.isoformat());db.add(plan);db.flush()
  for day_index in range(payload.weeks*7):
   meal=candidates[day_index%len(candidates)];db.add(PlannedMeal(plan_id=plan.id,meal_id=meal['id'],day_index=day_index,meal_type='dinner',servings=payload.servings))
  db.commit();return serialize_plan(db,plan)
 finally:db.close()
@app.get('/api/plans')
def list_plans():
 db=SessionLocal()
 try:return {'plans':[serialize_plan(db,p) for p in db.query(Plan).order_by(Plan.id.desc()).all()]}
 finally:db.close()
@app.get('/api/plans/{plan_id}')
def get_plan(plan_id:int):
 db=SessionLocal()
 try:
  plan=db.get(Plan,plan_id)
  if not plan:raise HTTPException(404,'Plan not found')
  return serialize_plan(db,plan)
 finally:db.close()
@app.patch('/api/plans/{plan_id}/meals/{planned_meal_id}')
def move_planned_meal(plan_id:int,planned_meal_id:int,payload:PlannedMealPatch):
 db=SessionLocal()
 try:
  row=db.get(PlannedMeal,planned_meal_id);plan=db.get(Plan,plan_id)
  if not plan or not row or row.plan_id!=plan_id:raise HTTPException(404,'Planned meal not found')
  values=payload.model_dump(exclude_none=True)
  consumed=db.query(PantryConsumption).filter_by(planned_meal_id=row.id).first()
  if values and (consumed or row.status in ('cooked','eaten')):
   raise HTTPException(409,'A cooked/eaten meal cannot be edited because its pantry consumption is already recorded')
  if 'day_index' in values and not (0<=values['day_index']<plan.weeks*7):raise HTTPException(422,'day_index outside plan range')
  if 'servings' in values and values['servings']<1:raise HTTPException(422,'servings must be positive')
  for k,v in values.items():setattr(row,k,v)
  db.commit();return serialize_planned_meal(row)
 finally:db.close()
@app.delete('/api/plans/{plan_id}/meals/{planned_meal_id}')
def remove_planned_meal(plan_id:int,planned_meal_id:int):
 db=SessionLocal()
 try:
  row=db.get(PlannedMeal,planned_meal_id)
  if not row or row.plan_id!=plan_id:raise HTTPException(404,'Planned meal not found')
  consumed=db.query(PantryConsumption).filter_by(planned_meal_id=row.id).first()
  if consumed or row.status in ('cooked','eaten'):
   raise HTTPException(409,'A cooked/eaten meal cannot be removed because its pantry consumption is already recorded')
  db.delete(row);db.commit();return {'ok':True}
 finally:db.close()
@app.post('/api/plans/{plan_id}/meals/{planned_meal_id}/swap')
def swap_planned_meal(plan_id:int,planned_meal_id:int,payload:SwapMealIn):
 db=SessionLocal()
 try:
  row=db.get(PlannedMeal,planned_meal_id)
  if not row or row.plan_id!=plan_id:raise HTTPException(404,'Planned meal not found')
  consumed=db.query(PantryConsumption).filter_by(planned_meal_id=row.id).first()
  if consumed or row.status in ('cooked','eaten'):
   raise HTTPException(409,'A cooked/eaten meal cannot be swapped because its pantry consumption is already recorded')
  ids={x.meal_id for x in db.query(PlannedMeal).filter(PlannedMeal.plan_id==plan_id).all()}
  if payload.meal_id:
   replacement=meal_by_id(payload.meal_id)
   if not replacement:raise HTTPException(404,'Replacement meal not found')
  else:
   candidates=ranked_plan_candidates(db);replacement=next((m for m in candidates if m['id']!=row.meal_id and m['id'] not in ids),None) or next((m for m in candidates if m['id']!=row.meal_id),None)
  if not replacement:raise HTTPException(409,'No replacement available')
  row.meal_id=replacement['id'];row.status='planned';db.commit();return serialize_planned_meal(row)
 finally:db.close()
@app.post('/api/plans/{plan_id}/regenerate')
def regenerate_plan(plan_id:int):
 db=SessionLocal()
 try:
  plan=db.get(Plan,plan_id)
  if not plan:raise HTTPException(404,'Plan not found')
  candidates=ranked_plan_candidates(db);rows_to_update=db.query(PlannedMeal).filter(PlannedMeal.plan_id==plan_id,PlannedMeal.status=='planned').order_by(PlannedMeal.day_index).all()
  if rows_to_update and not candidates:raise HTTPException(409,'No eligible meals available to regenerate this plan')
  for i,row in enumerate(rows_to_update):row.meal_id=candidates[i%len(candidates)]['id']
  db.commit();return serialize_plan(db,plan)
 finally:db.close()
@app.post('/api/plans/{plan_id}/meals/{planned_meal_id}/status')
def planned_meal_status(plan_id:int,planned_meal_id:int,payload:PlannedMealStatusIn):
 if payload.status not in {'planned','cooked','eaten','skipped'}:raise HTTPException(422,'Unsupported meal status')
 db=SessionLocal()
 try:
  row=db.get(PlannedMeal,planned_meal_id)
  if not row or row.plan_id!=plan_id:raise HTTPException(404,'Planned meal not found')
  previous=row.status;row.status=payload.status;consumed=[];already_consumed=False
  if payload.status in ('cooked','eaten'):
   ledger=db.query(PantryConsumption).filter_by(planned_meal_id=row.id).first()
   if ledger:
    already_consumed=True
   else:
    meal=meal_by_id(row.meal_id)
    if meal:
     consumed=consume_meal_from_pantry(db,meal,row.servings)
     db.add(PantryConsumption(planned_meal_id=row.id,meal_id=row.meal_id,consumed_json=json.dumps(consumed,ensure_ascii=False)))
     db.add(UserEvent(meal_id=row.meal_id,action=payload.status))
  db.commit();return {**serialize_planned_meal(row),'consumed':consumed,'already_consumed':already_consumed}
 finally:db.close()
@app.get('/api/today')
def today(plan_id:int|None=Query(default=None)):
 db=SessionLocal()
 try:
  plan=db.get(Plan,plan_id) if plan_id else db.query(Plan).filter(Plan.status=='active').order_by(Plan.id.desc()).first()
  if not plan:return {'plan':None,'date':date.today().isoformat(),'meals':[]}
  start=date.fromisoformat(plan.start_date);day_index=(date.today()-start).days
  if day_index<0 or day_index>=plan.weeks*7:return {'plan':serialize_plan(db,plan),'date':date.today().isoformat(),'day_index':day_index,'meals':[]}
  day_meals=db.query(PlannedMeal).filter(PlannedMeal.plan_id==plan.id,PlannedMeal.day_index==day_index).all();pantry=pantry_snapshot(db);serialized=[]
  for row in day_meals:
   item=serialize_planned_meal(row);ingredients=item['meal']['ingredients'] if item['meal'] else [];covered=0
   for name,amount,unit in ingredients:
    stock=pantry.get(str(name).lower())
    if not stock:
     continue
    available=_convert_quantity(stock.get('quantity',0),stock.get('unit'),unit)
    required=float(amount)*row.servings/2
    if available is not None and available+1e-9>=required:
     covered+=1
   item['pantry_covered_ingredients']=covered;item['pantry_total_ingredients']=len(ingredients);item['pantry_coverage_pct']=round(covered/len(ingredients)*100) if ingredients else 0;serialized.append(item)
  return {'plan':{'id':plan.id,'strategy':plan.strategy,'budget':plan.budget},'date':date.today().isoformat(),'day_index':day_index,'meals':serialized}
 finally:db.close()
@app.post('/api/ai/meals')
def ai_meals(payload:BrainDumpIn,request:Request):
 prompt=payload.prompt.strip()
 if not prompt:raise HTTPException(422,'Describe what you feel like eating first')
 try:
  # Gemini creates the meal ideas; the local engine then personalizes their order.
  generated=GeminiService().generate_meals(prompt)
  intent=brain_dump(payload)
  user=getattr(request.state,'bitewise_user',None) or {}
  owner=str(user.get('id') or user.get('email') or 'local')[:160]
  db=SessionLocal()
  try:
   # Persist concepts so likes/skips survive restarts and become future learning signals.
   for meal in generated:
    key=str(meal.get('id') or '').strip()[:180]
    if not key:continue
    row=db.query(RecipeHistory).filter_by(user_id=owner,record_key=key).first()
    record_type='concept' if meal.get('is_concept') else 'recipe'
    if row is None:
     row=RecipeHistory(id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'bitewise:{owner}:{key}')),user_id=owner,record_key=key,record_type=record_type,status='discovered',name=str(meal.get('name') or 'Meal')[:180],prompt=prompt[:4000],meal_json=json.dumps(meal,ensure_ascii=False))
     db.add(row)
    else:
     row.record_type=record_type
     row.name=str(meal.get('name') or row.name)[:180]
     row.prompt=prompt[:4000]
     row.meal_json=json.dumps(meal,ensure_ascii=False)
     row.updated_at=datetime.utcnow()
   db.commit()
   events=db.query(UserEvent).all()
   pantry=db.query(PantryItem).filter(PantryItem.quantity>0).all()
   history_rows=db.query(RecipeHistory).filter_by(user_id=owner).all()
   preference_pool=list(MEALS)
   for row in history_rows:
    try:
     stored=json.loads(row.meal_json)
     if isinstance(stored,dict) and stored.get('id'):preference_pool.append(stored)
    except Exception:continue
   preference_pool.extend(generated)
   profile=build_preference_profile(events,preference_pool)
   ranked=rank_meals(generated,events,pantry,intent.get('mode'),profile=profile)
   for meal in ranked:
    meal['recommendation_score']=round(score_meal(meal,events,pantry,intent.get('mode'),profile),3)
    reasons=[]
    cuisine=str(meal.get('cuisine') or '').lower()
    if profile['cuisines'].get(cuisine,0)>0:reasons.append('Matches cuisines you have liked before')
    liked_tags=[str(tag).lower() for tag in meal.get('tags') or [] if profile['tags'].get(str(tag).lower(),0)>0]
    if liked_tags:reasons.append('Fits food styles you tend to enjoy: '+', '.join(liked_tags[:2]))
    if intent.get('mode')=='quick' and (meal.get('time') or 999)<=30:reasons.append('Fits your quick-meal request')
    if not reasons:reasons.append('Selected for fit with your request and variety')
    meal['recommendation_reasons']=reasons
   return {'meals':ranked,'intent':intent.get('constraints',{}),'ranking':'personalized_hybrid','ideas_generated_by':'gemini'}
  finally:db.close()
 except Exception as exc:raise HTTPException(502,f'Gemini generation failed: {str(exc)[:300]}')
