import React, { useEffect, useMemo, useState } from 'react';
import {
  AirVent,
  ArrowRight,
  CalendarDays,
  Check,
  ChefHat,
  Clock3,
  Flame,
  Heart,
  Home,
  Microwave,
  Minus,
  PackageCheck,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShoppingBasket,
  Sparkles,
  UtensilsCrossed,
  X,
  Zap,
} from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const K = 'bitewise.v2.';

type MealType = 'breakfast' | 'lunch' | 'dinner' | 'dessert' | 'snack';
type Meal = {
  id: string; name: string; description: string; time: number; difficulty: string; cost: number;
  cuisine: string; tags: string[]; ingredients: [string, number, string][]; image: string;
  calories?: number; meal_type?: MealType; steps?: {text:string; minutes?:number|null}[];
};
type Product = { id:number|null; name_original:string; brand?:string|null; package_size:number; package_unit:string; price:number|null; product_url?:string|null };
type BasketItem = { ingredient:string; quantity:number; needed_quantity?:number; unit:string; product:Product|null; packs:number; total:number; pantry_used?:number; badge?:string };
type Strategy = 'maximum-savings'|'best-value'|'plan-efficiency'|'premium';
type Tab = 'discover'|'picks'|'plan'|'today'|'basket'|'pantry'|'settings';

const mealTypes: {id:MealType; label:string; emoji:string}[] = [
  {id:'breakfast',label:'Breakfast',emoji:'☕'}, {id:'lunch',label:'Lunch',emoji:'🥗'},
  {id:'dinner',label:'Dinner',emoji:'🍝'}, {id:'dessert',label:'Desserts',emoji:'🍰'}, {id:'snack',label:'Snacks',emoji:'🍓'},
];
const cuisines = ['all','quick','cheap','healthy','high-protein','asian','mexican','italian','mediterranean','latin-american','german'];
const strategies: {id:Strategy; label:string; icon:string}[] = [
  {id:'maximum-savings',label:'Maximum savings',icon:'💰'}, {id:'best-value',label:'Best value',icon:'⭐'},
  {id:'plan-efficiency',label:'Plan efficiency',icon:'🔥'}, {id:'premium',label:'Premium',icon:'✨'},
];
const applianceOptions = [
  {id:'air fryer',label:'Air fryer',icon:<AirVent size={16}/>}, {id:'microwave',label:'Microwave',icon:<Microwave size={16}/>},
  {id:'oven',label:'Oven',icon:<Flame size={16}/>}, {id:'stovetop',label:'Stovetop',icon:<ChefHat size={16}/>},
];

async function api(path:string, options?:RequestInit) {
  const r = await fetch(API+path,{headers:{'Content-Type':'application/json',...(options?.headers||{})},...options});
  if(!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
  return r.json();
}
function read<T>(key:string,fallback:T):T { try { const v=localStorage.getItem(K+key); return v?JSON.parse(v):fallback; } catch{return fallback;} }
function save(key:string,value:unknown){ try{localStorage.setItem(K+key,JSON.stringify(value));}catch{} }
function money(v?:number|null){return `€${Number(v||0).toFixed(2)}`}
function cx(...xs:(string|false|undefined|null)[]){return xs.filter(Boolean).join(' ')}

function mealTypeOf(m:Meal):MealType {
  if(m.meal_type) return m.meal_type;
  const s=`${m.name} ${m.description} ${(m.tags||[]).join(' ')}`.toLowerCase();
  if(/breakfast|oat|pancake|toast|granola|omelette|yogurt/.test(s)) return 'breakfast';
  if(/dessert|cake|cookie|brownie|tiramisu|pudding|sweet/.test(s)) return 'dessert';
  if(/snack|smoothie|bite|bar/.test(s)) return 'snack';
  if(/lunch|salad|sandwich|wrap/.test(s)) return 'lunch';
  return 'dinner';
}
function caloriesOf(m:Meal){
  if(m.calories) return m.calories;
  const protein=(m.ingredients||[]).some(x=>/chicken|beef|salmon|fish|pancetta/.test(x[0]))?170:0;
  const carb=(m.ingredients||[]).some(x=>/pasta|rice|potato|bread|tortilla/.test(x[0]))?230:100;
  return Math.min(950,Math.round(180+protein+carb+(m.cost||2)*25));
}
function fallbackSteps(m:Meal, appliances:string[]){
  const names=(m.ingredients||[]).map(x=>x[0]);
  const steps:{text:string;minutes?:number}[]=[];
  const hasPasta=names.some(x=>x.includes('pasta'));
  const hasRice=names.some(x=>x==='rice');
  if(hasPasta) steps.push({text:'Boil salted water. Add pasta and cook until tender.',minutes:10});
  if(hasRice) steps.push({text:'Cook rice with 2 parts water to 1 part rice.',minutes:12});
  if(appliances.includes('air fryer') && names.some(x=>/chicken|potato|salmon|vegetable/.test(x))) steps.push({text:'Put the main protein/vegetables in the air fryer at 190°C. Shake once halfway.',minutes:12});
  else if(appliances.includes('oven') && names.some(x=>/chicken|potato|salmon|vegetable/.test(x))) steps.push({text:'Put the main ingredients on one tray and roast at 210°C.',minutes:20});
  else steps.push({text:'Heat one pan, add the main ingredients and cook until done.',minutes:10});
  steps.push({text:'Add sauce/seasoning, combine everything and taste.',minutes:3});
  steps.push({text:'Plate it. Done — no extra steps unless you want garnish.',minutes:1});
  return steps;
}

export default function AppV2(){
  const [tab,setTab]=useState<Tab>(()=>read('tab','discover'));
  const [meals,setMeals]=useState<Meal[]>([]);
  const [liked,setLiked]=useState<Meal[]>(()=>read('liked',[]));
  const [skipped,setSkipped]=useState<string[]>(()=>read('skipped',[]));
  const [mealType,setMealType]=useState<MealType>(()=>read('mealType','dinner'));
  const [filter,setFilter]=useState(()=>read('filter','all'));
  const [brain,setBrain]=useState(()=>read('brain',''));
  const [appliances,setAppliances]=useState<string[]>(()=>read('appliances',['oven','stovetop','microwave']));
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
  const [altSearch,setAltSearch]=useState('');

  useEffect(()=>{boot()},[]);
  useEffect(()=>save('tab',tab),[tab]); useEffect(()=>save('liked',liked),[liked]); useEffect(()=>save('skipped',skipped),[skipped]);
  useEffect(()=>save('mealType',mealType),[mealType]); useEffect(()=>save('filter',filter),[filter]); useEffect(()=>save('brain',brain),[brain]);
  useEffect(()=>save('appliances',appliances),[appliances]); useEffect(()=>save('basket',basket),[basket]); useEffect(()=>save('summary',summary),[summary]);
  useEffect(()=>save('strategy',strategy),[strategy]); useEffect(()=>save('owned',owned),[owned]);

  async function boot(){
    try{
      const [m,p,s]=await Promise.all([api('/meals?mode=random'),api('/pantry'),api('/settings')]);
      setMeals(m.meals||[]); setPantry(p||[]); if(s.shopping_strategy)setStrategy(s.shopping_strategy);
      const ss=await api('/shopping/state'); setOwned((ss.items||[]).filter((x:any)=>x.state==='owned').map((x:any)=>x.ingredient));
    }catch(e:any){setError(e.message)}
  }

  const visible=useMemo(()=>{
    let list=meals.filter(m=>!liked.some(x=>x.id===m.id)&&!skipped.includes(m.id));
    list=list.filter(m=>mealTypeOf(m)===mealType);
    if(filter==='quick') list=list.filter(m=>m.time<=30 || m.tags?.some(t=>/quick/i.test(t)));
    else if(filter==='cheap') list=list.filter(m=>m.cost<=3 || m.tags?.some(t=>/cheap/i.test(t)));
    else if(filter==='healthy') list=list.filter(m=>m.tags?.some(t=>/healthy/i.test(t)));
    else if(filter==='high-protein') list=list.filter(m=>m.tags?.some(t=>/protein/i.test(t)));
    else if(filter!=='all') list=list.filter(m=>m.cuisine?.toLowerCase().replace(/\s+/g,'-').includes(filter));
    return list;
  },[meals,liked,skipped,mealType,filter]);

  async function generateAI(prompt:string){
    setLoading(true);setError('');
    try{
      const full=`${prompt}. Meal type: ${mealType}. Available appliances: ${appliances.join(', ') || 'basic kitchen'}. Prioritize the easiest method and minimum cleanup.`;
      const d=await api('/ai/meals',{method:'POST',body:JSON.stringify({prompt:full})});
      const fresh:Meal[]=d.meals||[];
      if(!fresh.length) throw new Error('No AI meals were generated. Check GEMINI_API_KEY in backend/.env.');
      setMeals(current=>[...fresh,...current.filter(x=>!fresh.some(n=>n.id===x.id))]);
      setFilter('all');
    }catch(e:any){setError(e.message)}finally{setLoading(false)}
  }
  async function applyBrain(){ if(brain.trim()) await generateAI(brain.trim()); }
  async function strictFilter(next:string){
    setFilter(next);
    setTimeout(()=>{},0);
  }
  async function react(meal:Meal,action:'like'|'skip'|'dislike'){
    try{await api('/events',{method:'POST',body:JSON.stringify({meal_id:meal.id,action})});}catch{}
    if(action==='like') setLiked(x=>x.some(a=>a.id===meal.id)?x:[...x,meal]); else setSkipped(x=>[...new Set([...x,meal.id])]);
  }

  async function makeBasket(nextStrategy:Strategy=strategy){
    if(!liked.length)return;
    setLoading(true);setError('');
    try{
      const servings=Object.fromEntries(liked.map(m=>[m.id,2]));
      const d=await api('/shopping',{method:'POST',body:JSON.stringify({meal_ids:liked.map(m=>m.id),servings,owned,mode:nextStrategy})});
      setBasket(d.items||d.basket||[]);setSummary(d);setTab('basket');
    }catch(e:any){setError(e.message)}finally{setLoading(false)}
  }
  async function changeStrategy(s:Strategy){setStrategy(s);await api('/settings',{method:'PATCH',body:JSON.stringify({shopping_strategy:s})}); if(basket.length)await makeBasket(s)}
  async function toggleOwned(ingredient:string){
    const next=owned.includes(ingredient)?owned.filter(x=>x!==ingredient):[...owned,ingredient]; setOwned(next);
    await api('/shopping/state',{method:'PUT',body:JSON.stringify({ingredient,state:next.includes(ingredient)?'owned':'needed'})});
    if(liked.length){
      const servings=Object.fromEntries(liked.map(m=>[m.id,2]));
      const d=await api('/shopping',{method:'POST',body:JSON.stringify({meal_ids:liked.map(m=>m.id),servings,owned:next,mode:strategy})});
      setBasket(d.items||[]);setSummary(d);
    }
  }
  async function openAlternatives(item:BasketItem){
    setAltItem(item);setAltSearch(item.ingredient);
    const d=await api(`/products/search?q=${encodeURIComponent(item.ingredient)}`); setAlternatives(d.products||[]);
  }
  async function searchAlternatives(){if(!altSearch.trim())return; const d=await api(`/products/search?q=${encodeURIComponent(altSearch)}`);setAlternatives(d.products||[])}
  async function chooseAlternative(p:Product){if(!altItem||!p.id)return;await api('/products/replace',{method:'POST',body:JSON.stringify({ingredient:altItem.ingredient,product_id:p.id})});setAltItem(null);await makeBasket(strategy)}
  async function purchase(item:BasketItem){if(!item.product?.id)return;await api('/shopping/purchase',{method:'POST',body:JSON.stringify({product_id:item.product.id,packs:item.packs,ingredient:item.ingredient})});setBasket(x=>x.filter(i=>i.ingredient!==item.ingredient));const p=await api('/pantry');setPantry(p||[])}

  const week=useMemo(()=>{
    const groups:Record<MealType,Meal[]>={breakfast:[],lunch:[],dinner:[],dessert:[],snack:[]}; liked.forEach(m=>groups[mealTypeOf(m)].push(m));
    return Array.from({length:7},(_,day)=>({day,slots:mealTypes.map(t=>({type:t.id,meal:groups[t.id].length?groups[t.id][day%groups[t.id].length]:null})).filter(x=>x.meal)}));
  },[liked]);

  const todaySlots=week[new Date().getDay()%7]?.slots||[];

  return <div className="min-h-screen bg-[#f7f4ee] text-[#17211b]">
    <header className="sticky top-0 z-40 border-b border-[#17211b]/8 bg-[#f7f4ee]/92 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1500px] items-center justify-between px-5 py-3">
        <button onClick={()=>setTab('discover')} className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-xl bg-[#18392b] text-white"><UtensilsCrossed size={17}/></span><div className="text-left"><div className="font-black">Bitewise</div><div className="text-[9px] font-bold uppercase tracking-[.22em] text-[#18392b]/45">Eat well. Think less.</div></div></button>
        <nav className="hidden gap-1 rounded-full bg-white p-1 shadow-sm lg:flex">{(['discover','picks','plan','today','basket'] as Tab[]).map(t=><button key={t} onClick={()=>setTab(t)} className={cx('rounded-full px-4 py-2 text-xs font-black capitalize transition',tab===t?'bg-[#18392b] text-white':'text-[#18392b]/50 hover:bg-[#edf3ee] hover:text-[#18392b]')}>{t}{t==='picks'&&liked.length?` ${liked.length}`:''}</button>)}</nav>
        <div className="flex gap-1"><button onClick={()=>setTab('pantry')} className="rounded-full bg-white p-2.5 shadow-sm hover:-translate-y-0.5"><Home size={16}/></button><button onClick={()=>setTab('settings')} className="rounded-full bg-white p-2.5 shadow-sm hover:-translate-y-0.5"><Settings size={16}/></button></div>
      </div>
    </header>

    <main className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6">
      {error&&<div className="mb-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-bold text-red-700">{error}</div>}

      {tab==='discover'&&<section>
        <div className="flex flex-col gap-4 rounded-[26px] bg-gradient-to-r from-[#18392b] via-[#23543d] to-[#4f6f58] p-5 text-white shadow-xl shadow-[#18392b]/10 sm:flex-row sm:items-center sm:justify-between">
          <div><div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[.2em] text-white/55"><Sparkles size={13}/> AI food decision engine</div><h1 className="mt-1 text-2xl font-black sm:text-3xl">Pick what looks good. We optimize the rest.</h1></div>
          <div className="flex min-w-0 flex-1 gap-2 sm:max-w-xl"><input value={brain} onChange={e=>setBrain(e.target.value)} onKeyDown={e=>e.key==='Enter'&&applyBrain()} placeholder="Fancy but easy tonight · cheap Mexican · dessert under €3..." className="min-w-0 flex-1 rounded-xl bg-white/12 px-4 py-3 text-sm text-white outline-none placeholder:text-white/45 focus:bg-white/18"/><button onClick={applyBrain} disabled={loading} className="rounded-xl bg-white px-4 py-3 text-xs font-black text-[#18392b]">{loading?<RefreshCw size={15} className="animate-spin"/>:'Apply'}</button></div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">{mealTypes.map(t=><button key={t.id} onClick={()=>{setMealType(t.id);setFilter('all')}} className={cx('rounded-full px-4 py-2 text-xs font-black transition',mealType===t.id?'bg-[#d9efdd] text-[#18392b] ring-1 ring-[#18392b]/10':'bg-white text-[#18392b]/50 hover:bg-[#edf3ee]')}>{t.emoji} {t.label}</button>)}</div>
        <div className="mt-3 flex gap-2 overflow-x-auto pb-2">{cuisines.map(c=><button key={c} onClick={()=>strictFilter(c)} className={cx('shrink-0 rounded-full border px-3.5 py-2 text-xs font-bold capitalize transition',filter===c?'border-[#18392b] bg-[#18392b] text-white':'border-[#18392b]/10 bg-white text-[#18392b]/55 hover:border-[#18392b]/30')}>{c.replace('-',' ')}</button>)}</div>

        {!visible.length&&!loading?<div className="mt-6 rounded-[28px] border border-dashed border-[#18392b]/15 bg-white p-10 text-center"><div className="text-lg font-black">No {mealType} options match this filter yet.</div><p className="mt-2 text-sm text-[#18392b]/45">Generate fresh ideas that actually match it.</p><button onClick={()=>generateAI(`${filter==='all'?'varied':filter} ${mealType} ideas`)} className="mt-4 rounded-xl bg-[#18392b] px-5 py-3 text-xs font-black text-white"><Sparkles size={14} className="mr-2 inline"/>Generate matching meals</button></div>:
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{visible.map(m=><MealCard key={m.id} meal={m} open={()=>setDetail(m)} like={()=>react(m,'like')} skip={()=>react(m,'skip')} appliances={appliances}/>)}</div>}
      </section>}

      {tab==='picks'&&<section><Title kicker="Your shortlist" title="Picks" text="Everything you liked stays here. Mix breakfast, lunch, dinner, dessert and snacks."/>{!liked.length?<Empty text="Like some meals first."/>:<><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{liked.map(m=><MealCard key={m.id} meal={m} open={()=>setDetail(m)} like={()=>setLiked(x=>x.filter(v=>v.id!==m.id))} skip={()=>setLiked(x=>x.filter(v=>v.id!==m.id))} appliances={appliances} picked/>)}</div><div className="sticky bottom-4 mt-6 flex justify-end"><button onClick={()=>makeBasket()} className="rounded-2xl bg-[#18392b] px-6 py-3.5 text-sm font-black text-white shadow-xl"><ShoppingBasket size={16} className="mr-2 inline"/>Optimize grocery basket</button></div></>}
      </section>}

      {tab==='plan'&&<section><Title kicker="Weekly plan" title="Your week at a glance" text="Each day groups breakfast, lunch, dinner and extras in one compact card."/><div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">{week.map(d=><div key={d.day} className="rounded-[24px] bg-white p-4 shadow-sm ring-1 ring-black/[.03]"><div className="text-[10px] font-black uppercase tracking-[.18em] text-[#18392b]/35">Day {d.day+1}</div>{!d.slots.length?<div className="py-8 text-center text-xs text-[#18392b]/35">No meals selected</div>:<div className="mt-3 space-y-3">{d.slots.map(s=><button key={s.type} onClick={()=>setDetail(s.meal!)} className="flex w-full items-center gap-3 rounded-2xl bg-[#f7f4ee] p-2.5 text-left transition hover:-translate-y-0.5 hover:shadow-md"><img src={s.meal!.image} className="h-14 w-16 rounded-xl object-cover"/><div className="min-w-0"><div className="text-[9px] font-black uppercase tracking-wide text-[#2d7a52]">{s.type}</div><div className="truncate text-xs font-black">{s.meal!.name}</div><div className="text-[10px] text-[#18392b]/40">{s.meal!.time} min · {caloriesOf(s.meal!)} kcal</div></div></button>)}</div>}</div>)}</div>
      </section>}

      {tab==='today'&&<section><Title kicker="Today" title="Cook without thinking" text="Your meal on the left, the shortest useful recipe on the right."/>{!todaySlots.length?<Empty text="Nothing selected for today."/>:<div className="mt-5 space-y-5">{todaySlots.map(s=><div key={s.type} className="grid overflow-hidden rounded-[28px] bg-white shadow-sm lg:grid-cols-[.75fr_1.25fr]"><div className="relative min-h-[240px]"><img src={s.meal!.image} className="absolute inset-0 h-full w-full object-cover"/><span className="absolute left-4 top-4 rounded-full bg-white/90 px-3 py-1.5 text-[10px] font-black uppercase">{s.type}</span></div><RecipePane meal={s.meal!} appliances={appliances}/></div>)}</div>}
      </section>}

      {tab==='basket'&&<section><Title kicker="Shopping" title="Optimized basket" text="Switch strategy any time. Open alternatives when you want a different pasta, brand or pack."/><div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{strategies.map(s=><button key={s.id} onClick={()=>changeStrategy(s.id)} className={cx('rounded-2xl border p-4 text-left transition hover:-translate-y-0.5',strategy===s.id?'border-[#18392b] bg-[#18392b] text-white shadow-lg':'border-[#18392b]/10 bg-white')}><div className="text-lg">{s.icon}</div><div className="mt-1 text-xs font-black">{s.label}</div></button>)}</div>{!basket.length?<Empty text="Generate a basket from Picks."/>:<div className="mt-5 grid gap-6 lg:grid-cols-[1fr_300px]"><div className="space-y-3">{basket.map(item=><div key={item.ingredient} className="rounded-[22px] bg-white p-4 shadow-sm"><div className="flex items-start gap-3"><button onClick={()=>toggleOwned(item.ingredient)} className={cx('mt-1 grid h-7 w-7 place-items-center rounded-lg border',owned.includes(item.ingredient)?'border-[#18392b] bg-[#18392b] text-white':'border-[#18392b]/15')}>{owned.includes(item.ingredient)&&<Check size={13}/>}</button><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><b className="capitalize">{item.ingredient}</b>{item.badge&&<span className="rounded-full bg-[#edf3ee] px-2 py-1 text-[9px] font-black text-[#2d7a52]">{item.badge}</span>}</div><div className="mt-1 text-xs text-[#18392b]/40">Need {item.needed_quantity??item.quantity} {item.unit}{item.pantry_used?` · pantry ${item.pantry_used} ${item.unit}`:''}</div>{item.product?<div className="mt-3 flex flex-col gap-3 rounded-2xl bg-[#f7f4ee] p-3 sm:flex-row sm:items-center sm:justify-between"><div><div className="text-sm font-black">{item.product.name_original}</div><div className="text-[11px] text-[#18392b]/40">{item.product.brand||'REWE'} · {item.product.package_size} {item.product.package_unit} · {item.packs} pack{item.packs===1?'':'s'}</div></div><div className="flex items-center gap-2"><b>{money(item.total)}</b><button onClick={()=>openAlternatives(item)} className="rounded-xl bg-white px-3 py-2 text-[10px] font-black shadow-sm">See alternatives</button>{item.product.id&&<button onClick={()=>purchase(item)} className="rounded-xl bg-[#18392b] p-2 text-white"><PackageCheck size={14}/></button>}</div></div>:<div className="mt-3 flex items-center justify-between rounded-xl bg-[#edf3ee] p-3 text-xs"><span>🏠 Using pantry / already at home</span><button onClick={()=>toggleOwned(item.ingredient)} className="font-black underline">Need to buy instead</button></div>}</div></div></div>)}</div><aside className="h-fit rounded-[26px] bg-[#18392b] p-5 text-white"><div className="text-[10px] font-black uppercase tracking-[.18em] text-white/45">Estimated basket</div><div className="mt-2 text-4xl font-black">{money(summary?.total)}</div><div className="mt-4 text-xs text-white/55">{money(summary?.cost_per_serving)} / serving · {basket.length} items</div></aside></div>}
      </section>}

      {tab==='pantry'&&<section><Title kicker="At home" title="Pantry" text="Bitewise uses this first before asking you to buy more."/><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{pantry.map(p=><div key={p.id} className="rounded-[22px] bg-white p-4 shadow-sm"><div className="font-black capitalize">{p.ingredient}</div><div className="mt-2 text-2xl font-black">{Number(p.quantity).toFixed(1)} <span className="text-xs text-[#18392b]/40">{p.unit}</span></div></div>)}</div></section>}

      {tab==='settings'&&<section><Title kicker="Profile" title="Make Bitewise cook your way" text="Tell it what appliances you own. AI recipes will prefer the lowest-effort method available."/><div className="mt-5 rounded-[28px] bg-white p-6 shadow-sm"><div className="font-black">Kitchen appliances</div><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{applianceOptions.map(a=><button key={a.id} onClick={()=>setAppliances(x=>x.includes(a.id)?x.filter(v=>v!==a.id):[...x,a.id])} className={cx('flex items-center gap-3 rounded-2xl border p-4 text-left transition',appliances.includes(a.id)?'border-[#2d7a52] bg-[#edf7ef] text-[#18392b]':'border-[#18392b]/10 hover:border-[#18392b]/30')}>{a.icon}<span className="text-sm font-black">{a.label}</span>{appliances.includes(a.id)&&<Check size={14} className="ml-auto"/>}</button>)}</div><p className="mt-4 text-xs text-[#18392b]/45">When you generate new meals, Bitewise sends these appliances to the AI so it can prefer air fryer, microwave or oven methods over extra pans when appropriate.</p></div></section>}
    </main>

    {detail&&<div className="fixed inset-0 z-50 overflow-y-auto bg-[#102018]/55 p-4 backdrop-blur-sm" onMouseDown={()=>setDetail(null)}><div className="mx-auto mt-4 max-w-4xl overflow-hidden rounded-[30px] bg-white shadow-2xl" onMouseDown={e=>e.stopPropagation()}><div className="grid lg:grid-cols-[.9fr_1.1fr]"><div className="relative min-h-[300px]"><img src={detail.image} className="absolute inset-0 h-full w-full object-cover"/><button onClick={()=>setDetail(null)} className="absolute right-4 top-4 rounded-full bg-white/90 p-2"><X size={16}/></button></div><RecipePane meal={detail} appliances={appliances}/></div></div></div>}

    {altItem&&<div className="fixed inset-0 z-50 overflow-y-auto bg-[#102018]/55 p-4 backdrop-blur-sm"><div className="mx-auto mt-8 max-w-2xl rounded-[28px] bg-white p-6"><div className="flex justify-between"><div><div className="text-[10px] font-black uppercase tracking-[.18em] text-[#18392b]/35">{altItem.ingredient}</div><h2 className="text-2xl font-black">Choose a different REWE product</h2></div><button onClick={()=>setAltItem(null)}><X/></button></div><div className="mt-4 flex gap-2"><input value={altSearch} onChange={e=>setAltSearch(e.target.value)} onKeyDown={e=>e.key==='Enter'&&searchAlternatives()} className="min-w-0 flex-1 rounded-xl bg-[#f7f4ee] px-4 py-3 text-sm outline-none"/><button onClick={searchAlternatives} className="rounded-xl bg-[#18392b] px-4 text-white"><Search size={16}/></button></div><div className="mt-4 max-h-[60vh] space-y-2 overflow-y-auto">{alternatives.map(p=><button key={p.id||p.name_original} onClick={()=>chooseAlternative(p)} className="flex w-full items-center justify-between rounded-2xl border border-[#18392b]/8 p-4 text-left transition hover:border-[#2d7a52]/40 hover:bg-[#edf7ef]"><div><div className="text-sm font-black">{p.name_original}</div><div className="text-[11px] text-[#18392b]/40">{p.brand||'REWE'} · {p.package_size} {p.package_unit}</div></div><b>{money(p.price)}</b></button>)}</div></div></div>}
  </div>
}

function MealCard({meal,open,like,skip,appliances,picked=false}:{meal:Meal;open:()=>void;like:()=>void;skip:()=>void;appliances:string[];picked?:boolean}){
  return <article className="group overflow-hidden rounded-[24px] bg-white shadow-sm ring-1 ring-black/[.03] transition duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-[#18392b]/10"><button onClick={open} className="block w-full text-left"><div className="relative aspect-[4/3] overflow-hidden bg-[#e7e1d7]"><img src={meal.image} alt={meal.name} className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.04]"/><div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-black/55 to-transparent"/><div className="absolute bottom-3 left-3 flex gap-2"><span className="rounded-full bg-white/90 px-2.5 py-1 text-[9px] font-black">{mealTypeOf(meal)}</span><span className="rounded-full bg-[#18392b]/90 px-2.5 py-1 text-[9px] font-black text-white">{caloriesOf(meal)} kcal</span></div></div><div className="p-4"><div className="flex items-start justify-between gap-3"><h3 className="text-base font-black leading-tight">{meal.name}</h3><span className="shrink-0 text-xs font-black text-[#2d7a52]">{money(meal.cost)}</span></div><p className="mt-1 line-clamp-2 min-h-9 text-xs leading-4 text-[#18392b]/45">{meal.description}</p><div className="mt-3 flex gap-2 text-[10px] font-bold text-[#18392b]/50"><span><Clock3 size={11} className="mr-1 inline"/>{meal.time} min</span><span>·</span><span>{meal.difficulty}</span><span>·</span><span>{meal.cuisine}</span></div></div></button><div className="grid grid-cols-[1fr_auto] gap-2 px-4 pb-4"><button onClick={like} className={cx('rounded-xl px-3 py-2.5 text-xs font-black transition',picked?'bg-[#edf3ee] text-[#18392b]':'bg-[#18392b] text-white hover:bg-[#23543d]')}>{picked?<><X size={13} className="mr-1 inline"/>Remove</>:<><Heart size={13} className="mr-1 inline"/>I'd eat this</>}</button><button onClick={skip} className="rounded-xl border border-[#18392b]/10 px-3 text-[#18392b]/45 hover:bg-[#f7f4ee]"><ArrowRight size={14}/></button></div></article>
}

function RecipePane({meal,appliances}:{meal:Meal;appliances:string[]}){
  const steps=meal.steps?.length?meal.steps:fallbackSteps(meal,appliances);
  return <div className="p-6 sm:p-7"><div className="flex flex-wrap gap-2"><span className="rounded-full bg-[#edf7ef] px-3 py-1 text-[10px] font-black text-[#2d7a52]">{mealTypeOf(meal)}</span><span className="rounded-full bg-[#f7f4ee] px-3 py-1 text-[10px] font-black">{caloriesOf(meal)} kcal</span><span className="rounded-full bg-[#f7f4ee] px-3 py-1 text-[10px] font-black">{meal.time} min</span></div><h2 className="mt-4 text-2xl font-black">{meal.name}</h2><p className="mt-2 text-sm leading-6 text-[#18392b]/50">{meal.description}</p><div className="mt-5"><div className="text-[10px] font-black uppercase tracking-[.18em] text-[#18392b]/35">Fastest simple method</div><div className="mt-3 space-y-3">{steps.map((s,i)=><div key={i} className="flex gap-3"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#18392b] text-[10px] font-black text-white">{i+1}</span><div className="pt-1 text-sm font-semibold leading-5">{s.text}{s.minutes!=null&&<span className="ml-2 whitespace-nowrap text-[10px] font-black text-[#2d7a52]">~{s.minutes} min</span>}</div></div>)}</div></div><div className="mt-6 border-t border-[#18392b]/8 pt-4"><div className="text-[10px] font-black uppercase tracking-[.18em] text-[#18392b]/35">Ingredients</div><div className="mt-2 flex flex-wrap gap-2">{meal.ingredients?.map(([n,q,u])=><span key={n} className="rounded-full bg-[#f7f4ee] px-3 py-1.5 text-[10px] font-bold">{n} · {q} {u}</span>)}</div></div><div className="mt-5 flex flex-wrap gap-2">{appliances.map(a=><span key={a} className="rounded-full border border-[#18392b]/10 px-3 py-1 text-[9px] font-bold text-[#18392b]/45">{a}</span>)}</div></div>
}
function Title({kicker,title,text}:{kicker:string;title:string;text:string}){return <div><div className="text-[10px] font-black uppercase tracking-[.2em] text-[#2d7a52]">{kicker}</div><h1 className="mt-1 text-3xl font-black tracking-tight">{title}</h1><p className="mt-2 max-w-2xl text-sm text-[#18392b]/45">{text}</p></div>}
function Empty({text}:{text:string}){return <div className="mt-6 rounded-[26px] border border-dashed border-[#18392b]/15 bg-white p-12 text-center"><Sparkles className="mx-auto text-[#18392b]/20"/><div className="mt-3 text-sm font-black">{text}</div></div>}
