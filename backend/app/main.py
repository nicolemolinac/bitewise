import os, uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from .database import SessionLocal, UserEvent, PantryItem
from .recipes.seed import MEALS
from .recommendations.engine import score_meal
from .shopping.optimizer import consolidate, build_basket
from .rewe.adapter import ReweAdapter
from .ai.gemini import GeminiService

load_dotenv(Path(__file__).resolve().parents[1]/".env")
app=FastAPI(title="Bitewise API")
origins=os.getenv("CORS_ORIGINS","http://localhost:5173").split(",")
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

def events():
    db=SessionLocal(); rows=db.query(UserEvent).all(); db.close(); return rows

def pantry():
    db=SessionLocal(); rows=db.query(PantryItem).all(); db.close(); return rows

class EventIn(BaseModel): meal_id:str; action:str
class PantryIn(BaseModel): ingredient:str; quantity:float=1; unit:str="unit"
class PlanIn(BaseModel): meal_ids:list[str]; servings:dict[str,int]={}
class BasketIn(BaseModel): meal_ids:list[str]; servings:dict[str,int]={}; owned:list[str]=[]; mode:str="cheapest"

@app.get("/api/health")
def health(): return {"ok":True}

@app.get("/api/meals")
def get_meals(mode:str="random"):
    ev=events(); pan=pantry()
    meals=sorted(MEALS,key=lambda m:score_meal(m,ev,pan,mode),reverse=True)
    # strong variety: rotate top results by cuisine and remove meals recently cooked/seen heavily
    seen={e.meal_id for e in ev if e.action in ("like","skip","cooked")}
    fresh=[m for m in meals if m["id"] not in seen]
    return {"meals":(fresh+meals)[:12],"mode":mode}

@app.post("/api/events")
def add_event(payload:EventIn):
    if payload.meal_id not in {m["id"] for m in MEALS}: raise HTTPException(404,"Meal not found")
    db=SessionLocal(); db.add(UserEvent(meal_id=payload.meal_id,action=payload.action)); db.commit(); db.close(); return {"ok":True}

@app.get("/api/plan")
def get_plan():
    db=SessionLocal(); likes=[e.meal_id for e in db.query(UserEvent).filter(UserEvent.action=="like").all()]; db.close()
    ids=list(dict.fromkeys(likes))[-7:]
    return {"meal_ids":ids}

@app.post("/api/plan")
def plan(payload:PlanIn):
    ids=payload.meal_ids[:14]; selected=[m for m in MEALS if m["id"] in ids]
    for m in selected:
        db=SessionLocal(); db.add(UserEvent(meal_id=m["id"],action="cooked")); db.commit(); db.close()
    return {"ok":True,"meal_ids":ids,"meals":selected}

@app.get("/api/pantry")
def get_pantry(): return [{"id":p.id,"ingredient":p.ingredient,"quantity":p.quantity,"unit":p.unit} for p in pantry()]

@app.post("/api/pantry")
def add_pantry(payload:PantryIn):
    db=SessionLocal(); old=db.query(PantryItem).filter(PantryItem.ingredient.ilike(payload.ingredient)).first()
    if old: old.quantity=payload.quantity; old.unit=payload.unit
    else: db.add(PantryItem(**payload.model_dump()))
    db.commit(); db.close(); return {"ok":True}

@app.delete("/api/pantry/{item_id}")
def del_pantry(item_id:int):
    db=SessionLocal(); row=db.get(PantryItem,item_id)
    if row: db.delete(row); db.commit()
    db.close(); return {"ok":True}

@app.post("/api/shopping")
def shopping(payload:BasketIn):
    selected=[m for m in MEALS if m["id"] in payload.meal_ids]
    reqs=consolidate(selected,payload.servings)
    adapter=ReweAdapter(os.getenv("REWE_LIVE_ENABLED","false").lower()=="true")
    basket=build_basket(reqs,adapter,payload.mode,payload.owned)
    total=round(sum(x["total"] for x in basket),2)
    servings=sum(payload.servings.get(m["id"],2) for m in selected)
    return {"requirements":reqs,"basket":basket,"total":total,"meals":len(selected),"servings":servings,"cost_per_serving":round(total/servings,2) if servings else 0,"waste":round(sum(x["waste"] for x in basket),1)}

@app.post("/api/ai/meals")
def ai_meals(prompt:str):
    data=GeminiService().generate_meals(prompt)
    return {"meals":data or []}
