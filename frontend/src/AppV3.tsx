import React, { useEffect, useMemo, useState } from 'react';
import {
  AirVent, CalendarDays, Check, ChefHat, Clock3, ExternalLink, Flame, Heart, Home,
  Microwave, PackageCheck, Plus, RefreshCw, Search, Settings, ShoppingBasket,
  Sparkles, UtensilsCrossed, X,
} from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const K = 'bitewise.v3.';

type MealType = 'breakfast' | 'lunch' | 'dinner' | 'dessert' | 'snack';
type Tab = 'discover'|'picks'|'plan'|'today'|'basket'|'extras'|'pantry'|'settings';
type Strategy = 'maximum-savings'|'best-value'|'plan-efficiency'|'premium';
type CalendarView = 'week'|'month'|'year';
type Meal = {
  id:string; name:string; description:string; time:number; difficulty:string; cost:number; cuisine:string;
  tags:string[]; ingredients:[string,number,string][]; image:string; calories?:number; meal_type?:MealType;
  steps?:{text:string;minutes?:number|null}[]; is_concept?:boolean; discovery_prompt?:string;
};
type Product = {
  id:number|null; name_original:string; brand?:string|null; package_size:number; package_unit:string;
  price:number|null; product_url?:string|null; ingredient?:string;
};
type BasketItem = {
  ingredient:string; quantity:number; needed_quantity?:number; unit:string; product:Product|null;
  packs:number; total:number; pantry_used?:number; badge?:string;
};
type Profile = { heightCm:number; weightKg:number; portionPreference:number };
type DayContext = { people:number; occasion:string };
type ExtraItem = {
  id:string; kind:'beverage'|'non-food'; label:string; product:Product|null; dailyUse:number; onHand:number;
};

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
  if(!r.ok) throw new Error((await r.text())||`HTTP ${r.status}`);
  return r.json();
}
function read<T>(key:string,fallback:T):T{try{const v=localStorage.getItem(K+key);return v?JSON.parse(v):fallback}catch{return fallback}}
function save(key:string,value:unknown){try{localStorage.setItem(K+key,JSON.stringify(value))}catch{}}
function money(v?:number|null){return `€${Number(v||0).toFixed(2)}`}
function cx(...v:(string|false|null|undefined)[]){return v.filter(Boolean).join(' ')}
function clamp(v:number,min:number,max:number){return Math.min(max,Math.max(min,v))}
function mealTypeOf(m:Meal):MealType{
  if(m.meal_type)return m.meal_type;
  const s=`${m.name} ${m.description} ${(m.tags||[]).join(' ')}`.toLowerCase();
  if(/breakfast|oat|pancake|toast|granola|omelette|yogurt/.test(s))return 'breakfast';
  if(/dessert|cake|cookie|brownie|tiramisu|pudding|sweet/.test(s))return 'dessert';
  if(/snack|smoothie|bite|bar/.test(s))return 'snack';
  if(/lunch|salad|sandwich|wrap/.test(s))return 'lunch';
  return 'dinner';
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
function portionFactor(profile:Profile){
  const body=Math.sqrt((Math.max(profile.weightKg,35)/70)*(Math.max(profile.heightCm,140)/170));
  return clamp(body*profile.portionPreference,0.65,1.4);
}
function isoAfterDays(days:number){const d=new Date();d.setDate(d.getDate()+Math.max(0,Math.floor(days)));return d.toLocaleDateString()}
function exactRewe(url?:string|null){try{const u=new URL(url||'');return /(^|\.)rewe\.de$/.test(u.hostname)&&u.pathname.includes('/shop/p/')}catch{return false}}

export default function AppV3(){
  const [tab,setTab]=useState<Tab>(()=>read('tab','discover'));
  const [meals,setMeals]=useState<Meal[]>([]);
  const [liked,setLiked]=useState<Meal[]>(()=>read('liked',[]));
  const [skipped,setSkipped]=useState<string[]>(()=>read('skipped',[]));
  const [mealType,setMealType]=useState<MealType>(()=>read('mealType','dinner'));
  const [filter,setFilter]=useState(()=>read('filter','all'));
  const [brain,setBrain]=useState(()=>read('brain',''));
  const [appliances,setAppliances]=useState<string[]>(()=>read('appliances',['oven','stovetop','microwave']));
  const [profile,setProfile]=useState<Profile>(()=>read('profile',{heightCm:170,weightKg:70,portionPreference:1}));
  const [dayContexts,setDayContexts]=useState<DayContext[]>(()=>read('dayContexts',Array.from({length:7},()=>({people:1,occasion:''}))));
  const [calendarView,setCalendarView]=useState<CalendarView>(()=>read('calendarView','week'));
  const [extras,setExtras]=useState<ExtraItem[]>(()=>read('extras',[]));
  const [extraKind,setExtraKind]=useState<'beverage'|'non-food'>('beverage');
  const [extraQuery,setExtraQuery]=useState('');
  const [extraResults,setExtraResults]=useState<Product[]>([]);
  const [detail,setDetail]=useState<Meal|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [basket,setBasket]=useState<BasketItem[]>(()=>read('basket',[]));
  const [summary,setSummary]=useState<any>(()=>read('summary',null));
  const [strategy,setStrategy]=useState<Strategy>(()=>read('strategy','best-value'));
  const [owned,setOwned]=useState<string[]>(()=>read('owned',[]));
  const [pantry,setPantry]=useState<any[]>([]);
  const [altItem,setAltItem]=useState<BasketItem|null>(null);
  const [alternatives,setAlternatives]=useState<Product[]>([]);

  useEffect(()=>{boot()},[]);
  useEffect(()=>save('tab',tab),[tab]);useEffect(()=>save('liked',liked),[liked]);useEffect(()=>save('skipped',skipped),[skipped]);
  useEffect(()=>save('mealType',mealType),[mealType]);useEffect(()=>save('filter',filter),[filter]);useEffect(()=>save('brain',brain),[brain]);
  useEffect(()=>save('appliances',appliances),[appliances]);useEffect(()=>save('profile',profile),[profile]);useEffect(()=>save('dayContexts',dayContexts),[dayContexts]);
  useEffect(()=>save('calendarView',calendarView),[calendarView]);useEffect(()=>save('extras',extras),[extras]);useEffect(()=>save('basket',basket),[basket]);
  useEffect(()=>save('summary',summary),[summary]);useEffect(()=>save('strategy',strategy),[strategy]);useEffect(()=>save('owned',owned),[owned]);

  async function boot(){
    try{
      const [m,p,s,ss]=await Promise.all([api('/meals?mode=random'),api('/pantry'),api('/settings'),api('/shopping/state')]);
      setMeals(m.meals||[]);setPantry(p||[]);if(s.shopping_strategy)setStrategy(s.shopping_strategy);
      const apiOwned=(ss.items||[]).filter((x:any)=>x.state==='owned').map((x:any)=>x.ingredient);if(apiOwned.length)setOwned(apiOwned);
    }catch(e:any){setError(e.message)}
  }

  const visible=useMemo(()=>{
    let list=meals.filter(m=>!liked.some(x=>x.id===m.id)&&!skipped.includes(m.id)).filter(m=>mealTypeOf(m)===mealType);
    if(filter==='quick')list=list.filter(m=>m.time<=30||m.tags?.some(t=>/quick/i.test(t)));
    else if(filter==='cheap')list=list.filter(m=>m.cost<=3||m.tags?.some(t=>/cheap/i.test(t)));
    else if(filter==='healthy')list=list.filter(m=>m.tags?.some(t=>/healthy/i.test(t)));
    else if(filter==='high-protein')list=list.filter(m=>m.tags?.some(t=>/protein/i.test(t)));
    else if(filter!=='all')list=list.filter(m=>m.cuisine?.toLowerCase().replace(/\s+/g,'-').includes(filter));
    return list;
  },[meals,liked,skipped,mealType,filter]);

  const weeklyPlan=useMemo(()=>{
    const groups:Record<MealType,Meal[]>={breakfast:[],lunch:[],dinner:[],dessert:[],snack:[]};liked.forEach(m=>groups[mealTypeOf(m)].push(m));
    return Array.from({length:7},(_,day)=>({day,slots:mealTypes.map(t=>({type:t.id,meal:groups[t.id].length?groups[t.id][day%groups[t.id].length]:null} as Slot)).filter(x=>x.meal)}));
  },[liked]);
  const factor=portionFactor(profile);
  const todayIndex=(new Date().getDay()+6)%7;
  const todaySlots=weeklyPlan[todayIndex]?.slots||[];

  const weeklyStats=useMemo(()=>{
    let cost=0,calories=0,mealCount=0;
    weeklyPlan.forEach((d,idx)=>d.slots.forEach(s=>{if(!s.meal)return;const portions=dayContexts[idx]?.people||1;cost+=s.meal.cost*factor*portions;calories+=caloriesOf(s.meal)*factor;mealCount++;}));
    const avgCalories=mealCount?Math.round(calories/7):0;
    return {cost,avgCalories,mealCount};
  },[weeklyPlan,dayContexts,factor]);

  async function generateAI(prompt:string){
    setLoading(true);setError('');
    try{
      const full=`${prompt}. Meal type: ${mealType}. Available appliances: ${appliances.join(', ')||'basic kitchen'}. User portion factor is ${factor.toFixed(2)}. Prefer the easiest method, minimal cleanup, and products likely available in the current REWE catalog.`;
      const d=await api('/ai/meals',{method:'POST',body:JSON.stringify({prompt:full})});const fresh:Meal[]=d.meals||[];
      if(!fresh.length)throw new Error('No meal ideas were generated. Check GEMINI_API_KEY in backend/.env.');
      setMeals(current=>[...fresh,...current.filter(x=>!fresh.some(n=>n.id===x.id))]);setFilter('all');
    }catch(e:any){setError(e.message)}finally{setLoading(false)}
  }
  async function react(meal:Meal,action:'like'|'skip'|'dislike'){
    if(action==='like'&&meal.is_concept){
      setLoading(true);setError('');
      try{
        const d=await api('/ai/recipe',{method:'POST',body:JSON.stringify({concept:meal,context:meal.discovery_prompt||brain})});
        const recipe:Meal=d.meal;
        if(!recipe?.id)throw new Error('Bitewise could not build the selected recipe.');
        try{await api('/events',{method:'POST',body:JSON.stringify({meal_id:recipe.id,action:'like'})})}catch{}
        setLiked(x=>x.some(a=>a.id===recipe.id)?x:[...x,recipe]);
        setSkipped(x=>[...new Set([...x,meal.id])]);
      }catch(e:any){setError(e.message)}finally{setLoading(false)}
      return;
    }
    if(!meal.is_concept){try{await api('/events',{method:'POST',body:JSON.stringify({meal_id:meal.id,action})})}catch{}}
    if(action==='like')setLiked(x=>x.some(a=>a.id===meal.id)?x:[...x,meal]);else setSkipped(x=>[...new Set([...x,meal.id])]);
  }
  function servingTotals(){
    const totals:Record<string,number>={};
    weeklyPlan.forEach((d,idx)=>d.slots.forEach(s=>{if(s.meal)totals[s.meal.id]=(totals[s.meal.id]||0)+factor*(dayContexts[idx]?.people||1)}));
    if(!Object.keys(totals).length)liked.forEach(m=>totals[m.id]=factor);
    return totals;
  }
  async function makeBasket(nextStrategy:Strategy=strategy){
    if(!liked.length)return;setLoading(true);setError('');
    try{
      const servings=servingTotals();const ids=Object.keys(servings);
      const d=await api('/shopping',{method:'POST',body:JSON.stringify({meal_ids:ids,servings,owned,mode:nextStrategy})});
      setBasket(d.items||d.basket||[]);setSummary(d);setTab('basket');
    }catch(e:any){setError(e.message)}finally{setLoading(false)}
  }
  async function changeStrategy(s:Strategy){setStrategy(s);await api('/settings',{method:'PATCH',body:JSON.stringify({shopping_strategy:s})});if(basket.length)await makeBasket(s)}
  async function toggleOwned(ingredient:string){
    const next=owned.includes(ingredient)?owned.filter(x=>x!==ingredient):[...owned,ingredient];setOwned(next);
    await api('/shopping/state',{method:'PUT',body:JSON.stringify({ingredient,state:next.includes(ingredient)?'owned':'needed'})});
    if(liked.length){const servings=servingTotals();const d=await api('/shopping',{method:'POST',body:JSON.stringify({meal_ids:Object.keys(servings),servings,owned:next,mode:strategy})});setBasket(d.items||[]);setSummary(d)}
  }
  async function openAlternatives(item:BasketItem){setAltItem(item);const d=await api(`/products/search?q=${encodeURIComponent(item.ingredient)}`);setAlternatives(d.products||[])}
  async function chooseAlternative(p:Product){if(!altItem||!p.id)return;await api('/products/replace',{method:'POST',body:JSON.stringify({ingredient:altItem.ingredient,product_id:p.id})});setAltItem(null);await makeBasket(strategy)}
  async function purchase(item:BasketItem){if(!item.product?.id)return;await api('/shopping/purchase',{method:'POST',body:JSON.stringify({product_id:item.product.id,packs:item.packs,ingredient:item.ingredient})});setBasket(x=>x.filter(i=>i.ingredient!==item.ingredient));setPantry(await api('/pantry'))}
  async function searchExtras(){if(!extraQuery.trim())return;const d=await api(`/products/search?q=${encodeURIComponent(extraQuery)}`);setExtraResults(d.products||[])}
  function addExtra(p:Product){
    const id=`${extraKind}-${p.id||p.name_original}`;if(extras.some(x=>x.id===id))return;
    setExtras(x=>[...x,{id,kind:extraKind,label:p.name_original,product:p,dailyUse:extraKind==='beverage'?1:0,onHand:0}]);
  }
  function updateDay(i:number,patch:Partial<DayContext>){setDayContexts(x=>x.map((d,idx)=>idx===i?{...d,...patch}:d))}
  function updateExtra(id:string,patch:Partial<ExtraItem>){setExtras(x=>x.map(e=>e.id===id?{...e,...patch}:e))}

  return <div className="min-h-screen bg-[#f7f4ee] text-[#17211b]">
    <header className="sticky top-0 z-40 border-b border-[#17211b]/8 bg-[#f7f4ee]/92 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1500px] items-center justify-between px-5 py-3">
        <button onClick={()=>setTab('discover')} className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-xl bg-[#18392b] text-white"><UtensilsCrossed size={17}/></span><div className="text-left"><div className="font-black">Bitewise</div><div className="text-[9px] font-bold uppercase tracking-[.22em] text-[#18392b]/45">Eat well. Think less.</div></div></button>
        <nav className="hidden gap-1 rounded-full bg-white p-1 shadow-sm xl:flex">{(['discover','picks','plan','today','basket','extras'] as Tab[]).map(t=><button key={t} onClick={()=>setTab(t)} className={cx('rounded-full px-4 py-2 text-xs font-black capitalize transition',tab===t?'bg-[#18392b] text-white':'text-[#18392b]/50 hover:bg-[#edf3ee] hover:text-[#18392b]')}>{t}{t==='picks'&&liked.length?` ${liked.length}`:''}</button>)}</nav>
        <div className="flex gap-1"><button onClick={()=>setTab('pantry')} className="rounded-full bg-white p-2.5 shadow-sm"><Home size={16}/></button><button onClick={()=>setTab('settings')} className="rounded-full bg-white p-2.5 shadow-sm"><Settings size={16}/></button></div>
      </div>
    </header>

    <main className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6">
      {error&&<div className="mb-4 rounded-2xl bg-red-50 px-4 py-3 text-sm font-bold text-red-700">{error}</div>}

      {tab==='discover'&&<>
        <div className="grid gap-3 rounded-[26px] bg-[#18392b] p-5 text-white lg:grid-cols-[1fr_auto] lg:items-center"><div><div className="text-xs font-black uppercase tracking-[.18em] text-white/45">AI food decision engine</div><h1 className="mt-1 text-2xl font-black">What do you feel like eating?</h1><p className="mt-1 text-sm text-white/55">Browse lightweight ideas first. Bitewise creates the full recipe only when you pick one.</p></div><div className="text-right"><div className="text-xs text-white/40">Adaptive portion</div><div className="text-xl font-black">{factor.toFixed(2)}×</div></div></div>
        <div className="mt-4 flex gap-2 overflow-x-auto pb-1">{mealTypes.map(t=><button key={t.id} onClick={()=>setMealType(t.id)} className={cx('shrink-0 rounded-full px-4 py-2 text-sm font-black',mealType===t.id?'bg-[#dff2df] text-[#173b2d]':'bg-white text-[#173b2d]/55')}>{t.emoji} {t.label}</button>)}</div>
        <div className="mt-3 flex flex-col gap-2 rounded-2xl bg-white p-3 shadow-sm sm:flex-row"><input value={brain} onChange={e=>setBrain(e.target.value)} onKeyDown={e=>e.key==='Enter'&&brain.trim()&&generateAI(brain)} className="min-w-0 flex-1 rounded-xl bg-[#f3f1eb] px-4 py-3 text-sm outline-none" placeholder="Fancy but easy tonight · cheap breakfast · use what I have..."/><button onClick={()=>brain.trim()&&generateAI(brain)} className="rounded-xl bg-[#18392b] px-5 py-3 text-sm font-black text-white">{loading?'Thinking…':'Generate'}</button></div>
        <div className="mt-4 flex gap-2 overflow-x-auto pb-1">{cuisines.map(c=><button key={c} onClick={()=>setFilter(c)} className={cx('shrink-0 rounded-full border px-3 py-1.5 text-xs font-black capitalize',filter===c?'border-[#18392b] bg-[#18392b] text-white':'border-[#18392b]/10 bg-white text-[#18392b]/55')}>{c.replace('-',' ')}</button>)}</div>
        {!visible.length?<div className="mt-5 rounded-[28px] bg-white p-10 text-center"><ChefHat className="mx-auto text-[#18392b]/20"/><div className="mt-3 font-black">No exact matches yet</div><button onClick={()=>generateAI(`${filter==='all'?'varied':filter} ${mealType} ideas`)} className="mt-4 rounded-full bg-[#18392b] px-5 py-2.5 text-sm font-black text-white">Generate matching meals</button></div>:<div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{visible.map(m=><MealCard key={m.id} meal={m} appliances={appliances} open={()=>!m.is_concept&&setDetail(m)} like={()=>react(m,'like')} skip={()=>react(m,'skip')}/>)}</div>}
      </>}

      {tab==='picks'&&<><Title title="Your picks" sub="Only selected ideas become full recipes. Portions adapt to your profile and each day's guest count."/><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{liked.map(m=><MealCard key={m.id} meal={m} appliances={appliances} open={()=>setDetail(m)} like={()=>setLiked(x=>x.filter(a=>a.id!==m.id))} skip={()=>setLiked(x=>x.filter(a=>a.id!==m.id))} picked/>)}</div>{liked.length>0&&<button onClick={()=>makeBasket()} className="mt-6 rounded-2xl bg-[#18392b] px-5 py-3 text-sm font-black text-white"><ShoppingBasket size={15} className="mr-2 inline"/>Build adaptive weekly basket</button>}</>}

      {tab==='plan'&&<><div className="flex flex-wrap items-end justify-between gap-3"><Title title="Calendar" sub="Week, month and year views are projected from your current recurring meal plan."/><div className="flex rounded-full bg-white p-1 shadow-sm">{(['week','month','year'] as CalendarView[]).map(v=><button key={v} onClick={()=>setCalendarView(v)} className={cx('rounded-full px-4 py-2 text-xs font-black capitalize',calendarView===v?'bg-[#18392b] text-white':'text-[#18392b]/45')}>{v}</button>)}</div></div><Stats cost={weeklyStats.cost} calories={weeklyStats.avgCalories} count={weeklyStats.mealCount}/>{calendarView==='week'?<div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">{weeklyPlan.map((d,i)=><DayCard key={i} day={d} index={i} context={dayContexts[i]} update={p=>updateDay(i,p)} appliances={appliances} open={setDetail}/>)}</div>:calendarView==='month'?<MonthView weekly={weeklyStats}/>:<YearView weekly={weeklyStats}/>}</>}

      {tab==='today'&&<><Title title="Today" sub={`${dayContexts[todayIndex]?.people||1} person${(dayContexts[todayIndex]?.people||1)>1?'s':''}${dayContexts[todayIndex]?.occasion?` · ${dayContexts[todayIndex].occasion}`:''}`}/><div className="mt-5 space-y-4">{todaySlots.length?todaySlots.map(s=><div key={s.type} className="grid overflow-hidden rounded-[26px] bg-white shadow-sm md:grid-cols-[280px_1fr]">{s.meal?.image&&<img src={s.meal.image} className="h-56 w-full object-cover md:h-full"/>}<div className="p-6"><div className="text-xs font-black uppercase tracking-[.16em] text-[#18392b]/35">{s.type}</div><div className="mt-1 text-2xl font-black">{s.meal?.name}</div><div className="mt-2 text-sm text-[#18392b]/45">≈ {Math.round(caloriesOf(s.meal!)*factor)} kcal for your portion · {s.meal?.time} min</div><RecipeSteps meal={s.meal!} appliances={appliances}/></div></div>):<Empty text="No meals planned for today yet."/>}</div></>}

      {tab==='basket'&&<><Title title="Adaptive basket" sub="Quantities use your portion estimate plus each day's guest count."/><div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{strategies.map(s=><button key={s.id} onClick={()=>changeStrategy(s.id)} className={cx('rounded-2xl border p-3 text-left text-sm font-black',strategy===s.id?'border-[#18392b] bg-[#18392b] text-white':'border-[#18392b]/10 bg-white')}>{s.icon} {s.label}</button>)}</div>{basket.length?<div className="mt-5 grid gap-5 xl:grid-cols-[1fr_320px]"><div className="space-y-3">{basket.map(item=><div key={item.ingredient} className="rounded-[22px] bg-white p-4 shadow-sm"><div className="flex items-start gap-3"><button onClick={()=>toggleOwned(item.ingredient)} className={cx('grid h-7 w-7 shrink-0 place-items-center rounded-lg border',owned.includes(item.ingredient)?'bg-[#18392b] text-white':'border-[#18392b]/15')}>{owned.includes(item.ingredient)&&<Check size={13}/>}</button><div className="min-w-0 flex-1"><div className="font-black capitalize">{item.ingredient}</div><div className="text-xs text-[#18392b]/40">Need {item.needed_quantity??item.quantity} {item.unit}{item.pantry_used?` · pantry ${item.pantry_used} ${item.unit}`:''}</div>{item.product?<div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-[#f5f4ef] p-3"><div><div className="text-sm font-black">{item.product.name_original}</div><div className="text-xs text-[#18392b]/40">{item.packs} pack(s) · {money(item.total)}</div></div><div className="flex gap-2"><button onClick={()=>openAlternatives(item)} className="rounded-lg bg-white px-3 py-2 text-xs font-black">Alternatives</button>{exactRewe(item.product.product_url)&&<a href={item.product.product_url!} target="_blank" rel="noreferrer" className="rounded-lg bg-white p-2"><ExternalLink size={14}/></a>}<button onClick={()=>purchase(item)} className="rounded-lg bg-[#18392b] px-3 py-2 text-xs font-black text-white"><PackageCheck size={13} className="mr-1 inline"/>Bought</button></div></div>:<div className="mt-2 text-xs font-bold text-amber-700">Covered by pantry / no compatible product.</div>}</div></div></div>)}</div><aside className="h-fit rounded-[24px] bg-[#18392b] p-5 text-white"><div className="text-xs uppercase tracking-[.16em] text-white/40">Food estimate</div><div className="mt-2 text-4xl font-black">{money(summary?.total)}</div><div className="mt-5 text-sm text-white/60">Extras and beverages stay separate so you can see food vs household spend.</div><button onClick={()=>setTab('extras')} className="mt-4 w-full rounded-xl bg-white px-4 py-3 text-sm font-black text-[#18392b]">Open drinks & extras</button></aside></div>:<Empty text="Build the basket from your picks first."/>}</>}

      {tab==='extras'&&<><Title title="Drinks & extras" sub="Beverages and household items stay outside the meal planner but inside your shopping view."/><div className="mt-4 flex gap-2"><button onClick={()=>setExtraKind('beverage')} className={cx('rounded-full px-4 py-2 text-sm font-black',extraKind==='beverage'?'bg-[#18392b] text-white':'bg-white')}>🥤 Beverages</button><button onClick={()=>setExtraKind('non-food')} className={cx('rounded-full px-4 py-2 text-sm font-black',extraKind==='non-food'?'bg-[#18392b] text-white':'bg-white')}>🧻 Non-food</button></div><div className="mt-3 flex gap-2 rounded-2xl bg-white p-3"><input value={extraQuery} onChange={e=>setExtraQuery(e.target.value)} onKeyDown={e=>e.key==='Enter'&&searchExtras()} placeholder={extraKind==='beverage'?'Coca-Cola, water, coffee...':'toilet paper, detergent...'} className="min-w-0 flex-1 rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm outline-none"/><button onClick={searchExtras} className="rounded-xl bg-[#18392b] px-4 text-white"><Search size={16}/></button></div>{extraResults.length>0&&<div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{extraResults.slice(0,12).map(p=><button key={p.id||p.name_original} onClick={()=>addExtra(p)} className="rounded-2xl bg-white p-4 text-left shadow-sm hover:-translate-y-0.5"><div className="font-black">{p.name_original}</div><div className="mt-1 text-xs text-[#18392b]/40">{p.brand||'REWE'} · {money(p.price)}</div></button>)}</div>}<div className="mt-5 grid gap-3 lg:grid-cols-2">{extras.map(e=>{const days=e.dailyUse>0?e.onHand/e.dailyUse:Infinity;return <div key={e.id} className="rounded-[22px] bg-white p-5 shadow-sm"><div className="flex justify-between gap-3"><div><div className="text-xs font-black uppercase text-[#18392b]/35">{e.kind==='beverage'?'Beverage':'Non-food'}</div><div className="font-black">{e.label}</div><div className="mt-1 text-xs text-[#18392b]/45">{e.product?money(e.product.price):''}{Number.isFinite(days)?` · stock until ~${isoAfterDays(days)}`:''}</div></div><button onClick={()=>setExtras(x=>x.filter(a=>a.id!==e.id))}><X size={15}/></button></div><div className="mt-4 grid grid-cols-2 gap-2"><label className="text-xs font-bold text-[#18392b]/50">On hand<input type="number" min="0" value={e.onHand} onChange={ev=>updateExtra(e.id,{onHand:Number(ev.target.value)})} className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2 text-sm text-[#18392b]"/></label><label className="text-xs font-bold text-[#18392b]/50">Use / day<input type="number" min="0" step="0.25" value={e.dailyUse} onChange={ev=>updateExtra(e.id,{dailyUse:Number(ev.target.value)})} className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2 text-sm text-[#18392b]"/></label></div>{e.product&&exactRewe(e.product.product_url)&&<a href={e.product.product_url!} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs font-black underline">Open product <ExternalLink size={12}/></a>}</div>})}</div></>}

      {tab==='pantry'&&<><Title title="Pantry" sub="Current food inventory from purchases and manual adjustments."/><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{pantry.map((p:any)=><div key={p.id} className="rounded-2xl bg-white p-4 shadow-sm"><div className="font-black capitalize">{p.ingredient}</div><div className="mt-2 text-2xl font-black">{Number(p.quantity).toFixed(1)} <span className="text-sm text-[#18392b]/40">{p.unit}</span></div></div>)}</div></>}

      {tab==='settings'&&<><Title title="Your profile" sub="Used only to estimate practical portion sizes. This is not medical or nutrition advice."/><div className="mt-5 grid gap-5 lg:grid-cols-2"><div className="rounded-[24px] bg-white p-5 shadow-sm"><div className="font-black">Portion sizing</div><div className="mt-4 grid grid-cols-2 gap-3"><label className="text-xs font-bold text-[#18392b]/50">Height (cm)<input type="number" value={profile.heightCm} onChange={e=>setProfile({...profile,heightCm:Number(e.target.value)})} className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm text-[#18392b]"/></label><label className="text-xs font-bold text-[#18392b]/50">Weight (kg)<input type="number" value={profile.weightKg} onChange={e=>setProfile({...profile,weightKg:Number(e.target.value)})} className="mt-1 w-full rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm text-[#18392b]"/></label></div><div className="mt-4 text-sm text-[#18392b]/50">Estimated portion multiplier: <b className="text-[#18392b]">{factor.toFixed(2)}×</b></div><div className="mt-4"><div className="text-xs font-bold text-[#18392b]/50">Appetite preference</div><div className="mt-2 flex gap-2">{[{v:.85,l:'Smaller'},{v:1,l:'Standard'},{v:1.15,l:'Larger'}].map(x=><button key={x.l} onClick={()=>setProfile({...profile,portionPreference:x.v})} className={cx('rounded-full px-3 py-2 text-xs font-black',profile.portionPreference===x.v?'bg-[#18392b] text-white':'bg-[#f3f1eb]')}>{x.l}</button>)}</div></div></div><div className="rounded-[24px] bg-white p-5 shadow-sm"><div className="font-black">Kitchen equipment</div><p className="mt-1 text-sm text-[#18392b]/45">Recipes prefer your fastest, lowest-effort method.</p><div className="mt-4 grid grid-cols-2 gap-2">{applianceOptions.map(a=><button key={a.id} onClick={()=>setAppliances(x=>x.includes(a.id)?x.filter(v=>v!==a.id):[...x,a.id])} className={cx('flex items-center gap-2 rounded-xl border p-3 text-sm font-black',appliances.includes(a.id)?'border-[#18392b] bg-[#dff2df]':'border-[#18392b]/10')}>{a.icon}{a.label}{appliances.includes(a.id)&&<Check size={13} className="ml-auto"/>}</button>)}</div></div></div></>}
    </main>

    {detail&&<div className="fixed inset-0 z-50 overflow-y-auto bg-black/55 p-4" onClick={()=>setDetail(null)}><div className="mx-auto mt-8 max-w-3xl overflow-hidden rounded-[30px] bg-white shadow-2xl" onClick={e=>e.stopPropagation()}>{detail.image&&<img src={detail.image} className="h-64 w-full object-cover"/>}<div className="p-6"><div className="flex justify-between gap-4"><div><div className="text-xs font-black uppercase text-[#18392b]/35">{mealTypeOf(detail)} · ≈ {Math.round(caloriesOf(detail)*factor)} kcal your portion</div><h2 className="mt-1 text-3xl font-black">{detail.name}</h2></div><button onClick={()=>setDetail(null)}><X/></button></div><RecipeSteps meal={detail} appliances={appliances}/><div className="mt-5"><div className="text-xs font-black uppercase text-[#18392b]/35">Ingredients</div><div className="mt-2 flex flex-wrap gap-2">{(detail.ingredients||[]).map(([n,q,u])=><span key={n} className="rounded-full bg-[#f3f1eb] px-3 py-1.5 text-xs font-bold">{n} · {Math.round(q*factor*100)/100} {u}</span>)}</div></div></div></div></div>}

    {altItem&&<div className="fixed inset-0 z-50 overflow-y-auto bg-black/55 p-4"><div className="mx-auto mt-10 max-w-2xl rounded-[28px] bg-white p-5"><div className="flex justify-between"><div><div className="text-xs uppercase text-[#18392b]/35">{altItem.ingredient}</div><div className="text-2xl font-black">Choose another product</div></div><button onClick={()=>setAltItem(null)}><X/></button></div><div className="mt-4 max-h-[65vh] space-y-2 overflow-auto">{alternatives.map(p=><button key={p.id||p.name_original} onClick={()=>chooseAlternative(p)} className="flex w-full items-center justify-between gap-3 rounded-xl bg-[#f5f4ef] p-3 text-left"><div><div className="text-sm font-black">{p.name_original}</div><div className="text-xs text-[#18392b]/40">{p.brand||'REWE'} · {p.package_size} {p.package_unit}</div></div><b>{money(p.price)}</b></button>)}</div></div></div>}
  </div>;
}

function MealCard({meal,appliances,open,like,skip,picked=false}:{meal:Meal;appliances:string[];open:()=>void;like:()=>void;skip:()=>void;picked?:boolean}){
  return <article className="group overflow-hidden rounded-[24px] bg-white shadow-sm transition hover:-translate-y-1 hover:shadow-xl"><button onClick={open} className="block w-full text-left"><div className="aspect-[4/3] overflow-hidden bg-[#e8e5dc]">{meal.image&&<img src={meal.image} className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.04]"/>}</div><div className="p-4"><div className="flex items-start justify-between gap-2"><h3 className="font-black leading-tight">{meal.name}</h3><span className="shrink-0 rounded-full bg-[#dff2df] px-2 py-1 text-[10px] font-black">≈{caloriesOf(meal)} kcal</span></div><div className="mt-2 text-xs text-[#18392b]/45">{meal.time} min · {meal.cuisine} · {money(meal.cost)}</div>{meal.is_concept&&<div className="mt-2 text-[10px] font-black uppercase tracking-[.12em] text-[#18392b]/35">Recipe generated only if you pick it</div>}</div></button><div className="flex gap-2 px-4 pb-4"><button onClick={skip} className="rounded-xl border border-[#18392b]/10 p-2"><X size={14}/></button><button onClick={like} className="flex-1 rounded-xl bg-[#18392b] px-3 py-2 text-xs font-black text-white">{picked?'Remove':'♥ I’d eat this'}</button></div></article>
}
function RecipeSteps({meal,appliances}:{meal:Meal;appliances:string[]}){const steps=meal.steps?.length?meal.steps:fallbackSteps(meal,appliances);return <div className="mt-5"><div className="text-xs font-black uppercase tracking-[.16em] text-[#18392b]/35">Fastest way</div><div className="mt-3 space-y-2">{steps.map((s,i)=><div key={i} className="flex gap-3 rounded-xl bg-[#f7f5ef] p-3"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#18392b] text-[10px] font-black text-white">{i+1}</span><div className="text-sm"><b>{s.text}</b>{s.minutes?<span className="ml-2 text-xs text-[#18392b]/40">~{s.minutes} min</span>:null}</div></div>)}</div></div>}
function DayCard({day,index,context,update,appliances,open}:{day:{day:number;slots:Slot[]};index:number;context:DayContext;update:(p:Partial<DayContext>)=>void;appliances:string[];open:(m:Meal)=>void}){
  return <div className="rounded-[22px] bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><div className="text-xs font-black uppercase text-[#18392b]/35">Day {index+1}</div><div className="font-black">{dayNames[index]}</div></div><CalendarDays size={16} className="text-[#18392b]/25"/></div><div className="mt-3 grid grid-cols-[100px_1fr] gap-2"><label className="text-[10px] font-bold text-[#18392b]/40">People<input type="number" min="1" max="12" value={context.people} onChange={e=>update({people:Math.max(1,Number(e.target.value))})} className="mt-1 w-full rounded-lg bg-[#f3f1eb] px-2 py-2 text-sm text-[#18392b]"/></label><label className="text-[10px] font-bold text-[#18392b]/40">Context<input value={context.occasion} onChange={e=>update({occasion:e.target.value})} placeholder="Dinner party…" className="mt-1 w-full rounded-lg bg-[#f3f1eb] px-2 py-2 text-sm text-[#18392b]"/></label></div><div className="mt-3 space-y-2">{day.slots.map(s=><button key={s.type} onClick={()=>s.meal&&open(s.meal)} className="flex w-full gap-2 rounded-xl bg-[#f7f5ef] p-2 text-left hover:bg-[#edf3ee]">{s.meal?.image&&<img src={s.meal.image} className="h-12 w-14 rounded-lg object-cover"/>}<div className="min-w-0"><div className="text-[9px] font-black uppercase text-[#18392b]/35">{s.type}</div><div className="truncate text-xs font-black">{s.meal?.name}</div></div></button>)}{!day.slots.length&&<div className="py-4 text-xs text-[#18392b]/35">No meals selected.</div>}</div></div>
}
function Stats({cost,calories,count}:{cost:number;calories:number;count:number}){return <div className="mt-5 grid gap-3 sm:grid-cols-3"><Stat label="Projected weekly food" value={money(cost)}/><Stat label="Avg kcal / day" value={calories}/><Stat label="Planned meals" value={count}/></div>}
function MonthView({weekly}:{weekly:{cost:number;avgCalories:number;mealCount:number}}){return <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Array.from({length:4},(_,i)=><div key={i} className="rounded-[22px] bg-white p-5 shadow-sm"><div className="text-xs font-black uppercase text-[#18392b]/35">Week {i+1}</div><div className="mt-2 text-2xl font-black">{money(weekly.cost)}</div><div className="mt-1 text-sm text-[#18392b]/45">≈ {weekly.avgCalories} kcal/day · {weekly.mealCount} meals</div></div>)}</div>}
function YearView({weekly}:{weekly:{cost:number;avgCalories:number;mealCount:number}}){return <div className="mt-5 grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].map(m=><div key={m} className="rounded-[22px] bg-white p-5 shadow-sm"><div className="font-black">{m}</div><div className="mt-2 text-xl font-black">{money(weekly.cost*4.345)}</div><div className="text-xs text-[#18392b]/45">projected food · ≈ {weekly.avgCalories} kcal/day</div></div>)}</div>}
function Title({title,sub}:{title:string;sub:string}){return <div><div className="text-xs font-black uppercase tracking-[.17em] text-[#18392b]/35">Bitewise</div><h1 className="mt-1 text-3xl font-black">{title}</h1><p className="mt-1 text-sm text-[#18392b]/45">{sub}</p></div>}
function Stat({label,value}:{label:string;value:any}){return <div className="rounded-[20px] bg-white p-4 shadow-sm"><div className="text-[10px] font-black uppercase tracking-[.14em] text-[#18392b]/35">{label}</div><div className="mt-1 text-2xl font-black">{String(value)}</div></div>}
function Empty({text}:{text:string}){return <div className="mt-5 rounded-[24px] border border-dashed border-[#18392b]/15 bg-white p-10 text-center text-sm font-bold text-[#18392b]/35">{text}</div>}
