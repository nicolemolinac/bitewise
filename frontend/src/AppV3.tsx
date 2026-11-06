import React, { useEffect, useMemo, useState } from 'react';
import { parseApiResponse } from './apiResponse.js';
import { isCanonicalReweProductUrl } from './reweUrl.js';
import {
  AirVent, CalendarDays, Check, ChefHat, ExternalLink, Flame, Home,
  Microwave, PackageCheck, Settings, ShoppingBasket,
  UtensilsCrossed, X,
} from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const K = 'bitewise.v3.';

type MealType = 'breakfast' | 'lunch' | 'dinner' | 'dessert' | 'snack';
type Tab = 'discover'|'picks'|'history'|'plan'|'today'|'basket'|'extras'|'pantry'|'settings';
type Strategy = 'maximum-savings'|'best-value'|'plan-efficiency'|'premium';
type CalendarView = 'week'|'month'|'year';
type Meal = {
  id:string; name:string; description:string; time:number; difficulty:string; cost:number; cuisine:string;
  tags:string[]; ingredients:[string,number,string][]; image:string; calories?:number; meal_type?:MealType;
  steps?:{text:string;minutes?:number|null}[]; is_concept?:boolean; discovery_prompt?:string;
  image_page?:string; photographer?:string;
  costing?:{strategy:string;matched_ingredients:number;substituted_ingredients?:number;covered_ingredients?:number;unmatched_ingredients?:number;total_ingredients:number;catalog_ready:boolean;checkout_total:number|null;consumed_cost:number|null;cost_per_serving?:number|null;servings?:number;people?:number;cost_scope?:string;shopping_ready?:boolean;catalog_coverage?:number;currency:string};
  product_matches?:any[];
};
type Product = { id:number|null; name_original:string; brand?:string|null; package_size:number; package_unit:string; price:number|null; price_per_unit?:number|null; product_url?:string|null; image_url?:string|null; ingredient?:string; };
type BasketItem = { ingredient:string; quantity:number; needed_quantity?:number; unit:string; product:Product|null; packs:number; total:number; pantry_used?:number; badge?:string; match_status?:string; availability_status?:string; availability_note?:string; };
type Profile = { heightCm:number; weightKg:number; portionPreference:number };
type DayContext = { people:number; occasion:string };
type ExtraItem = { id:string; kind:'beverage'|'non-food'|'freezer-meal'; label:string; product:Product|null; dailyUse:number; weeklyQuantity?:number; onHand:number; };
type Slot = { type:MealType; meal:Meal|null };

const mealTypes:{id:MealType;label:string;emoji:string}[]=[
  {id:'breakfast',label:'Breakfast',emoji:'☕'}, {id:'lunch',label:'Lunch',emoji:'🥗'},
  {id:'dinner',label:'Dinner',emoji:'🍝'}, {id:'dessert',label:'Dessert',emoji:'🍰'}, {id:'snack',label:'Snacks',emoji:'🍓'},
];
const cuisines=['all','quick','cheap','healthy','high-protein','asian','mexican','italian','mediterranean','latin-american','german'];
const strategies:{id:Strategy;label:string;icon:string}[]=[
  {id:'maximum-savings',label:'Maximum savings',icon:'💰'}, {id:'best-value',label:'Best value',icon:'⭐'},
  {id:'plan-efficiency',label:'Plan efficiency',icon:'🔥'}, {id:'premium',label:'Premium',icon:'✨'},
];
const applianceOptions=[
  {id:'air fryer',label:'Air fryer',icon:<AirVent size={15}/>}, {id:'microwave',label:'Microwave',icon:<Microwave size={15}/>},
  {id:'oven',label:'Oven',icon:<Flame size={15}/>}, {id:'stovetop',label:'Stovetop',icon:<ChefHat size={15}/>},
];
const dayNames=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

async function api(path:string,options?:RequestInit){
  const r=await fetch(API+path,{headers:{'Content-Type':'application/json',...(options?.headers||{})},...options});
  return parseApiResponse(r);
}
function read<T>(key:string,fallback:T):T{try{const v=localStorage.getItem(K+key);return v?JSON.parse(v):fallback}catch{return fallback}}
function save(key:string,value:unknown){try{localStorage.setItem(K+key,JSON.stringify(value))}catch{}}
function money(v?:number|null){return `€${Number(v||0).toFixed(2)}`}
function cx(...v:(string|false|null|undefined)[]){return v.filter(Boolean).join(' ')}
function clamp(v:number,min:number,max:number){return Math.min(max,Math.max(min,v))}
function mealTypeOf(m:Meal):MealType{
  if(m.meal_type)return m.meal_type;
  const s=`${m.name} ${m.description} ${(m.tags||[]).join(' ')}`.toLowerCase();
  if(/breakfast|oat|pancake|toast|granola|omelette|yogurt|egg/.test(s))return 'breakfast';
  if(/dessert|cake|cookie|brownie|tiramisu|pudding|sweet/.test(s))return 'dessert';
  if(/snack|smoothie|bite|bar/.test(s))return 'snack';
  if(/lunch|salad|sandwich|wrap/.test(s))return 'lunch';
  return 'dinner';
}

function buildSmartWeek(meals:Meal[]):Record<string,string>{
  const assignments:Record<string,string>={};
  const slotTypes:MealType[]=['breakfast','lunch','dinner'];
  const usage=new Map<string,number>();
  const lastByType=new Map<MealType,string>();
  for(let day=0;day<7;day++){
    for(const type of slotTypes){
      const candidates=meals.filter(m=>mealTypeOf(m)===type);
      if(!candidates.length)continue;
      const ranked=[...candidates].sort((a,b)=>{
        const score=(m:Meal)=>{
          const used=usage.get(m.id)||0;
          const repeatedYesterday=lastByType.get(type)===m.id?1000:0;
          const time=Math.max(0,Number(m.time)||0);
          const cost=Math.max(0,Number(m.cost)||0);
          return used*100+repeatedYesterday+time*0.7+cost*3;
        };
        return score(a)-score(b);
      });
      const chosen=ranked[0];
      assignments[`${day}:${type}`]=chosen.id;
      usage.set(chosen.id,(usage.get(chosen.id)||0)+1);
      lastByType.set(type,chosen.id);
    }
  }
  return assignments;
}
function mondayOfCurrentWeek(){
  const date=new Date();
  date.setHours(0,0,0,0);
  date.setDate(date.getDate()-((date.getDay()+6)%7));
  return date;
}
function dateLabel(date:Date){
  return date.toLocaleDateString(undefined,{day:'numeric',month:'short'});
}
function dateKey(date:Date){return date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0')}
function addMonths(date:Date,amount:number){return new Date(date.getFullYear(),date.getMonth()+amount,1)}
function readCalendarAssignments(){
  try{const raw=localStorage.getItem(K+'calendarAssignments');if(raw!==null)return JSON.parse(raw)}catch{}
  const legacy=readCurrentWeekPlan();
  const migrated:Record<string,string>={};
  const monday=mondayOfCurrentWeek();
  Object.entries(legacy).forEach(([key,id])=>{const match=key.match(/^(\d+):(breakfast|lunch|dinner)$/);if(match){const day=new Date(monday);day.setDate(day.getDate()+Number(match[1]));migrated[dateKey(day)+':'+match[2]]=id}});
  if(Object.keys(migrated).length)save('calendarAssignments',migrated);
  try{localStorage.removeItem(K+planStorageKey());localStorage.removeItem(K+'planAssignments')}catch{}
  return migrated;
}
function planStorageKey(){
  const date=mondayOfCurrentWeek();
  const key=`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  return `planAssignments:${key}`;
}
function readCurrentWeekPlan(){
  const current=read<Record<string,string>>(planStorageKey(),{});
  if(Object.keys(current).length)return current;
  // One-time migration of the original unscoped calendar state.
  const legacy=read<Record<string,string>>('planAssignments',{});
  if(Object.keys(legacy).length){
    save(planStorageKey(),legacy);
    try{localStorage.removeItem(K+'planAssignments')}catch{}
  }
  return legacy;
}
function caloriesOf(m:Meal){
  if(m.calories)return m.calories;
  const protein=(m.ingredients||[]).some(x=>/chicken|beef|salmon|fish|pancetta/.test(x[0]))?170:0;
  const carb=(m.ingredients||[]).some(x=>/pasta|rice|potato|bread|tortilla/.test(x[0]))?230:100;
  return Math.min(950,Math.round(180+protein+carb+(m.cost||2)*25));
}
function fallbackSteps(m:Meal,appliances:string[]){
  const names=(m.ingredients||[]).map(x=>x[0]);
  const out:{text:string;minutes?:number}[]=[];
  if(names.some(x=>x.includes('pasta')))out.push({text:'Boil water, add pasta and cook until tender.',minutes:10});
  if(names.some(x=>x==='rice'))out.push({text:'Cook rice with water until fluffy.',minutes:12});
  if(appliances.includes('air fryer')&&names.some(x=>/chicken|potato|salmon|vegetable/.test(x)))out.push({text:'Air fry the main protein/vegetables at 190°C. Shake once.',minutes:12});
  else if(appliances.includes('oven')&&names.some(x=>/chicken|potato|salmon|vegetable/.test(x)))out.push({text:'Put everything on one tray and roast at 210°C.',minutes:20});
  else out.push({text:'Cook the main ingredients in one pan until done.',minutes:10});
  out.push({text:'Add sauce or seasoning and combine.',minutes:3});
  out.push({text:'Plate it. Done.',minutes:1});
  return out;
}
function portionFactor(profile:Profile){const body=Math.sqrt((Math.max(profile.weightKg,35)/70)*(Math.max(profile.heightCm,140)/170));return clamp(body*profile.portionPreference,0.65,1.4)}
function exactRewe(url?:string|null){return isCanonicalReweProductUrl(url)}

export default function AppV3(){
  const [tab,setTab]=useState<Tab>(()=>read('tab','discover'));
  const [meals,setMeals]=useState<Meal[]>([]);
  const [history,setHistory]=useState<any[]>([]);
  const [liked,setLiked]=useState<Meal[]>(()=>read('liked',[]));
  const [skipped,setSkipped]=useState<string[]>(()=>read('skipped',[]));
  const [mealType,setMealType]=useState<MealType>(()=>read('mealType','dinner'));
  const [filter,setFilter]=useState(()=>read('filter','all'));
  const [brain,setBrain]=useState(()=>read('brain',''));
  const DEFAULT_APPLIANCES=['air fryer','microwave','stovetop'];
  const [appliances,setAppliances]=useState<string[]>(()=>{
    const saved=read<string[]>('appliances',DEFAULT_APPLIANCES);
    // Replace the old untouched default with the user's new air-fryer/microwave-first setup.
    return JSON.stringify(saved)===JSON.stringify(['oven','stovetop','microwave'])?DEFAULT_APPLIANCES:saved;
  });
  const [profile,setProfile]=useState<Profile>(()=>read('profile',{heightCm:170,weightKg:70,portionPreference:1}));
  const [dayContexts,setDayContexts]=useState<DayContext[]>(()=>read('dayContexts',Array.from({length:7},()=>({people:1,occasion:''}))));
  const [calendarAssignments,setCalendarAssignments]=useState<Record<string,string>>(()=>readCalendarAssignments());
  const [calendarView,setCalendarView]=useState<CalendarView>(()=>read('calendarView','week'));
  const [calendarCursor,setCalendarCursor]=useState<string>(()=>read('calendarCursor',dateKey(new Date())));
  const [extras,setExtras]=useState<ExtraItem[]>(()=>read('extras',[]));
  const [extraKind,setExtraKind]=useState<'beverage'|'non-food'|'freezer-meal'>('beverage');
  const [extraQuery,setExtraQuery]=useState('');
  const [extraResults,setExtraResults]=useState<Product[]>([]);
  const [detail,setDetail]=useState<Meal|null>(null);
  const [loading,setLoading]=useState(false);
  const [cartAdding,setCartAdding]=useState(false);
  const [cartReport,setCartReport]=useState<any>(null);
  const [error,setError]=useState('');
  const [basket,setBasket]=useState<BasketItem[]>(()=>read('basket',[]));
  const [summary,setSummary]=useState<any>(()=>read('summary',null));
  const [basketUsesUnplannedPicks,setBasketUsesUnplannedPicks]=useState(()=>read('basketUsesUnplannedPicks',false));
  const [strategy,setStrategy]=useState<Strategy>(()=>read('strategy','best-value'));
  const [owned,setOwned]=useState<string[]>(()=>read('owned',[]));
  const [pantry,setPantry]=useState<any[]>([]);
  const [pantryDraftId,setPantryDraftId]=useState<number|null>(null);
  const [pantryIngredient,setPantryIngredient]=useState('');
  const [pantryQuantity,setPantryQuantity]=useState('1');
  const [pantryUnit,setPantryUnit]=useState('g');
  const [pantryExpiry,setPantryExpiry]=useState('');
  const [pantrySaving,setPantrySaving]=useState(false);
  const [pantryError,setPantryError]=useState('');
  const [altItem,setAltItem]=useState<BasketItem|null>(null);
  const [alternatives,setAlternatives]=useState<Product[]>([]);
  const [altError,setAltError]=useState('');

  useEffect(()=>{boot()},[]);
  useEffect(()=>save('tab',tab),[tab]);useEffect(()=>save('liked',liked),[liked]);useEffect(()=>save('skipped',skipped),[skipped]);
  useEffect(()=>save('mealType',mealType),[mealType]);useEffect(()=>save('filter',filter),[filter]);useEffect(()=>save('brain',brain),[brain]);
  useEffect(()=>save('appliances',appliances),[appliances]);useEffect(()=>save('profile',profile),[profile]);useEffect(()=>save('dayContexts',dayContexts),[dayContexts]);
  useEffect(()=>save('calendarAssignments',calendarAssignments),[calendarAssignments]);useEffect(()=>save('calendarView',calendarView),[calendarView]);useEffect(()=>save('calendarCursor',calendarCursor),[calendarCursor]);useEffect(()=>save('extras',extras),[extras]);useEffect(()=>save('basket',basket),[basket]);
  useEffect(()=>save('summary',summary),[summary]);useEffect(()=>save('basketUsesUnplannedPicks',basketUsesUnplannedPicks),[basketUsesUnplannedPicks]);useEffect(()=>save('strategy',strategy),[strategy]);useEffect(()=>save('owned',owned),[owned]);

  async function boot(){
    try{
      const [m,p,s,ss,h]=await Promise.all([api('/meals?mode=random'),api('/pantry'),api('/settings'),api('/shopping/state'),api('/recipe-history')]);
      setMeals(m.meals||[]);setPantry(p||[]);if(s.shopping_strategy)setStrategy(s.shopping_strategy);
      const records=h.records||[];setHistory(records);
      const recipeRows=records.filter((x:any)=>x.record_type==='recipe'&&['saved','cooked'].includes(x.status)&&x.meal);
      const savedRecipes=recipeRows.map((row:any)=>{
        const meal={...row.meal};
        const keyId=String(row.record_key||'').replace(/^recipe:/,'');
        // Only AI-expanded recipes need concept-based namespacing. Seed recipes
        // saved as Picks must keep their original IDs so calendar assignments survive.
        const conceptId=String(meal.source_concept_id||(keyId&&keyId!==String(meal.id||'')?keyId:''));
        if(conceptId&&!meal.source_concept_id){
          meal.source_concept_id=conceptId;
          if(!String(meal.id||'').endsWith('-'+conceptId))meal.id=(meal.id||'recipe')+'-'+conceptId;
        }
        return meal as Meal;
      });
      // The database is the source of truth for Picks, including an empty list.
      setLiked(savedRecipes);
      const migrated=recipeRows.filter((row:any)=>!row.meal.source_concept_id);
      if(migrated.length){
        const bySource=new Map(savedRecipes.map(meal=>[(meal as any).source_concept_id,meal]));
        const updates=migrated.map((row:any)=>{
          const conceptId=String(row.record_key||'').replace(/^recipe:/,'');
          return {record_key:row.record_key,record_type:'recipe',status:row.status,prompt:row.prompt||'',meal:bySource.get(conceptId)};
        }).filter((row:any)=>row.meal);
        void api('/recipe-history',{method:'POST',body:JSON.stringify({records:updates})}).then(()=>{
          setHistory(current=>current.map(row=>{
            const conceptId=String(row.record_key||'').replace(/^recipe:/,'');
            const updated=bySource.get(conceptId);
            return row.record_type==='recipe'&&updated?{...row,meal:updated}:row;
          }));
        }).catch(()=>{});
      }
      const savedConcepts=records
        .filter((x:any)=>x.record_type==='concept'&&!['expanded','disliked','removed','skipped'].includes(x.status))
        .slice(0,24).map((x:any)=>x.meal).filter(Boolean);
      if(savedConcepts.length)void attachFreePhotos(savedConcepts);
      const apiOwned=(ss.items||[]).filter((x:any)=>x.state==='owned').map((x:any)=>x.ingredient);if(apiOwned.length)setOwned(apiOwned);
    }catch(e:any){setError(e.message)}
  }

  const discoverPool=useMemo(()=>{
    const concepts=history
      .filter((row:any)=>row.record_type==='concept'&&!['expanded','disliked','removed','skipped'].includes(row.status))
      .map((row:any)=>row.meal)
      .filter(Boolean) as Meal[];
    const byId=new Map<string,Meal>();
    [...concepts,...meals].forEach(meal=>{if(meal?.id)byId.set(meal.id,meal)});
    return [...byId.values()];
  },[history,meals]);

  const visible=useMemo(()=>{
    let list=discoverPool.filter(m=>!liked.some(x=>x.id===m.id)&&!skipped.includes(m.id)).filter(m=>mealTypeOf(m)===mealType);
    if(filter==='quick')list=list.filter(m=>m.time<=30||m.tags?.some(t=>/quick/i.test(t)));
    else if(filter==='cheap')list=list.filter(m=>m.cost<=3||m.tags?.some(t=>/cheap/i.test(t)));
    else if(filter==='healthy')list=list.filter(m=>m.tags?.some(t=>/healthy/i.test(t)));
    else if(filter==='high-protein')list=list.filter(m=>m.tags?.some(t=>/protein/i.test(t)));
    else if(filter!=='all')list=list.filter(m=>m.cuisine?.toLowerCase().replace(/\s+/g,'-').includes(filter));
    return list;
  },[discoverPool,liked,skipped,mealType,filter]);

  const weeklyPlan=useMemo(()=>Array.from({length:7},(_,day)=>{const date=mondayOfCurrentWeek();date.setDate(date.getDate()+day);return {day,date,slots:(['breakfast','lunch','dinner'] as MealType[]).map(type=>({type,meal:liked.find(m=>m.id===calendarAssignments[dateKey(date)+':'+type])||null} as Slot)).filter(x=>x.meal)}}),[liked,calendarAssignments]);
  const factor=portionFactor(profile);const todayIndex=(new Date().getDay()+6)%7;const todaySlots=weeklyPlan[todayIndex]?.slots||[];
  const weeklyStats=useMemo(()=>{let cost=0,calories=0,mealCount=0;weeklyPlan.forEach((d,idx)=>d.slots.forEach(s=>{if(!s.meal)return;const portions=dayContexts[idx]?.people||1;cost+=s.meal.cost*factor*portions;calories+=caloriesOf(s.meal)*factor;mealCount++}));return {cost,avgCalories:mealCount?Math.round(calories/7):0,mealCount}},[weeklyPlan,dayContexts,factor]);

  async function attachFreePhotos(fresh:Meal[]){
    try{
      const photos=await api('/meal-photos',{method:'POST',body:JSON.stringify({meals:fresh.map(meal=>({
        name:meal.name,
        description:meal.description||'',
        meal_type:mealTypeOf(meal),
        tags:meal.tags||[],
        ingredients:meal.ingredients||[]
      }))})});
      const enriched=fresh.map((meal,index)=>{
        const photo=photos?.photos?.[index]||{};
        return {...meal,image:photo.image||'',image_page:photo.image_page||'',photographer:photo.photographer||''};
      });
      setMeals(current=>{
        const byId=new Map(current.map(meal=>[meal.id,meal]));
        enriched.forEach(meal=>byId.set(meal.id,meal));
        return [...byId.values()];
      });
      setHistory(current=>current.map(row=>{
        const updated=enriched.find(meal=>meal.id===row.record_key);
        return updated?{...row,meal:updated}:row;
      }));
    }catch{
      setMeals(current=>{
        const byId=new Map(current.map(meal=>[meal.id,meal]));
        fresh.forEach(meal=>{if(!byId.has(meal.id))byId.set(meal.id,{...meal,image:''})});
        return [...byId.values()];
      });
    }
  }

  async function generateAI(prompt:string){
    setLoading(true);setError('');
    try{
      const p=prompt.toLowerCase();
      const promptType:MealType|undefined=/\b(breakfast|desayuno)\b/.test(p)?'breakfast':/\b(lunch|almuerzo)\b/.test(p)?'lunch':/\b(dinner|cena)\b/.test(p)?'dinner':/\b(dessert|postre)\b/.test(p)?'dessert':/\b(snack|merienda)\b/.test(p)?'snack':undefined;
      const requestedType=promptType||mealType;setMealType(requestedType);
      const full=`${prompt}. Meal type: ${requestedType}. Available appliances: ${appliances.join(', ')||'basic kitchen'}. User portion factor is ${factor.toFixed(2)}. Prefer the easiest method and minimal cleanup.`;
      const d=await api('/ai/meals',{method:'POST',body:JSON.stringify({prompt:full})});
      const generated:Meal[]=d.meals||[];
      if(!generated.length)throw new Error('No meal ideas were generated. Check GEMINI_API_KEY in backend/.env.');
      const batchId=Date.now();
      const requestedMeals=generated.map((m,i)=>({...m,id:`${m.id}-${batchId}-${i+1}`,meal_type:requestedType,image:'',discovery_prompt:prompt,is_concept:true}));
      const saved=await api('/recipe-history',{method:'POST',body:JSON.stringify({records:requestedMeals.map(meal=>({record_key:meal.id,record_type:'concept',status:'discovered',prompt,meal}))})});
      if(!saved.ok)throw new Error('Bitewise could not save this discovery to your permanent history.');
      setHistory(prev=>[...requestedMeals.map(meal=>({record_key:meal.id,record_type:'concept',status:'discovered',prompt,meal})),...prev]);
      setMeals(current=>{const byId=new Map(current.map(meal=>[meal.id,meal]));requestedMeals.forEach(meal=>byId.set(meal.id,meal));return [...byId.values()]});setFilter('all');void attachFreePhotos(requestedMeals);
    }catch(e:any){setError(e.message)}finally{setLoading(false)}
  }
  async function react(meal:Meal,action:'like'|'skip'|'dislike'){
    if(action==='like'&&meal.is_concept){
      setLoading(true);setError('');
      try{
        const people=dayContexts[todayIndex]?.people||1;
        const servings=clamp(factor*people,0.1,12);
        const d=await api('/ai/recipe',{method:'POST',body:JSON.stringify({concept:meal,context:meal.discovery_prompt||brain,appliances,servings,people})});
        const recipe:Meal={...d.meal,image:meal.image||d.meal?.image||'',image_page:meal.image_page||'',photographer:meal.photographer||''};
        if(!recipe?.id)throw new Error('Bitewise could not build the selected recipe.');
        try{await api('/events',{method:'POST',body:JSON.stringify({meal_id:recipe.id,action:'like'})})}catch{}
        setLiked(x=>x.some(a=>a.id===recipe.id)?x:[...x,recipe]);
        setDetail(recipe);
        setSkipped(x=>[...new Set([...x,meal.id])]);
        setHistory(prev=>[
          {record_key:`recipe:${meal.id}`,record_type:'recipe',status:'saved',prompt:meal.discovery_prompt,meal:recipe},
          ...prev.map(row=>row.record_key===meal.id?{...row,status:'expanded'}:row),
        ]);
      }catch(e:any){setError(e.message)}finally{setLoading(false)}
      return;
    }
    if(meal.is_concept){
      const nextStatus=action==='dislike'?'disliked':'skipped';
      try{await api(`/recipe-history/${encodeURIComponent(meal.id)}`,{method:'PATCH',body:JSON.stringify({status:nextStatus})})}catch(e:any){setError('Could not update permanent history: '+e.message)}
      setHistory(prev=>prev.map(row=>row.record_key===meal.id?{...row,status:nextStatus}:row));
    }else{
      if(action==='like'){
        // Persist ordinary catalog meals just like AI-expanded recipes so Picks
        // remain available to the calendar and shopping basket after a reload.
        const recordKey='recipe:'+meal.id;
        const saved=await api('/recipe-history',{method:'POST',body:JSON.stringify({records:[{
          record_key:recordKey,record_type:'recipe',status:'saved',meal
        }]})});
        if(!saved?.ok||Number(saved.saved||0)<1)throw new Error('Could not save this Pick permanently. Please try again.');
        setHistory(current=>[{record_key:recordKey,record_type:'recipe',status:'saved',meal},...current.filter(row=>row.record_key!==recordKey)]);
      }
      try{await api('/events',{method:'POST',body:JSON.stringify({meal_id:meal.id,action})})}catch{}
    }
    if(action==='like')setLiked(x=>x.some(a=>a.id===meal.id)?x:[...x,meal]);
    else setSkipped(x=>[...new Set([...x,meal.id])]);
  }
  function servingTotals(includeUnplannedPicks=false){const totals:Record<string,number>={};weeklyPlan.forEach((d,idx)=>d.slots.forEach(s=>{if(s.meal)totals[s.meal.id]=(totals[s.meal.id]||0)+factor*(dayContexts[idx]?.people||1)}));if(!Object.keys(totals).length&&includeUnplannedPicks)liked.forEach(m=>totals[m.id]=factor);return totals}
  async function removePick(meal:Meal){
    setLiked(current=>current.filter(item=>item.id!==meal.id));
    const recordKey='recipe:'+String((meal as any).source_concept_id||meal.id);
    try{
      await api('/recipe-history/'+encodeURIComponent(recordKey),{
        method:'PATCH',body:JSON.stringify({status:'removed'})
      });
      setHistory(current=>current.map(row=>row.record_key===recordKey?{...row,status:'removed'}:row));
    }catch(e:any){setError('Pick removed locally but could not update permanent history: '+e.message)}
  }

  async function makeBasket(nextStrategy:Strategy=strategy,selectedExtras:ExtraItem[]=extras,selectedOwned:string[]=owned,includeUnplannedPicks=basketUsesUnplannedPicks){if(!liked.length&&!selectedExtras.length){setBasketUsesUnplannedPicks(false);setBasket([]);setSummary({recipe_total:0,extras_total:0,total:0});return;}setBasketUsesUnplannedPicks(includeUnplannedPicks);setLoading(true);setError('');try{const servings=servingTotals(includeUnplannedPicks);const d=Object.keys(servings).length?await api('/shopping',{method:'POST',body:JSON.stringify({meal_ids:Object.keys(servings),servings,owned:selectedOwned,mode:nextStrategy})}):{items:[],total:0};const recipeItems:BasketItem[]=d.items||d.basket||[];const extraItems:BasketItem[]=selectedExtras.map(extra=>{const requested=Math.max(0,Math.ceil(Number(extra.weeklyQuantity??1)||0));const onHand=Math.max(0,Math.floor(Number(extra.onHand)||0));const packs=Math.max(0,requested-onHand);const priced=Boolean(extra.product?.id&&extra.product?.price!==null&&extra.product?.price!==undefined);return {ingredient:`extra:${extra.id}`,quantity:requested,needed_quantity:packs,unit:'pack',product:extra.product,packs,total:priced?Number((packs*Number(extra.product!.price)).toFixed(2)):0,pantry_used:onHand,badge:extra.kind==='freezer-meal'?'Quick freezer meal':extra.kind==='beverage'?'Beverage':'Household extra',match_status:priced?'matched':'unmatched'} as BasketItem;}).filter(item=>item.needed_quantity!>0);const combined=[...recipeItems,...extraItems];const extrasTotal=extraItems.reduce((sum,item)=>sum+Number(item.total||0),0);setBasket(combined);setSummary({...d,recipe_total:d.total,extras_total:Number(extrasTotal.toFixed(2)),total:Number((Number(d.total||0)+extrasTotal).toFixed(2))});setTab('basket')}catch(e:any){setError(e.message)}finally{setLoading(false)}}
  async function addBasketToRewe(){
    const items=basket.filter(item=>item.product?.id&&exactRewe(item.product.product_url)&&Number(item.packs)>0).map(item=>({product_id:item.product!.id,packs:Math.max(1,Math.ceil(Number(item.packs)||1))}));
    if(!items.length){setError('No verified REWE product links are ready to add. Check unmatched products and alternatives first.');return;}
    if(!window.confirm('Add '+items.length+' products to your signed-in REWE cart using Chrome for Testing? This will not place an order or make a payment. Review the cart before checkout.'))return;
    setCartAdding(true);setCartReport(null);setError('');
    try{const result=await api('/rewe/cart/add',{method:'POST',body:JSON.stringify({items})});setCartReport(result)}catch(e:any){setError('REWE cart handoff failed: '+e.message)}finally{setCartAdding(false)}
  }
  async function changeStrategy(s:Strategy){setStrategy(s);await api('/settings',{method:'PATCH',body:JSON.stringify({shopping_strategy:s})});if(basket.length)await makeBasket(s)}
  async function toggleOwned(ingredient:string){if(ingredient.startsWith('extra:')){const id=ingredient.slice(6);const nextExtras=extras.map(item=>item.id===id?{...item,onHand:Math.max(Number(item.onHand)||0,Number(item.weeklyQuantity??1)||0)}:item);setExtras(nextExtras);await makeBasket(strategy,nextExtras);return;}const next=owned.includes(ingredient)?owned.filter(x=>x!==ingredient):[...owned,ingredient];setOwned(next);try{await api('/shopping/state',{method:'PUT',body:JSON.stringify({ingredient,state:next.includes(ingredient)?'owned':'needed'})});if(basket.length)await makeBasket(strategy,extras,next)}catch(e:any){setError('Could not update pantry status: '+e.message)}}
  async function openAlternatives(item:BasketItem){setAltItem(item);setAltError('');setAlternatives([]);try{if(item.product?.id&&!item.ingredient.startsWith('extra:')){const d=await api(`/products/${item.product.id}/alternatives?needed_qty=${encodeURIComponent(String(item.needed_quantity??item.quantity))}&unit=${encodeURIComponent(item.unit)}`);setAlternatives(d.alternatives||[])}else{const query=item.ingredient.startsWith('extra:')?(item.product?.name_original||item.ingredient):item.ingredient;const d=await api(`/products/search?q=${encodeURIComponent(query)}`);setAlternatives(d.products||[])}}catch(e:any){setAltError(e.message||'Could not load alternatives')}}
  async function chooseAlternative(p:Product){if(!altItem||!p.id)return;setAltError('');try{if(altItem.ingredient.startsWith('extra:')){const id=altItem.ingredient.slice(6);const nextExtras=extras.map(extra=>extra.id===id?{...extra,product:p,label:p.name_original}:extra);setExtras(nextExtras);await makeBasket(strategy,nextExtras);setAltItem(null);return;}await api('/products/replace',{method:'POST',body:JSON.stringify({ingredient:altItem.ingredient,product_id:p.id})});await makeBasket(strategy);setAltItem(null)}catch(e:any){setAltError(e.message||'Could not save this product choice')}}
  async function purchase(item:BasketItem){if(item.ingredient.startsWith('extra:')){const id=item.ingredient.slice(6);const nextExtras=extras.map(extra=>extra.id===id?{...extra,onHand:(Number(extra.onHand)||0)+Math.max(1,Number(item.packs)||1)}:extra);setExtras(nextExtras);await makeBasket(strategy,nextExtras);return;}if(!item.product?.id)return;await api('/shopping/purchase',{method:'POST',body:JSON.stringify({product_id:item.product.id,packs:item.packs,ingredient:item.ingredient})});setPantry(await api('/pantry'));await makeBasket(strategy)}
  function editPantryItem(item:any){setPantryDraftId(item.id);setPantryIngredient(item.ingredient||'');setPantryQuantity(String(item.quantity??1));setPantryUnit(item.unit||'g');setPantryExpiry(item.expiry_date||'');setPantryError('');}
  function resetPantryDraft(){setPantryDraftId(null);setPantryIngredient('');setPantryQuantity('1');setPantryUnit('g');setPantryExpiry('');setPantryError('');}
  async function savePantryDraft(){const ingredient=pantryIngredient.trim();const quantity=Number(pantryQuantity);if(!ingredient||!Number.isFinite(quantity)||quantity<0){setPantryError('Enter an ingredient and a valid quantity (zero or more).');return;}setPantrySaving(true);setPantryError('');try{const payload={ingredient,quantity,unit:pantryUnit.trim()||'unit',expiry_date:pantryExpiry||null};await api(pantryDraftId?'/pantry/'+pantryDraftId:'/pantry',{method:pantryDraftId?'PATCH':'POST',body:JSON.stringify(payload)});setPantry(await api('/pantry'));resetPantryDraft()}catch(e:any){setPantryError(e.message||'Could not save pantry item')}finally{setPantrySaving(false)}}
  async function deletePantryItem(item:any){if(!window.confirm('Remove '+item.ingredient+' from your pantry?'))return;try{await api('/pantry/'+item.id,{method:'DELETE'});setPantry(await api('/pantry'));if(pantryDraftId===item.id)resetPantryDraft()}catch(e:any){setPantryError(e.message||'Could not remove pantry item')}}
  async function searchExtras(){if(!extraQuery.trim())return;const d=await api(`/products/search?q=${encodeURIComponent(extraQuery)}`);setExtraResults(d.products||[])}
  async function addExtra(p:Product){const id=`${extraKind}-${p.id||p.name_original}`;if(extras.some(x=>x.id===id)){setTab('basket');return;}const next=[...extras,{id,kind:extraKind,label:p.name_original,product:p,dailyUse:extraKind==='beverage'?1:0,weeklyQuantity:1,onHand:0}];setExtras(next);await makeBasket(strategy,next);}
  function updateDay(i:number,patch:Partial<DayContext>){setDayContexts(x=>x.map((d,idx)=>idx===i?{...d,...patch}:d))}
  function assignDateMeal(date:Date,type:MealType,mealId:string){
    const key=dateKey(date)+':'+type;
    setCalendarAssignments(current=>{const next={...current};if(mealId)next[key]=mealId;else delete next[key];return next});
  }
  function assignMeal(day:number,type:MealType,mealId:string){const date=mondayOfCurrentWeek();date.setDate(date.getDate()+day);assignDateMeal(date,type,mealId)}
  function autoPlanWeek(){const generated=buildSmartWeek(liked);setCalendarAssignments(current=>{const next={...current};const monday=mondayOfCurrentWeek();for(let day=0;day<7;day++){const date=new Date(monday);date.setDate(date.getDate()+day);(['breakfast','lunch','dinner'] as MealType[]).forEach(type=>{delete next[dateKey(date)+':'+type];const id=generated[day+':'+type];if(id)next[dateKey(date)+':'+type]=id})}return next})}
  function clearWeek(){setCalendarAssignments(current=>{const next={...current};const monday=mondayOfCurrentWeek();for(let day=0;day<7;day++){const date=new Date(monday);date.setDate(date.getDate()+day);(['breakfast','lunch','dinner'] as MealType[]).forEach(type=>delete next[dateKey(date)+':'+type])}return next})}
  function changeCalendarMonth(delta:number){const current=new Date(calendarCursor+'T12:00:00');setCalendarCursor(dateKey(addMonths(current,delta)))}
  function updateExtra(id:string,patch:Partial<ExtraItem>){setExtras(x=>x.map(e=>e.id===id?{...e,...patch}:e))}

  return <div className="min-h-screen bg-[#f7f4ee] text-[#17211b]">
    <header className="sticky top-0 z-40 border-b border-[#17211b]/8 bg-[#f7f4ee]/92 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1500px] items-center justify-between px-5 py-3">
        <button onClick={()=>setTab('discover')} className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-xl bg-[#18392b] text-white"><UtensilsCrossed size={17}/></span><div className="text-left"><div className="font-black">Bitewise</div><div className="text-[9px] font-bold uppercase tracking-[.22em] text-[#18392b]/45">Eat well. Think less.</div></div></button>
        <nav className="hidden gap-1 rounded-full bg-white p-1 shadow-sm xl:flex">{(['discover','picks','history','plan','today','basket','extras'] as Tab[]).map(t=><button key={t} onClick={()=>setTab(t)} className={cx('rounded-full px-4 py-2 text-xs font-black capitalize transition',tab===t?'bg-[#18392b] text-white':'text-[#18392b]/50 hover:bg-[#edf3ee] hover:text-[#18392b]')}>{t}{t==='picks'&&liked.length?` ${liked.length}`:''}</button>)}</nav>
        <div className="flex gap-1"><button onClick={()=>setTab('pantry')} className="rounded-full bg-white p-2.5 shadow-sm"><Home size={16}/></button><button onClick={()=>setTab('settings')} className="rounded-full bg-white p-2.5 shadow-sm"><Settings size={16}/></button></div>
      </div>
    </header>

    <main className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6">
      {error&&<div className="mb-4 rounded-2xl bg-red-50 px-4 py-3 text-sm font-bold text-red-700">{error}</div>}

      {tab==='discover'&&<>
        <div className="grid gap-3 rounded-[26px] bg-[#18392b] p-5 text-white lg:grid-cols-[1fr_auto] lg:items-center"><div><div className="text-xs font-black uppercase tracking-[.18em] text-white/45">AI food decision engine</div><h1 className="mt-1 text-2xl font-black">What do you feel like eating?</h1><p className="mt-1 text-sm text-white/55">Browse lightweight ideas first. Bitewise creates the full recipe only when you pick one.</p></div><div className="text-right"><div className="text-xs text-white/40">Adaptive portion</div><div className="text-xl font-black">{factor.toFixed(2)}×</div></div></div>
        <div className="mt-4 flex gap-2 overflow-x-auto pb-1">{mealTypes.map(t=><button key={t.id} onClick={()=>setMealType(t.id)} className={cx('shrink-0 rounded-full px-4 py-2 text-sm font-black',mealType===t.id?'bg-[#dff2df] text-[#173b2d]':'bg-white text-[#173b2d]/55')}>{t.emoji} {t.label}</button>)}</div>
        <div className="mt-3 flex flex-col gap-2 rounded-2xl bg-white p-3 shadow-sm sm:flex-row"><input value={brain} onChange={e=>setBrain(e.target.value)} onKeyDown={e=>e.key==='Enter'&&!loading&&brain.trim()&&generateAI(brain)} disabled={loading} className="min-w-0 flex-1 rounded-xl bg-[#f3f1eb] px-4 py-3 text-sm outline-none" placeholder="Fancy but easy tonight · cheap breakfast · use what I have..."/><button onClick={()=>brain.trim()&&generateAI(brain)} disabled={loading} className="rounded-xl bg-[#18392b] px-5 py-3 text-sm font-black text-white disabled:opacity-50">{loading?'Thinking…':'Generate'}</button></div>
        <div className="mt-4 flex gap-2 overflow-x-auto pb-1">{cuisines.map(c=><button key={c} onClick={()=>setFilter(c)} className={cx('shrink-0 rounded-full border px-3 py-1.5 text-xs font-black capitalize',filter===c?'border-[#18392b] bg-[#18392b] text-white':'border-[#18392b]/10 bg-white text-[#18392b]/55')}>{c.replace('-',' ')}</button>)}</div>
        {!visible.length&&!loading?<div className="mt-5 rounded-[28px] bg-white p-10 text-center"><ChefHat className="mx-auto text-[#18392b]/20"/><div className="mt-3 font-black">No exact matches yet</div><button onClick={()=>generateAI(`${filter==='all'?'varied':filter} ${mealType} ideas`)} className="mt-4 rounded-full bg-[#18392b] px-5 py-2.5 text-sm font-black text-white">Generate matching meals</button></div>:!visible.length&&loading?<div className="mt-5 rounded-[28px] bg-white p-10 text-center text-sm font-bold text-[#18392b]/45">Creating your {mealType} ideas…</div>:<div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{visible.map(m=><MealCard key={m.id} meal={m} open={()=>!m.is_concept&&setDetail(m)} like={()=>react(m,'like')} skip={()=>react(m,'skip')} picked={false} busy={loading}/>)}</div>}
      </>}

      {tab==='picks'&&<><Title title="Your picks" sub="Only selected ideas become full recipes. Portions adapt to your profile and each day's guest count."/><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{liked.map(m=><MealCard key={m.id} meal={m} open={()=>setDetail(m)} like={()=>void removePick(m)} skip={()=>void removePick(m)} picked/>)}</div>{liked.length>0&&<button onClick={()=>makeBasket(strategy,extras,owned,true)} className="mt-6 rounded-2xl bg-[#18392b] px-5 py-3 text-sm font-black text-white"><ShoppingBasket size={15} className="mr-2 inline"/>Build adaptive weekly basket</button>}</>}

      {tab==='history'&&<><Title title="Recipe history" sub="Your generated ideas and completed recipes are saved in the permanent Bitewise database."/><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{history.map((row:any)=><article key={row.record_key} className="rounded-[22px] bg-white p-4 shadow-sm"><div className="flex items-center justify-between gap-2"><span className="text-[10px] font-black uppercase tracking-[.12em] text-[#18392b]/40">{row.record_type==='recipe'?'Full recipe':'Idea'}</span><span className="rounded-full bg-[#edf3ee] px-2 py-1 text-[10px] font-bold capitalize">{row.status}</span></div><div className="mt-2 font-black">{row.meal?.name||row.name}</div><div className="mt-1 text-xs text-[#18392b]/45">{row.meal?.meal_type||''} · {row.meal?.time||'—'} min</div><div className="mt-3 flex gap-2">{row.record_type==='recipe'?<button onClick={()=>setDetail(row.meal)} className="flex-1 rounded-xl bg-[#18392b] px-3 py-2 text-xs font-black text-white">Open recipe</button>:<button disabled={row.status==='expanded'||loading} onClick={()=>react(row.meal,'like')} className="flex-1 rounded-xl bg-[#18392b] px-3 py-2 text-xs font-black text-white disabled:opacity-40">{row.status==='expanded'?'Expanded':'Create recipe'}</button>}</div></article>)}</div>{!history.length&&<Empty text="Your generated ideas and recipes will appear here."/>}</>}

      {tab==='plan'&&<><div className="flex flex-wrap items-end justify-between gap-3"><Title title="Smart meal calendar" sub="Plan real meals from your saved Picks. Assign portions, avoid repeats and keep the week in sync with your shopping basket."/><div className="flex rounded-full bg-white p-1 shadow-sm">{(['week','month','year'] as CalendarView[]).map(v=><button key={v} onClick={()=>setCalendarView(v)} className={cx('rounded-full px-4 py-2 text-xs font-black capitalize',calendarView===v?'bg-[#18392b] text-white':'text-[#18392b]/45')}>{v}</button>)}</div></div><div className="mt-4 flex flex-wrap items-center gap-2"><button onClick={autoPlanWeek} disabled={!liked.length} className="rounded-xl bg-[#18392b] px-4 py-2.5 text-sm font-black text-white disabled:opacity-40">✨ Auto-plan from Picks</button><button onClick={()=>void makeBasket(strategy,extras,owned,false)} disabled={loading||weeklyStats.mealCount===0} className="rounded-xl bg-[#dff2df] px-4 py-2.5 text-sm font-black text-[#18392b] disabled:opacity-40">🛒 Build shopping list</button><button onClick={clearWeek} className="rounded-xl border border-[#18392b]/15 bg-white px-4 py-2.5 text-sm font-black">Clear week</button><span className="text-xs text-[#18392b]/45">Auto-plan balances variety, prep time and estimated cost. You can edit every slot.</span></div><Stats cost={weeklyStats.cost} calories={weeklyStats.avgCalories} count={weeklyStats.mealCount}/>{calendarView==='week'?<div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{weeklyPlan.map((d,i)=><DayCard key={dateKey(d.date)} day={d} index={i} context={dayContexts[i]} update={p=>updateDay(i,p)} open={setDetail} picks={liked} assign={assignMeal}/>)}</div>:calendarView==='month'?<MonthView month={new Date(calendarCursor+'T12:00:00')} assignments={calendarAssignments} picks={liked} assign={assignDateMeal} open={setDetail} navigate={changeCalendarMonth}/>:<YearView year={new Date(calendarCursor+'T12:00:00').getFullYear()} assignments={calendarAssignments} navigate={delta=>setCalendarCursor(String(new Date(calendarCursor+'T12:00:00').getFullYear()+delta)+'-01-01')} chooseMonth={month=>{setCalendarCursor(String(new Date(calendarCursor+'T12:00:00').getFullYear())+'-'+String(month+1).padStart(2,'0')+'-01');setCalendarView('month')}}/>}</>}

      {tab==='today'&&<><Title title="Today" sub={`${dayContexts[todayIndex]?.people||1} person${(dayContexts[todayIndex]?.people||1)>1?'s':''}${dayContexts[todayIndex]?.occasion?` · ${dayContexts[todayIndex].occasion}`:''}`}/><div className="mt-5 space-y-4">{todaySlots.length?todaySlots.map(s=><div key={s.type} className="grid overflow-hidden rounded-[26px] bg-white shadow-sm md:grid-cols-[280px_1fr]">{s.meal?.image?<img src={s.meal.image} className="h-56 w-full object-cover md:h-full"/>:<div className="h-56 bg-[#e8e5dc] md:h-full"/>}<div className="p-6"><div className="text-xs font-black uppercase tracking-[.16em] text-[#18392b]/35">{s.type}</div><div className="mt-1 text-2xl font-black">{s.meal?.name}</div><div className="mt-2 text-sm text-[#18392b]/45">≈ {Math.round(caloriesOf(s.meal!)*factor)} kcal for your portion · {s.meal?.time} min</div><RecipeSteps meal={s.meal!} appliances={appliances}/></div></div>):<Empty text="No meals planned for today yet."/>}</div></>}

      {tab==='basket'&&<><Title title="Adaptive basket" sub="Recipe ingredients and optional REWE extras, adjusted for portions and pantry stock."/><div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">REWE handoff: Bitewise can add matched products through your signed-in Chrome for Testing session. It never checks out or pays. Review quantities, availability and final prices in REWE before paying.</div><div className="mt-4 flex flex-wrap gap-2"><button onClick={()=>makeBasket()} disabled={loading||(!liked.length&&!extras.length)} className="rounded-xl bg-white px-4 py-2 text-xs font-black">↻ Rebuild basket</button><span className="self-center text-xs text-[#18392b]/45">Includes selected freezer meals, drinks and household extras.</span></div><div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{strategies.map(s=><button key={s.id} onClick={()=>changeStrategy(s.id)} className={cx('rounded-2xl border p-3 text-left text-sm font-black',strategy===s.id?'border-[#18392b] bg-[#18392b] text-white':'border-[#18392b]/10 bg-white')}>{s.icon} {s.label}</button>)}</div>{basket.length?<div className="mt-5 grid gap-5 xl:grid-cols-[1fr_320px]"><div className="space-y-3">{basket.map(item=><div key={item.ingredient} className="rounded-[22px] bg-white p-4 shadow-sm"><div className="flex items-start gap-3"><button onClick={()=>toggleOwned(item.ingredient)} className={cx('grid h-7 w-7 shrink-0 place-items-center rounded-lg border',owned.includes(item.ingredient)?'bg-[#18392b] text-white':'border-[#18392b]/15')}>{owned.includes(item.ingredient)&&<Check size={13}/>}</button><div className="min-w-0 flex-1"><div className="font-black capitalize">{item.ingredient.startsWith('extra:')?(item.badge||'Optional extra'):item.ingredient}</div><div className="text-xs text-[#18392b]/40">Need {item.needed_quantity??item.quantity} {item.unit}{item.pantry_used?` · pantry ${item.pantry_used} ${item.unit}`:''}</div>{item.product?<div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-[#f5f4ef] p-3"><div className="flex items-center gap-3"><div className="h-14 w-14 shrink-0 overflow-hidden rounded-lg bg-white">{item.product.image_url?<img src={item.product.image_url} alt={item.product.name_original} className="h-full w-full object-contain"/>:null}</div><div><div className="text-sm font-black">{item.product.name_original}</div></div><div className="text-xs text-[#18392b]/40">{item.packs} pack(s) · {item.product.price!=null?money(item.total):'Price unavailable — confirm on REWE'}</div>{item.match_status==='substituted'&&<div className="mt-1 text-xs font-bold text-[#9a5b24]">Culinary substitute</div>}{item.availability_status==='unknown'&&<div className="mt-1 text-xs font-bold text-[#9a5b24]">Stock unverified — check REWE</div>}</div><div className="flex gap-2"><button onClick={()=>openAlternatives(item)} className="rounded-lg bg-white px-3 py-2 text-xs font-black">Alternatives</button>{exactRewe(item.product.product_url)&&<a href={item.product.product_url!} target="_blank" rel="noreferrer" className="rounded-lg bg-white p-2"><ExternalLink size={14}/></a>}<button onClick={()=>purchase(item)} className="rounded-lg bg-[#18392b] px-3 py-2 text-xs font-black text-white"><PackageCheck size={13} className="mr-1 inline"/>Bought</button></div></div>:<div className="mt-2 text-xs font-bold text-amber-700">{item.match_status==='covered'?'Covered by pantry / already owned.':'No compatible priced REWE product found. Add this ingredient manually or search REWE before shopping.'}</div>}</div></div></div>)}</div><aside className="h-fit rounded-[24px] bg-[#18392b] p-5 text-white"><div className="text-xs uppercase tracking-[.16em] text-white/40">Estimated REWE checkout</div><div className="mt-2 text-4xl font-black">{money(summary?.total)}</div><div className="mt-2 text-xs text-white/55">Recipes {money(summary?.recipe_total)} · Extras {money(summary?.extras_total)}</div><div className="mt-2 text-xs text-white/65">{basket.filter(item=>item.match_status==='unmatched').length} ingredient(s) without a priced REWE match — not included in the estimate.</div><div className="mt-5 text-sm text-white/60">Estimate from the saved REWE catalog. Confirm current prices, delivery availability and substitutions on REWE before paying.</div><button onClick={addBasketToRewe} disabled={cartAdding||!basket.some(item=>item.product?.id&&exactRewe(item.product.product_url)&&Number(item.packs)>0)} className="mt-4 w-full rounded-xl bg-[#dff2df] px-4 py-3 text-sm font-black text-[#18392b] disabled:opacity-50">{cartAdding?'Adding products to REWE…':'🛒 Add matched products to REWE cart'}</button>{cartReport&&<div className="mt-3 rounded-xl border border-[#18392b]/10 bg-white p-3 text-xs"><div className="font-black">REWE cart handoff results</div><div className="mt-1">{(cartReport.results||[]).filter((x:any)=>x.status==='added').length} confirmed · {(cartReport.results||[]).filter((x:any)=>x.status!=='added').length} need review</div><div className="mt-2 space-y-1">{(cartReport.results||[]).map((x:any,i:number)=><div key={i} className="flex justify-between gap-2"><span>{x.name}</span><b>{x.status}</b></div>)}</div><div className="mt-2 font-bold">No checkout or payment was performed. Verify the REWE cart manually.</div></div>}<button onClick={()=>setTab('extras')} className="mt-3 w-full rounded-xl bg-white px-4 py-3 text-sm font-black text-[#18392b]">Open extras & freezer meals</button></aside></div>:<Empty text="Add a saved recipe or a REWE extra to build your shopping basket."/>}</>}

      {tab==='extras'&&<><Title title="Quick meals & extras" sub="Add optional supermarket shortcuts and household items to the same weekly shopping estimate."/><div className="mt-4 flex flex-wrap gap-2"><button onClick={()=>setExtraKind('freezer-meal')} className={cx('rounded-full px-4 py-2 text-sm font-black',extraKind==='freezer-meal'?'bg-[#18392b] text-white':'bg-white')}>❄️ Quick freezer meals</button><button onClick={()=>setExtraKind('beverage')} className={cx('rounded-full px-4 py-2 text-sm font-black',extraKind==='beverage'?'bg-[#18392b] text-white':'bg-white')}>🥤 Beverages</button><button onClick={()=>setExtraKind('non-food')} className={cx('rounded-full px-4 py-2 text-sm font-black',extraKind==='non-food'?'bg-[#18392b] text-white':'bg-white')}>🧻 Non-food</button></div><div className="mt-3 flex gap-2"><input value={extraQuery} onChange={e=>setExtraQuery(e.target.value)} className="flex-1 rounded-xl bg-white px-3 py-2.5" placeholder={extraKind==='freezer-meal'?'Search e.g. Pizza Baguette, TK-Pizza, Gyoza…':'Search REWE catalog…'}/><button onClick={searchExtras} className="rounded-xl bg-[#18392b] px-4 py-2 text-sm font-black text-white">Search</button></div><div className="mt-4 grid gap-2 md:grid-cols-2">{extraResults.map(p=>{const alreadyAdded=extras.some(x=>x.id===`${extraKind}-${p.id||p.name_original}`);return <article key={String(p.id)+p.name_original} className="flex gap-3 rounded-xl bg-white p-3"><div className="h-20 w-20 shrink-0 overflow-hidden rounded-lg bg-[#f3f1eb]">{p.image_url?<img src={p.image_url} alt={p.name_original} loading="lazy" className="h-full w-full object-contain"/>:<div className="grid h-full place-items-center text-[9px] font-bold text-[#18392b]/30">No photo</div>}</div><div className="min-w-0 flex-1"><div className="font-black">{p.name_original}</div><div className="text-xs text-[#18392b]/40">{p.brand||''}{p.brand?' · ':''}{p.price!=null?money(p.price):'Price unavailable'}</div><button disabled={alreadyAdded} onClick={()=>void addExtra(p)} className="mt-2 rounded-lg bg-[#18392b] px-3 py-2 text-xs font-black text-white disabled:bg-[#dff2df] disabled:text-[#18392b]">{alreadyAdded?'✓ Added to basket':'＋ Add to basket'}</button></div></article>})}</div><div className="mt-5 grid gap-3 lg:grid-cols-2">{extras.map(e=><div key={e.id} className="flex gap-3 rounded-[22px] bg-white p-4"><div className="h-20 w-20 shrink-0 overflow-hidden rounded-xl bg-[#f3f1eb]">{e.product?.image_url?<img src={e.product.image_url} alt={e.label} className="h-full w-full object-contain"/>:<div className="grid h-full place-items-center text-[9px] font-bold text-[#18392b]/30">No photo</div>}</div><div className="min-w-0 flex-1"><div className="font-black">{e.label}</div><div className="mt-1 text-xs text-[#18392b]/45">{e.kind==='freezer-meal'?'Ready-made backup meal':e.kind==='beverage'?'Drink':'Household item'} · {e.product?.price!=null?money(e.product.price)+' / pack':'Price unavailable'}</div><div className="mt-3 grid grid-cols-2 gap-2"><label className="text-xs">Packs needed this week<input type="number" min="0" value={e.weeklyQuantity??1} onChange={x=>updateExtra(e.id,{weeklyQuantity:Math.max(0,Number(x.target.value)||0)})} className="mt-1 w-full rounded-lg bg-[#f3f1eb] p-2"/></label><label className="text-xs">Packs already at home<input type="number" min="0" value={e.onHand} onChange={x=>updateExtra(e.id,{onHand:Math.max(0,Number(x.target.value)||0)})} className="mt-1 w-full rounded-lg bg-[#f3f1eb] p-2"/></label></div></div></div>)}</div><button onClick={()=>makeBasket()} disabled={loading||(!liked.length&&!extras.length)} className="mt-5 rounded-xl bg-[#18392b] px-5 py-3 text-sm font-black text-white disabled:opacity-40">Build weekly shopping basket</button></>}

      {tab==='pantry'&&<><Title title="Pantry" sub="Track what you already have so Bitewise can reduce purchases and help use ingredients up."/><div className="mt-5 rounded-[22px] bg-white p-4 shadow-sm"><div className="font-black">{pantryDraftId?'Edit pantry item':'Add pantry item'}</div><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><label className="text-xs font-bold text-[#18392b]/55">Ingredient<input value={pantryIngredient} onChange={e=>setPantryIngredient(e.target.value)} placeholder="e.g. tomatoes" className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm text-[#18392b]"/></label><label className="text-xs font-bold text-[#18392b]/55">Quantity<input type="number" min="0" step="any" value={pantryQuantity} onChange={e=>setPantryQuantity(e.target.value)} className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm text-[#18392b]"/></label><label className="text-xs font-bold text-[#18392b]/55">Unit<input value={pantryUnit} onChange={e=>setPantryUnit(e.target.value)} placeholder="g, kg, ml, l, pcs" className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm text-[#18392b]"/></label><label className="text-xs font-bold text-[#18392b]/55 lg:col-span-2">Use by (optional)<input type="date" value={pantryExpiry} onChange={e=>setPantryExpiry(e.target.value)} className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm text-[#18392b]"/></label></div>{pantryError&&<div role="alert" className="mt-3 text-xs font-bold text-red-700">{pantryError}</div>}<div className="mt-3 flex gap-2"><button onClick={savePantryDraft} disabled={pantrySaving} className="rounded-xl bg-[#18392b] px-4 py-2.5 text-xs font-black text-white disabled:opacity-50">{pantrySaving?'Saving…':pantryDraftId?'Save changes':'Add to pantry'}</button>{pantryDraftId&&<button onClick={resetPantryDraft} className="rounded-xl bg-[#f3f1eb] px-4 py-2.5 text-xs font-black">Cancel</button>}</div></div><div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{pantry.map((p:any)=><div key={p.id} className="rounded-xl bg-white p-4 shadow-sm"><div className="flex items-start justify-between gap-2"><div className="font-black capitalize">{p.ingredient}</div><div className="text-xs font-bold tabular-nums">{p.quantity} {p.unit}</div></div>{p.expiry_date&&<div className="mt-1 text-xs text-[#18392b]/45">Use by {p.expiry_date}</div>}<div className="mt-3 flex gap-2"><button onClick={()=>editPantryItem(p)} className="rounded-lg bg-[#f3f1eb] px-3 py-1.5 text-xs font-black">Edit</button><button onClick={()=>deletePantryItem(p)} className="rounded-lg bg-[#f3f1eb] px-3 py-1.5 text-xs font-black text-red-700">Remove</button></div></div>)}</div>{pantry.length===0&&<Empty text="Your pantry is empty. Add ingredients you already have to reduce unnecessary purchases."/>}</>}
      {tab==='settings'&&<><Title title="Your profile" sub="Used only to estimate practical portion sizes. This is not medical or nutrition advice."/><div className="mt-5 grid gap-5 lg:grid-cols-2"><div className="rounded-[24px] bg-white p-5 shadow-sm"><div className="font-black">Portion sizing</div><div className="mt-4 grid grid-cols-2 gap-3"><label className="text-xs font-bold text-[#18392b]/50">Height (cm)<input type="number" value={profile.heightCm} onChange={e=>setProfile({...profile,heightCm:Number(e.target.value)})} className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm text-[#18392b]"/></label><label className="text-xs font-bold text-[#18392b]/50">Weight (kg)<input type="number" value={profile.weightKg} onChange={e=>setProfile({...profile,weightKg:Number(e.target.value)})} className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm text-[#18392b]"/></label></div></div><div className="rounded-[24px] bg-white p-5 shadow-sm"><div className="font-black">Kitchen equipment & cooking priority</div><p className="mt-1 text-xs text-[#18392b]/50">Select what you own. Your selection order sets the recipe priority — first is preferred.</p><div className="mt-4 grid grid-cols-2 gap-2">{applianceOptions.map(a=><button key={a.id} onClick={()=>setAppliances(x=>x.includes(a.id)?x.filter(v=>v!==a.id):[...x,a.id])} className={cx('flex items-center gap-2 rounded-xl border p-3 text-sm font-black',appliances.includes(a.id)?'border-[#18392b] bg-[#dff2df]':'border-[#18392b]/10')}>{a.icon}{a.label}{appliances.includes(a.id)&&<><span className="ml-auto text-[10px] font-black">{appliances.indexOf(a.id)+1}</span><Check size={13}/></>}</button>)}</div><div className="mt-3 rounded-xl bg-[#f3f1eb] px-3 py-2 text-xs font-bold text-[#18392b]/65">Priority: {appliances.length?appliances.join(' → '):'No preference selected'}</div></div></div></>}
    </main>


    {altItem&&<div className="fixed inset-0 z-[60] overflow-y-auto bg-black/55 p-4" onClick={()=>setAltItem(null)}><div className="mx-auto mt-8 max-w-2xl rounded-[28px] bg-white p-5 shadow-2xl" onClick={e=>e.stopPropagation()}><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-black uppercase tracking-[.15em] text-[#18392b]/40">Choose this ingredient</div><h2 className="mt-1 text-2xl font-black capitalize">{altItem.ingredient}</h2><p className="mt-1 text-sm text-[#18392b]/55">Your current basket strategy stays unchanged. Choose a different product just for this ingredient.</p></div><button onClick={()=>setAltItem(null)} className="rounded-xl bg-[#f3f1eb] p-2"><X size={18}/></button></div>{(()=>{const ranked=[...alternatives].filter(p=>p.id&&p.price!=null&&Number(p.price)>0).sort((a,b)=>(Number(a.price_per_unit??(Number(a.price)/Math.max(Number(a.package_size)||1,0.0001))))-(Number(b.price_per_unit??(Number(b.price)/Math.max(Number(b.package_size)||1,0.0001)))));const current=altItem.product?.id;const groups=[{label:'Economic',emoji:'💰',items:ranked.slice(0,Math.max(1,Math.ceil(ranked.length/3)))},{label:'Mid-range',emoji:'⭐',items:ranked.slice(Math.ceil(ranked.length/3),Math.max(Math.ceil(ranked.length/3),Math.ceil(ranked.length*2/3)))},{label:'Premium / other',emoji:'✨',items:ranked.slice(Math.ceil(ranked.length*2/3))}];return <div className="mt-5 space-y-4">{groups.map(group=><section key={group.label}><div className="mb-2 text-xs font-black uppercase tracking-wide text-[#18392b]/45">{group.emoji} {group.label}</div>{group.items.length?<div className="space-y-2">{group.items.map(p=><button key={p.id} onClick={()=>void chooseAlternative(p)} className={cx('flex w-full items-center gap-3 rounded-xl border p-3 text-left',current===p.id?'border-[#18392b] bg-[#edf5ec]':'border-[#18392b]/10 bg-[#faf9f6]')}><div className="h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-white">{p.image_url&&<img src={p.image_url} alt={p.name_original} className="h-full w-full object-contain"/>}</div><div className="min-w-0 flex-1"><div className="text-sm font-black">{p.name_original}</div><div className="text-xs text-[#18392b]/45">{p.brand||'REWE'} · {p.package_size} {p.package_unit}</div></div><div className="text-right"><div className="font-black">{money(p.price)}</div><div className="text-[10px] text-[#18392b]/45">{Number(p.price_per_unit??(Number(p.price)/Math.max(Number(p.package_size)||1,0.0001))).toFixed(2)} € / {p.package_unit}</div></div>{current===p.id&&<Check size={16}/>}</button>)}</div>:<div className="rounded-xl bg-[#f7f5ef] p-3 text-xs text-[#18392b]/45">No priced REWE product in this range.</div>}</section>)}</div>})()}{altError&&<div role="alert" className="mt-4 rounded-xl bg-amber-50 p-3 text-sm font-bold text-amber-800">{altError}</div>}{alternatives.length===0&&!altError&&<div className="mt-4 text-sm text-[#18392b]/50">No compatible alternatives found for this ingredient.</div>}<p className="mt-4 text-[11px] text-[#18392b]/40">The price-per-package-unit ranking is a guide, not a quality rating. Your selection is saved for this ingredient and the basket is recalculated.</p></div></div>}

    {detail&&<div className="fixed inset-0 z-50 overflow-y-auto bg-black/55 p-4" onClick={()=>setDetail(null)}><div className="mx-auto mt-8 max-w-3xl overflow-hidden rounded-[30px] bg-white shadow-2xl" onClick={e=>e.stopPropagation()}>{detail.image?<img src={detail.image} className="h-64 w-full object-cover"/>:<div className="h-64 bg-[#e8e5dc]"/>}<div className="p-6"><div className="flex justify-between gap-4"><div><div className="text-xs font-black uppercase text-[#18392b]/35">{mealTypeOf(detail)} · ≈ {Math.round(caloriesOf(detail)*factor)} kcal your portion</div><h2 className="mt-1 text-3xl font-black">{detail.name}</h2></div><button onClick={()=>setDetail(null)}><X/></button></div>{detail.costing&&<div className="mt-5 rounded-2xl border border-[#18392b]/10 bg-[#f7f4ee] p-4"><div className="font-black">REWE product matching</div><div className="mt-2 text-sm text-[#18392b]/65">{detail.costing.catalog_ready?`${detail.costing.matched_ingredients} exact matches · ${detail.costing.substituted_ingredients||0} substitutions · ${detail.costing.covered_ingredients||0} pantry-covered · ${detail.costing.unmatched_ingredients||0} unmatched.`:"REWE catalog has not been loaded yet. Refresh the catalog to get real product matches and prices."}</div><div className="mt-2 text-xs font-bold">{detail.costing.shopping_ready===true?"All ingredients resolved to priced REWE catalog products or pantry; stock still needs confirmation.":"Not fully resolved yet: one or more ingredients still need a valid REWE match or culinary substitution."}</div>{detail.costing.checkout_total!==null&&<div className="mt-3 grid grid-cols-2 gap-3"><div><div className="text-[10px] font-bold uppercase text-[#18392b]/40">{detail.costing.unmatched_ingredients?"Matched items checkout subtotal":"Checkout estimate"}</div><div className="text-xl font-black">{money(detail.costing.checkout_total)}</div></div><div><div className="text-[10px] font-bold uppercase text-[#18392b]/40">{detail.costing.unmatched_ingredients?"Matched ingredients consumed cost":"Consumed ingredient cost"}</div><div className="text-xl font-black">{money(detail.costing.consumed_cost)}</div>{detail.costing.cost_per_serving!==null&&detail.costing.cost_per_serving!==undefined&&<div className="mt-1 text-xs text-[#18392b]/55">{money(detail.costing.cost_per_serving)} catalog-covered ingredients / serving</div>}</div></div>}{(detail.product_matches||[]).map((x:any,i:number)=>(
  <div key={i} className="mt-3 border-t border-[#18392b]/10 pt-3 text-xs">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="font-black">{x.ingredient} <span className="font-normal text-[#18392b]/45">· {x.needed_quantity??x.quantity} {x.unit} needed</span></div>
        <div className="mt-1 text-[#18392b]/60">{x.product?x.product.name_original:(x.match_status==="covered"?"Covered by pantry":"No compatible priced REWE product found")}</div>
        {x.product ? (
          <div className="mt-1 text-[#18392b]/45">
            {x.packs} pack(s) · {x.package_quantity} {x.package_unit} purchased · {x.product.price!==null?money(x.product.price)+" / pack":""}
            {x.availability_status==="unknown" && <span className="ml-2 font-semibold text-[#9a5b24]">Stock unverified</span>}
          </div>
        ) : null}
      </div>
      <div className="shrink-0 text-right">
        {x.match_status==="matched"||x.match_status==="substituted" ? (
          <>
            <div className="font-black">{money(x.checkout_cost??x.total)} checkout</div>
            <div className="mt-1 text-[#18392b]/55">{money(x.consumed_cost)} consumed</div>
            {x.match_status==="substituted" && <div className="mt-1 font-bold text-[#9a5b24]">Culinary substitute: {x.product?.ingredient_substitute||x.product?.ingredient||"adapted ingredient"}</div>}
          </>
        ) : (
          <span className="font-bold text-[#9a5b24]">{x.match_status==="covered"?"Covered":"Unmatched"}</span>
        )}
      </div>
    </div>
  </div>
))}</div>}<RecipeSteps meal={detail} appliances={appliances}/></div></div></div>}
  </div>
}

function MealCard({meal,open,like,skip,picked,busy=false}:{meal:Meal;open:()=>void;like:()=>void;skip:()=>void;picked:boolean;busy?:boolean}){
  return <article className="group overflow-hidden rounded-[24px] bg-white shadow-sm transition hover:-translate-y-1 hover:shadow-xl"><button onClick={open} className="block w-full text-left"><div className="aspect-[4/3] overflow-hidden bg-[#e8e5dc]">{meal.image?<img src={meal.image} alt={meal.name} className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.04]" loading="lazy"/>:<div className="grid h-full place-items-center text-xs font-black uppercase tracking-[.12em] text-[#18392b]/25">Finding photo…</div>}</div><div className="p-4"><div className="flex items-start justify-between gap-2"><h3 className="font-black leading-tight">{meal.name}</h3><span className="shrink-0 rounded-full bg-[#dff2df] px-2 py-1 text-[10px] font-black">≈{caloriesOf(meal)} kcal</span></div><div className="mt-2 text-xs text-[#18392b]/45">{meal.time} min · {meal.cuisine} · {money(meal.cost)}</div>{meal.is_concept&&<div className="mt-2 text-[10px] font-black uppercase tracking-[.12em] text-[#18392b]/35">Recipe generated only if you pick it</div>}{meal.image_page&&<a href={meal.image_page} target="_blank" rel="noreferrer" onClick={e=>e.stopPropagation()} className="mt-2 block text-[10px] font-bold text-[#18392b]/35">Photo{meal.photographer?` by ${meal.photographer}`:''} · Pexels</a>}</div></button><div className="flex gap-2 px-4 pb-4"><button disabled={busy} onClick={skip} className="rounded-xl border border-[#18392b]/10 p-2 disabled:opacity-40"><X size={14}/></button><button disabled={busy} onClick={like} className="flex-1 rounded-xl bg-[#18392b] px-3 py-2 text-xs font-black text-white disabled:opacity-40">{picked?'Remove':'♥ I’d eat this'}</button></div></article>
}
function RecipeSteps({meal,appliances}:{meal:Meal;appliances:string[]}){const steps=meal.steps?.length?meal.steps:fallbackSteps(meal,appliances);return <div className="mt-5"><div className="text-xs font-black uppercase tracking-[.16em] text-[#18392b]/35">Fastest way</div><div className="mt-3 space-y-2">{steps.map((s,i)=><div key={i} className="flex gap-3 rounded-xl bg-[#f7f5ef] p-3"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#18392b] text-[10px] font-black text-white">{i+1}</span><div className="text-sm"><b>{s.text}</b>{s.minutes?<span className="ml-2 text-xs text-[#18392b]/40">~{s.minutes} min</span>:null}</div></div>)}</div></div>}
function DayCard({day,index,context,update,open,picks,assign}:{day:{day:number;date:Date;slots:Slot[]};index:number;context:DayContext;update:(p:Partial<DayContext>)=>void;open:(m:Meal)=>void;picks:Meal[];assign:(day:number,type:MealType,mealId:string)=>void}){
  const types:MealType[]=['breakfast','lunch','dinner'];
  return <div className="rounded-[22px] bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><div className="text-xs font-black uppercase text-[#18392b]/35">{dayNames[index]} · {dateLabel(day.date)}</div><div className="font-black">{day.slots.length} planned meal{day.slots.length===1?'':'s'}</div></div><CalendarDays size={16} className="text-[#18392b]/25"/></div><div className="mt-3 flex items-center gap-2"><label className="text-xs font-bold text-[#18392b]/50">People <input aria-label={`People on ${dayNames[index]}`} type="number" min="1" max="12" value={context?.people||1} onChange={e=>update({people:Math.max(1,Math.min(12,Number(e.target.value)||1))})} className="ml-1 w-14 rounded-lg bg-[#f3f1eb] px-2 py-1.5 text-sm text-[#18392b]"/></label><input aria-label={`Occasion on ${dayNames[index]}`} value={context?.occasion||''} onChange={e=>update({occasion:e.target.value})} placeholder="Notes (optional)" className="min-w-0 flex-1 rounded-lg bg-[#f3f1eb] px-2 py-1.5 text-xs"/></div><div className="mt-3 space-y-3">{types.map(type=>{const meal=day.slots.find(x=>x.type===type)?.meal||null;const candidates=picks.filter(m=>mealTypeOf(m)===type);return <div key={type} className="rounded-xl bg-[#f7f5ef] p-2"><div className="text-[9px] font-black uppercase tracking-wide text-[#18392b]/40">{type}</div><select aria-label={`${dayNames[index]} ${type}`} value={meal?.id||''} onChange={e=>assign(index,type,e.target.value)} className="mt-1 w-full rounded-lg border-0 bg-white px-2 py-2 text-xs font-bold text-[#18392b]"><option value="">Not planned</option>{candidates.map(m=><option key={m.id} value={m.id}>{m.name} · {m.time||'?'} min · {money(m.cost)}</option>)}</select>{meal&&<button onClick={()=>open(meal)} className="mt-2 flex w-full items-center gap-2 text-left">{meal.image&&<img src={meal.image} className="h-10 w-12 rounded-lg object-cover"/>}<span className="min-w-0 flex-1 text-xs font-black">{meal.name}</span><span className="text-[10px] text-[#18392b]/45">Open recipe</span></button>}</div>})}</div></div>
}
function Stats({cost,calories,count}:{cost:number;calories:number;count:number}){return <div className="mt-5 grid gap-3 sm:grid-cols-3"><Stat label="Recipe cost estimate" value={money(cost)}/><Stat label="Avg kcal / day" value={calories}/><Stat label="Planned meals" value={count}/></div>}
function MonthView({month,assignments,picks,assign,open,navigate}:{month:Date;assignments:Record<string,string>;picks:Meal[];assign:(date:Date,type:MealType,id:string)=>void;open:(meal:Meal)=>void;navigate:(delta:number)=>void}){
  const first=new Date(month.getFullYear(),month.getMonth(),1);
  const offset=(first.getDay()+6)%7;
  const days=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();
  const cells=[...Array(offset).fill(null),...Array.from({length:days},(_,i)=>new Date(month.getFullYear(),month.getMonth(),i+1))];
  const types:MealType[]=['breakfast','lunch','dinner'];
  return <div className="mt-5"><div className="mb-3 flex items-center justify-between rounded-2xl bg-white p-3"><button onClick={()=>navigate(-1)} className="rounded-lg bg-[#f3f1eb] px-3 py-2 text-sm font-black">←</button><div className="text-lg font-black">{month.toLocaleDateString(undefined,{month:'long',year:'numeric'})}</div><button onClick={()=>navigate(1)} className="rounded-lg bg-[#f3f1eb] px-3 py-2 text-sm font-black">→</button></div><div className="grid grid-cols-7 gap-1">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d=><div key={d} className="p-1 text-center text-[10px] font-black uppercase text-[#18392b]/40">{d}</div>)}{cells.map((date,i)=>date?<div key={dateKey(date)} className="min-h-[145px] min-w-0 rounded-xl bg-white p-1.5 shadow-sm sm:min-h-[190px] sm:p-2"><div className="mb-1 text-xs font-black">{date.getDate()}</div><div className="space-y-1">{types.map(type=>{const meal=picks.find(m=>m.id===assignments[dateKey(date)+':'+type])||null;return <div key={type}><div className="hidden text-[8px] font-black uppercase text-[#18392b]/35 sm:block">{type.slice(0,1)}</div><select aria-label={dateKey(date)+' '+type} value={meal?.id||''} onChange={e=>assign(date,type,e.target.value)} className="w-full min-w-0 rounded-md border-0 bg-[#f4f2ec] px-1 py-1 text-[9px] font-bold text-[#18392b] sm:text-[10px]"><option value="">{type==='breakfast'?'B':type==='lunch'?'L':'D'} · —</option>{picks.filter(m=>mealTypeOf(m)===type).map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select>{meal&&<button onClick={()=>open(meal)} className="mt-0.5 block w-full truncate text-left text-[9px] font-bold text-[#18392b]/70">{meal.name}</button>}</div>})}</div></div>:<div key={'blank-'+i} className="min-h-[145px] rounded-xl bg-[#eae7df]/50 sm:min-h-[190px]"/> )}</div><div className="mt-2 text-xs text-[#18392b]/45">Select a meal in any date cell to save it. Changes are stored locally and also appear in the weekly plan when the date belongs to the current week.</div></div>
}
function YearView({year,assignments,navigate,chooseMonth}:{year:number;assignments:Record<string,string>;navigate:(delta:number)=>void;chooseMonth:(month:number)=>void}){
  return <div className="mt-5"><div className="mb-3 flex items-center justify-between rounded-2xl bg-white p-3"><button onClick={()=>navigate(-1)} className="rounded-lg bg-[#f3f1eb] px-3 py-2 text-sm font-black">←</button><div className="text-lg font-black">{year}</div><button onClick={()=>navigate(1)} className="rounded-lg bg-[#f3f1eb] px-3 py-2 text-sm font-black">→</button></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Array.from({length:12},(_,month)=>{const first=new Date(year,month,1);const offset=(first.getDay()+6)%7;const days=new Date(year,month+1,0).getDate();const planned=Object.keys(assignments).filter(key=>key.startsWith(year+'-'+String(month+1).padStart(2,'0')+'-')).length;return <button key={month} onClick={()=>chooseMonth(month)} className="rounded-[20px] bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5"><div className="mb-1 flex items-center justify-between"><span className="font-black">{first.toLocaleDateString(undefined,{month:'long'})}</span><span className="text-[10px] font-black text-[#18392b]/45">{planned} meals</span></div><div className="grid grid-cols-7 gap-1 text-center text-[9px] text-[#18392b]/45">{['M','T','W','T','F','S','S'].map((d,i)=><span key={i} className="font-black">{d}</span>)}{Array.from({length:offset},(_,i)=><span key={'x'+i}/>)}{Array.from({length:days},(_,i)=>{const date=new Date(year,month,i+1);const active=['breakfast','lunch','dinner'].some(type=>assignments[dateKey(date)+':'+type]);return <span key={i+1} className={'rounded py-1 '+(active?'bg-[#dff2df] font-black text-[#18392b]':'bg-[#f3f1eb]')}>{i+1}</span>})}</div><div className="mt-2 text-[10px] font-black text-[#18392b]/45">Open month →</div></button>})}</div></div>
}
function Title({title,sub}:{title:string;sub:string}){return <div><div className="text-xs font-black uppercase tracking-[.17em] text-[#18392b]/35">Bitewise</div><h1 className="mt-1 text-3xl font-black">{title}</h1><p className="mt-1 text-sm text-[#18392b]/45">{sub}</p></div>}
function Stat({label,value}:{label:string;value:any}){return <div className="rounded-[20px] bg-white p-4 shadow-sm"><div className="text-[10px] font-black uppercase tracking-[.14em] text-[#18392b]/35">{label}</div><div className="mt-1 text-2xl font-black">{String(value)}</div></div>}
function Empty({text}:{text:string}){return <div className="mt-5 rounded-[24px] border border-dashed border-[#18392b]/15 bg-white p-10 text-center text-sm font-bold text-[#18392b]/35">{text}</div>}
