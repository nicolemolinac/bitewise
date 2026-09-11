import math
from collections import defaultdict

def consolidate(meals, servings_map):
    grouped=defaultdict(lambda:{"quantity":0,"unit":"","source_meals":[]})
    for meal in meals:
        factor=servings_map.get(meal["id"],1)/2
        for name,qty,unit in meal["ingredients"]:
            key=name.lower()
            grouped[key]["quantity"] += qty*factor
            grouped[key]["unit"] = unit
            grouped[key]["source_meals"].append(meal["name"])
    return [{"ingredient":k,"quantity":round(v["quantity"],1),"unit":v["unit"],"source_meals":list(dict.fromkeys(v["source_meals"]))} for k,v in grouped.items()]

def choose_product(req, candidates, mode="cheapest"):
    if not candidates: return None
    scored=[]
    for p in candidates:
        if p.get("price") is None: continue
        packs=max(1,math.ceil(req["quantity"]/p["pack_qty"]))
        purchased=packs*p["pack_qty"]
        waste=max(0,purchased-req["quantity"])
        total=packs*p["price"]
        waste_ratio=waste/max(req["quantity"],1)
        score=total if mode=="cheapest" else total + waste_ratio*0.7*p["price"]
        scored.append((score,packs,total,waste,p))
    return min(scored,key=lambda x:x[0]) if scored else None

def build_basket(requirements, adapter, mode="cheapest", owned=None):
    owned={x.lower() for x in (owned or [])}
    rows=[]
    for req in requirements:
        if req["ingredient"].lower() in owned: continue
        cands=adapter.search(req["ingredient"])
        choice=choose_product(req,cands,mode)
        if not choice: rows.append({**req,"product":None,"packs":0,"total":0,"waste":0}); continue
        score,packs,total,waste,p=choice
        rows.append({**req,"product":p,"packs":packs,"total":round(total,2),"waste":round(waste,1)})
    return rows
