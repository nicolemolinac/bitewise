import math
from collections import defaultdict
STRATEGIES={"maximum-savings","best-value","plan-efficiency","premium","cheapest","less-waste"}
def consolidate(meals, servings_map):
 g=defaultdict(lambda:{"quantity":0,"unit":"","source_meals":[]})
 for m in meals:
  for n,q,u in m["ingredients"]:
   x=g[n.lower()];x["quantity"]+=q*servings_map.get(m["id"],2)/2;x["unit"]=u;x["source_meals"].append(m["name"])
 return [{"ingredient":k,"quantity":round(v["quantity"],1),"unit":v["unit"],"source_meals":list(dict.fromkeys(v["source_meals"]))} for k,v in g.items()]
def build_basket(requirements,adapter,mode="best-value",owned=None):
 owned={x.lower() for x in (owned or [])};out=[]
 for r in requirements:
  if r["ingredient"].lower() in owned:continue
  a=[]
  for p in adapter.search(r["ingredient"]):
   if p.get("price") is None:continue
   packs=max(1,math.ceil(r["quantity"]/p["pack_qty"]));w=max(0,packs*p["pack_qty"]-r["quantity"]);total=packs*p["price"];score=total if mode in ("cheapest","maximum-savings") else total+w/max(r["quantity"],1)*p["price"]
   a.append((score,packs,total,w,p))
  if not a:out.append({**r,"product":None,"packs":0,"total":0,"waste":0,"badge":"Availability unknown","why":"No catalog match yet."});continue
  _,packs,total,w,p=min(a);badge="Cheapest" if mode in ("cheapest","maximum-savings") else ("Premium" if mode=="premium" else ("Best for Plan" if mode=="plan-efficiency" else "Best Value"))
  out.append({**r,"product":p,"packs":packs,"total":round(total,2),"waste":round(w,1),"badge":badge,"why":f"Used in {len(r['source_meals'])} meal(s)."})
 return out
