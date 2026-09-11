import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  ChefHat,
  Clock3,
  Database,
  Euro,
  ExternalLink,
  Heart,
  Home,
  Minus,
  PackageCheck,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShoppingBasket,
  Sparkles,
  Trash2,
  UtensilsCrossed,
  X,
} from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

type Meal = {
  id: string;
  name: string;
  description: string;
  time: number;
  difficulty: string;
  cost: number;
  cuisine: string;
  tags: string[];
  ingredients: [string, number, string][];
  image: string;
};

type Product = {
  id: number | null;
  supermarket?: string;
  ingredient: string;
  name_original: string;
  name_normalized?: string;
  translated_name?: string | null;
  brand?: string | null;
  category?: string | null;
  package_size: number;
  package_unit: string;
  price: number | null;
  price_per_unit?: number | null;
  product_url?: string | null;
  availability?: string;
};

type BasketItem = {
  ingredient: string;
  quantity: number;
  needed_quantity?: number;
  unit: string;
  source_meals: string[];
  product: Product | null;
  packs: number;
  total: number;
  waste: number;
  pantry_used?: number;
  badge?: string;
  why?: string;
  selected_by_user?: boolean;
};

type PantryItem = {
  id: number;
  ingredient: string;
  quantity: number;
  unit: string;
  confidence: string;
  source: string;
  notes?: string | null;
  expiry_date?: string | null;
  status: string;
};

type PlannedMeal = {
  id: number;
  plan_id: number;
  meal_id: string;
  day_index: number;
  meal_type: string;
  servings: number;
  status: string;
  meal: Meal;
  pantry_coverage_pct?: number;
};

type Plan = {
  id: number;
  weeks: number;
  servings: number;
  strategy: string;
  budget?: number | null;
  start_date: string;
  status: string;
  meals: PlannedMeal[];
};

type Tab = 'discover' | 'picks' | 'plan' | 'today' | 'shopping' | 'pantry' | 'rewe' | 'settings';

type Strategy = 'maximum-savings' | 'best-value' | 'plan-efficiency' | 'premium';

const strategies: { id: Strategy; label: string; icon: string; detail: string }[] = [
  { id: 'maximum-savings', label: 'Maximum Savings', icon: '💰', detail: 'Lowest checkout cost' },
  { id: 'best-value', label: 'Best Value', icon: '⭐', detail: 'Price + waste + quality balance' },
  { id: 'plan-efficiency', label: 'Plan Efficiency', icon: '🔥', detail: 'Best for your whole plan' },
  { id: 'premium', label: 'Premium', icon: '✨', detail: 'Prefer premium signals' },
];

const modes = ['random', 'quick', 'cheap', 'healthy', 'high-protein', 'one-pot', 'meal-prep', 'asian', 'mexican', 'italian', 'mediterranean', 'latin-american', 'german'];

async function api(path: string, options?: RequestInit) {
  const response = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `HTTP ${response.status}`);
  }
  return response.json();
}

function money(value?: number | null) {
  return `€${Number(value || 0).toFixed(2)}`;
}

function classNames(...values: (string | false | null | undefined)[]) {
  return values.filter(Boolean).join(' ');
}

export default function App() {
  const [tab, setTab] = useState<Tab>('discover');
  const [meals, setMeals] = useState<Meal[]>([]);
  const [likedMeals, setLikedMeals] = useState<Meal[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [mode, setMode] = useState('random');
  const [brainDump, setBrainDump] = useState('');
  const [brainResult, setBrainResult] = useState<any>(null);
  const [servings, setServings] = useState(2);
  const [strategy, setStrategy] = useState<Strategy>('best-value');
  const [basket, setBasket] = useState<BasketItem[]>([]);
  const [basketSummary, setBasketSummary] = useState<any>(null);
  const [owned, setOwned] = useState<string[]>([]);
  const [pantry, setPantry] = useState<PantryItem[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [activePlan, setActivePlan] = useState<Plan | null>(null);
  const [today, setToday] = useState<any>(null);
  const [reweStatus, setReweStatus] = useState<any>(null);
  const [postcode, setPostcode] = useState('13353');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [productModal, setProductModal] = useState<BasketItem | null>(null);

  useEffect(() => {
    Promise.all([loadMeals('random'), loadPantry(), loadPlans(), loadSettings(), loadReweStatus()]).catch(() => undefined);
  }, []);

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setLoading(true);
    setError('');
    try {
      return await fn();
    } catch (err: any) {
      setError(err?.message || 'Something went wrong');
      return undefined;
    } finally {
      setLoading(false);
    }
  }

  async function loadMeals(nextMode = mode) {
    const data = await api(`/meals?mode=${encodeURIComponent(nextMode)}`);
    const incoming: Meal[] = data.meals || data || [];
    setMeals(incoming.filter(m => !likedMeals.some(x => x.id === m.id) && !skipped.includes(m.id)));
  }

  async function loadPantry() {
    const data = await api('/pantry');
    setPantry(data || []);
  }

  async function loadPlans() {
    const data = await api('/plans');
    const next = data.plans || [];
    setPlans(next);
    setActivePlan((current: Plan | null) => current ? next.find((p: Plan) => p.id === current.id) || next[0] || null : next[0] || null);
  }

  async function loadToday(planId?: number) {
    const data = await api(`/today${planId ? `?plan_id=${planId}` : ''}`);
    setToday(data);
  }

  async function loadSettings() {
    const data = await api('/settings');
    setPostcode(data.postcode || '13353');
    if (strategies.some(x => x.id === data.shopping_strategy)) setStrategy(data.shopping_strategy);
  }

  async function loadReweStatus() {
    const data = await api('/rewe/status');
    setReweStatus(data);
  }

  async function reactToMeal(meal: Meal, action: 'like' | 'skip' | 'dislike') {
    await run(async () => {
      await api('/events', { method: 'POST', body: JSON.stringify({ meal_id: meal.id, action }) });
      if (action === 'like') setLikedMeals(current => [...current, meal]);
      else setSkipped(current => [...current, meal.id]);
      setMeals(current => current.filter(x => x.id !== meal.id));
    });
  }

  async function applyBrainDump() {
    if (!brainDump.trim()) return;
    await run(async () => {
      const result = await api('/brain-dump', { method: 'POST', body: JSON.stringify({ prompt: brainDump }) });
      setBrainResult(result.constraints);
      setMode(result.mode);
      await loadMeals(result.mode);
    });
  }

  async function generateBasket(mealSource = likedMeals, nextStrategy = strategy) {
    if (!mealSource.length) return;
    await run(async () => {
      const map = Object.fromEntries(mealSource.map(meal => [meal.id, servings]));
      const data = await api('/shopping', {
        method: 'POST',
        body: JSON.stringify({ meal_ids: mealSource.map(m => m.id), servings: map, owned, mode: nextStrategy }),
      });
      setBasket(data.items || data.basket || []);
      setBasketSummary(data);
      setTab('shopping');
    });
  }

  async function generateBasketFromPlan(plan = activePlan, nextStrategy = strategy) {
    if (!plan) return;
    const source = plan.meals.filter(x => x.status === 'planned').map(x => x.meal);
    await generateBasket(source, nextStrategy);
  }

  async function selectStrategy(next: Strategy) {
    setStrategy(next);
    await api('/settings', { method: 'PATCH', body: JSON.stringify({ shopping_strategy: next }) });
    if (basket.length) await generateBasket(likedMeals.length ? likedMeals : activePlan?.meals.map(x => x.meal) || [], next);
  }

  async function toggleOwned(ingredient: string) {
    const next = owned.includes(ingredient) ? owned.filter(x => x !== ingredient) : [...owned, ingredient];
    setOwned(next);
    await api('/shopping/state', {
      method: 'PUT',
      body: JSON.stringify({ ingredient, state: next.includes(ingredient) ? 'owned' : 'needed' }),
    });
  }

  async function purchase(item: BasketItem) {
    if (!item.product?.id) return;
    await run(async () => {
      await api('/shopping/purchase', {
        method: 'POST',
        body: JSON.stringify({ product_id: item.product!.id, packs: item.packs, ingredient: item.ingredient }),
      });
      await loadPantry();
      setBasket(current => current.filter(x => x.ingredient !== item.ingredient));
    });
  }

  async function createPlan(weeks: 1 | 2 | 4) {
    await run(async () => {
      const data = await api('/plans', {
        method: 'POST',
        body: JSON.stringify({
          weeks,
          servings,
          strategy,
          meal_ids: likedMeals.map(m => m.id),
        }),
      });
      setActivePlan(data);
      await loadPlans();
      setTab('plan');
    });
  }

  async function swapPlannedMeal(planned: PlannedMeal) {
    if (!activePlan) return;
    await run(async () => {
      await api(`/plans/${activePlan.id}/meals/${planned.id}/swap`, { method: 'POST', body: '{}' });
      await loadPlans();
      await loadToday(activePlan.id);
    });
  }

  async function removePlannedMeal(planned: PlannedMeal) {
    if (!activePlan) return;
    await run(async () => {
      await api(`/plans/${activePlan.id}/meals/${planned.id}`, { method: 'DELETE' });
      await loadPlans();
    });
  }

  async function regeneratePlan() {
    if (!activePlan) return;
    await run(async () => {
      await api(`/plans/${activePlan.id}/regenerate`, { method: 'POST' });
      await loadPlans();
    });
  }

  async function setMealStatus(planned: PlannedMeal, status: 'eaten' | 'cooked' | 'skipped') {
    if (!activePlan) return;
    await run(async () => {
      await api(`/plans/${activePlan.id}/meals/${planned.id}/status`, {
        method: 'POST',
        body: JSON.stringify({ status }),
      });
      await Promise.all([loadPlans(), loadToday(activePlan.id), loadPantry()]);
    });
  }

  async function updatePostcode() {
    await run(async () => {
      await api('/settings', { method: 'PATCH', body: JSON.stringify({ postcode }) });
      await loadReweStatus();
    });
  }

  async function refreshRewe() {
    await run(async () => {
      await api('/rewe/refresh', { method: 'POST' });
      await loadReweStatus();
    });
  }

  function navigate(next: Tab) {
    setTab(next);
    if (next === 'pantry') loadPantry();
    if (next === 'plan') loadPlans();
    if (next === 'today') loadToday(activePlan?.id);
    if (next === 'rewe') loadReweStatus();
  }

  return (
    <div className="min-h-screen bg-[#f5f3ee] text-[#171715]">
      <Header tab={tab} navigate={navigate} selected={likedMeals.length} />
      <main className="mx-auto max-w-7xl px-4 pb-28 pt-6 sm:px-6 lg:px-8 lg:pb-12">
        {error && <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">{error}</div>}
        {tab === 'discover' && (
          <Discover
            meals={meals}
            mode={mode}
            setMode={async next => { setMode(next); await run(() => loadMeals(next)); }}
            brainDump={brainDump}
            setBrainDump={setBrainDump}
            brainResult={brainResult}
            applyBrainDump={applyBrainDump}
            reactToMeal={reactToMeal}
            selected={likedMeals.length}
            loading={loading}
            viewPicks={() => setTab('picks')}
          />
        )}
        {tab === 'picks' && (
          <Picks
            meals={likedMeals}
            servings={servings}
            setServings={setServings}
            remove={id => setLikedMeals(current => current.filter(x => x.id !== id))}
            generate={() => generateBasket()}
            createPlan={createPlan}
          />
        )}
        {tab === 'plan' && (
          <PlanPage
            plans={plans}
            activePlan={activePlan}
            setActivePlan={setActivePlan}
            swap={swapPlannedMeal}
            remove={removePlannedMeal}
            regenerate={regeneratePlan}
            shop={() => generateBasketFromPlan()}
            createPlan={createPlan}
          />
        )}
        {tab === 'today' && (
          <TodayPage
            today={today}
            refresh={() => loadToday(activePlan?.id)}
            swap={swapPlannedMeal}
            status={setMealStatus}
            goPlan={() => setTab('plan')}
          />
        )}
        {tab === 'shopping' && (
          <ShoppingPage
            basket={basket}
            summary={basketSummary}
            strategy={strategy}
            setStrategy={selectStrategy}
            owned={owned}
            toggleOwned={toggleOwned}
            purchase={purchase}
            changeProduct={setProductModal}
          />
        )}
        {tab === 'pantry' && <PantryPage items={pantry} reload={loadPantry} run={run} />}
        {tab === 'rewe' && <RewePage status={reweStatus} refresh={refreshRewe} loading={loading} />}
        {tab === 'settings' && (
          <SettingsPage
            postcode={postcode}
            setPostcode={setPostcode}
            savePostcode={updatePostcode}
            strategy={strategy}
            setStrategy={selectStrategy}
          />
        )}
      </main>
      <MobileNav tab={tab} navigate={navigate} selected={likedMeals.length} />
      {productModal && (
        <ProductModal
          item={productModal}
          close={() => setProductModal(null)}
          changed={async () => {
            setProductModal(null);
            await generateBasket(likedMeals.length ? likedMeals : activePlan?.meals.map(x => x.meal) || []);
          }}
        />
      )}
    </div>
  );
}

function Header({ tab, navigate, selected }: { tab: Tab; navigate: (t: Tab) => void; selected: number }) {
  const items: { id: Tab; label: string }[] = [
    { id: 'discover', label: 'Discover' },
    { id: 'picks', label: `Picks${selected ? ` ${selected}` : ''}` },
    { id: 'plan', label: 'Plan' },
    { id: 'today', label: 'Today' },
    { id: 'shopping', label: 'Basket' },
  ];
  return (
    <header className="sticky top-0 z-40 border-b border-black/5 bg-[#f5f3ee]/90 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
        <button onClick={() => navigate('discover')} className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-2xl bg-black text-white"><UtensilsCrossed size={19} /></span>
          <div className="text-left"><div className="text-lg font-black">Bitewise</div><div className="text-[10px] font-bold uppercase tracking-[.18em] text-black/40">Food, optimized</div></div>
        </button>
        <nav className="hidden rounded-full bg-white p-1 shadow-sm md:flex">
          {items.map(item => <button key={item.id} onClick={() => navigate(item.id)} className={classNames('rounded-full px-4 py-2 text-sm font-bold', tab === item.id ? 'bg-black text-white' : 'text-black/45 hover:text-black')}>{item.label}</button>)}
        </nav>
        <div className="flex gap-1">
          <button onClick={() => navigate('pantry')} className="rounded-full bg-white p-2.5 shadow-sm" title="Pantry"><Home size={17} /></button>
          <button onClick={() => navigate('rewe')} className="rounded-full bg-white p-2.5 shadow-sm" title="REWE data"><Database size={17} /></button>
          <button onClick={() => navigate('settings')} className="rounded-full bg-white p-2.5 shadow-sm" title="Settings"><Settings size={17} /></button>
        </div>
      </div>
    </header>
  );
}

function Discover(props: any) {
  const { meals, mode, setMode, brainDump, setBrainDump, brainResult, applyBrainDump, reactToMeal, selected, loading, viewPicks } = props;
  return (
    <section>
      <div className="grid gap-5 lg:grid-cols-[1.35fr_.65fr]">
        <div className="overflow-hidden rounded-[34px] bg-[#181816] p-8 text-white sm:p-10">
          <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-xs font-bold"><Sparkles size={14} /> AI food decision engine</div>
          <h1 className="mt-6 max-w-3xl text-4xl font-black tracking-tight sm:text-6xl">Pick what looks good. We optimize the rest.</h1>
          <p className="mt-5 max-w-xl text-base leading-7 text-white/60">Discover meals visually, teach Bitewise your taste, then turn choices into a low-friction grocery plan.</p>
        </div>
        <div className="rounded-[34px] bg-white p-7 shadow-sm">
          <div className="text-xs font-black uppercase tracking-[.18em] text-black/35">This cycle</div>
          <div className="mt-3 text-5xl font-black">{selected}</div>
          <div className="text-sm text-black/45">meals you would eat</div>
          <button onClick={viewPicks} className="mt-8 flex w-full items-center justify-between rounded-2xl bg-black px-4 py-3 text-sm font-bold text-white">Review picks <ArrowRight size={16} /></button>
        </div>
      </div>

      <div className="mt-6 rounded-[28px] bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2 text-xs font-black uppercase tracking-[.18em] text-black/35"><Sparkles size={14} /> Brain Dump</div>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input value={brainDump} onChange={e => setBrainDump(e.target.value)} onKeyDown={e => e.key === 'Enter' && applyBrainDump()} placeholder="Fancy but easy tonight · cheap Mexican · I have chicken and rice..." className="min-w-0 flex-1 rounded-2xl bg-[#f3f1eb] px-4 py-3 text-sm outline-none" />
          <button onClick={applyBrainDump} className="rounded-2xl bg-black px-5 py-3 text-sm font-black text-white">Apply</button>
        </div>
        {brainResult && <div className="mt-3 flex flex-wrap gap-2 text-xs">{Object.entries(brainResult).filter(([,v]) => v !== null && v !== false && v !== '').slice(0,6).map(([k,v]) => <span key={k} className="rounded-full bg-[#f3f1eb] px-3 py-1.5 font-bold">{k}: {String(v)}</span>)}</div>}
      </div>

      <div className="mt-7 flex gap-2 overflow-x-auto pb-2">
        {modes.map(item => <button key={item} onClick={() => setMode(item)} className={classNames('shrink-0 rounded-full border px-4 py-2 text-sm font-bold capitalize', mode === item ? 'border-black bg-black text-white' : 'border-black/10 bg-white text-black/55')}>{item.replace('-', ' ')}</button>)}
      </div>

      {loading ? <Loading /> : <div className="mt-5 grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{meals.map((meal: Meal) => <MealCard key={meal.id} meal={meal} like={() => reactToMeal(meal,'like')} skip={() => reactToMeal(meal,'skip')} dislike={() => reactToMeal(meal,'dislike')} />)}</div>}
    </section>
  );
}

function MealCard({ meal, like, skip, dislike }: { meal: Meal; like: () => void; skip: () => void; dislike: () => void }) {
  return (
    <article className="overflow-hidden rounded-[28px] bg-white shadow-sm">
      <div className="relative aspect-[4/3] bg-[#e8e4dc]">
        {meal.image ? <img src={meal.image} alt={meal.name} className="h-full w-full object-cover" /> : <div className="grid h-full place-items-center"><ChefHat size={44} className="text-black/15" /></div>}
        <div className="absolute left-4 top-4 flex gap-2"><span className="rounded-full bg-white/90 px-3 py-1.5 text-[11px] font-black">{meal.cuisine}</span><span className="rounded-full bg-black/75 px-3 py-1.5 text-[11px] font-black text-white">{money(meal.cost)}</span></div>
      </div>
      <div className="p-5"><h3 className="text-xl font-black">{meal.name}</h3><p className="mt-2 line-clamp-2 min-h-10 text-sm leading-5 text-black/45">{meal.description}</p>
        <div className="mt-4 flex flex-wrap gap-2"><Pill><Clock3 size={12} /> {meal.time} min</Pill><Pill>{meal.difficulty}</Pill>{meal.tags?.slice(0,2).map(tag => <Pill key={tag}>{tag}</Pill>)}</div>
        <div className="mt-5 grid grid-cols-[auto_auto_1fr] gap-2"><button onClick={dislike} className="rounded-xl border border-black/10 p-3" title="Don't show me this"><Trash2 size={16}/></button><button onClick={skip} className="rounded-xl border border-black/10 p-3"><X size={16}/></button><button onClick={like} className="flex items-center justify-center gap-2 rounded-xl bg-black px-4 py-3 text-sm font-black text-white"><Heart size={16}/> I'd eat this</button></div>
      </div>
    </article>
  );
}

function Picks({ meals, servings, setServings, remove, generate, createPlan }: any) {
  return <section><PageTitle eyebrow="Step 2" title="Your picks" description="Fine-tune the meals you liked, then create a basket or a 1–4 week plan." />
    {!meals.length ? <Empty icon={<Heart size={38}/>} title="No picks yet" text="Like meals in Discover first."/> : <div className="grid gap-7 lg:grid-cols-[1fr_340px]">
      <div className="space-y-3">{meals.map((meal: Meal) => <div key={meal.id} className="flex gap-4 rounded-3xl bg-white p-3 shadow-sm"><div className="h-28 w-32 overflow-hidden rounded-2xl bg-[#ece8df]">{meal.image && <img src={meal.image} className="h-full w-full object-cover"/>}</div><div className="min-w-0 flex-1 py-2"><div className="flex justify-between"><div><div className="font-black">{meal.name}</div><div className="mt-1 text-xs text-black/40">{meal.time} min · {meal.cuisine}</div></div><button onClick={() => remove(meal.id)}><X size={16}/></button></div><div className="mt-8 font-black">{money(meal.cost)}</div></div></div>)}</div>
      <aside className="h-fit rounded-[30px] bg-black p-6 text-white lg:sticky lg:top-24"><div className="text-xs font-black uppercase tracking-[.18em] text-white/40">Servings per meal</div><div className="mt-4 flex items-center justify-between rounded-2xl bg-white/10 p-2"><button onClick={() => setServings(Math.max(1, servings-1))} className="p-3"><Minus size={16}/></button><b className="text-xl">{servings}</b><button onClick={() => setServings(Math.min(12, servings+1))} className="p-3"><Plus size={16}/></button></div><button onClick={generate} className="mt-5 w-full rounded-2xl bg-white px-4 py-3.5 text-sm font-black text-black">Optimize grocery basket</button><div className="my-5 h-px bg-white/10"/><div className="text-xs font-bold text-white/45">Or build a plan</div><div className="mt-2 grid grid-cols-3 gap-2">{[1,2,4].map(w => <button key={w} onClick={() => createPlan(w)} className="rounded-xl bg-white/10 px-2 py-3 text-xs font-black">{w} week{w>1?'s':''}</button>)}</div></aside>
    </div>}
  </section>;
}

function PlanPage({ plans, activePlan, setActivePlan, swap, remove, regenerate, shop, createPlan }: any) {
  const grouped = useMemo(() => {
    const out: Record<number, PlannedMeal[]> = {};
    (activePlan?.meals || []).forEach((m: PlannedMeal) => { (out[m.day_index] ||= []).push(m); });
    return out;
  }, [activePlan]);
  return <section><div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><PageTitle eyebrow="Planner" title="Weekly plan" description="Automatically distributed with variety, pantry awareness and your selected shopping strategy."/><div className="flex gap-2"><button onClick={regenerate} disabled={!activePlan} className="rounded-full bg-white px-4 py-2.5 text-sm font-bold shadow-sm"><RefreshCw size={14} className="mr-2 inline"/>Regenerate</button><button onClick={shop} disabled={!activePlan} className="rounded-full bg-black px-4 py-2.5 text-sm font-bold text-white"><ShoppingBasket size={14} className="mr-2 inline"/>Shop plan</button></div></div>
    <div className="mt-6 flex gap-2 overflow-auto">{plans.map((p: Plan) => <button key={p.id} onClick={() => setActivePlan(p)} className={classNames('rounded-full px-4 py-2 text-xs font-black', activePlan?.id===p.id?'bg-black text-white':'bg-white')}>Plan #{p.id} · {p.weeks}w</button>)}<button onClick={() => createPlan(1)} className="rounded-full border border-dashed border-black/20 px-4 py-2 text-xs font-black">+ New</button></div>
    {!activePlan ? <Empty icon={<CalendarDays size={38}/>} title="No plan yet" text="Create a 1, 2 or 4 week plan from your picks."/> : <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Object.entries(grouped).map(([day, rows]) => <div key={day} className="rounded-[26px] bg-white p-4 shadow-sm"><div className="text-xs font-black uppercase tracking-[.16em] text-black/35">Day {Number(day)+1}</div>{rows.map((planned: PlannedMeal) => <div key={planned.id} className="mt-3"><div className="aspect-[16/9] overflow-hidden rounded-2xl bg-[#eeeae2]">{planned.meal?.image && <img src={planned.meal.image} className="h-full w-full object-cover"/>}</div><div className="mt-3 flex justify-between gap-3"><div><b>{planned.meal?.name}</b><div className="text-xs text-black/40">{planned.meal?.time} min · {planned.servings} servings</div></div><span className="h-fit rounded-full bg-[#f3f1eb] px-2.5 py-1 text-[10px] font-black">{planned.status}</span></div><div className="mt-3 flex gap-2"><button onClick={() => swap(planned)} className="flex-1 rounded-xl bg-[#f3f1eb] px-3 py-2 text-xs font-bold">Swap</button><button onClick={() => remove(planned)} className="rounded-xl border border-black/10 px-3"><Trash2 size={14}/></button></div></div>)}</div>)}</div>}
  </section>;
}

function TodayPage({ today, refresh, swap, status, goPlan }: any) {
  useEffect(() => { refresh(); }, []);
  const meals: PlannedMeal[] = today?.meals || [];
  return <section><PageTitle eyebrow="Right now" title="Today" description="One screen for what to cook, what you already have, and what happens next." />
    {!today?.plan ? <Empty icon={<CalendarDays size={38}/>} title="No active plan" text="Create a weekly plan first." action={<button onClick={goPlan} className="rounded-full bg-black px-5 py-3 text-sm font-bold text-white">Go to planner</button>}/> : !meals.length ? <Empty icon={<Check size={38}/>} title="Nothing planned today" text="You are clear for today, or open the planner to move a meal here."/> : <div className="mt-6 grid gap-5 lg:grid-cols-2">{meals.map(meal => <div key={meal.id} className="overflow-hidden rounded-[30px] bg-white shadow-sm"><div className="aspect-[16/8] bg-[#eeeae2]">{meal.meal?.image && <img src={meal.meal.image} className="h-full w-full object-cover"/>}</div><div className="p-6"><div className="flex items-start justify-between gap-4"><div><h2 className="text-2xl font-black">{meal.meal?.name}</h2><div className="mt-2 text-sm text-black/45">{meal.meal?.time} min · {money(meal.meal?.cost)} · {meal.pantry_coverage_pct || 0}% pantry</div></div><Pill>{meal.status}</Pill></div><div className="mt-5 grid grid-cols-3 gap-2"><button onClick={() => status(meal,'eaten')} className="rounded-xl bg-black px-3 py-3 text-xs font-black text-white">Eaten</button><button onClick={() => swap(meal)} className="rounded-xl bg-[#f3f1eb] px-3 py-3 text-xs font-black">Swap</button><button onClick={() => status(meal,'skipped')} className="rounded-xl border border-black/10 px-3 py-3 text-xs font-black">Skip</button></div></div></div>)}</div>}
  </section>;
}

function ShoppingPage({ basket, summary, strategy, setStrategy, owned, toggleOwned, purchase, changeProduct }: any) {
  return <section><PageTitle eyebrow="Step 3" title="Optimized basket" description="Real products when the catalog supports them, pantry deductions, user overrides and plan-level value scoring." />
    <StrategyPicker value={strategy} onChange={setStrategy}/>
    {basket.length === 0 ? <Empty icon={<ShoppingBasket size={38}/>} title="Basket is empty" text="Generate it from Picks or your weekly plan."/> : <div className="mt-7 grid gap-7 lg:grid-cols-[1fr_330px]"><div className="space-y-3">{basket.map((item: BasketItem) => <div key={item.ingredient} className="rounded-[24px] bg-white p-5 shadow-sm"><div className="flex items-start gap-3"><button onClick={() => toggleOwned(item.ingredient)} className={classNames('mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border', owned.includes(item.ingredient)?'border-black bg-black text-white':'border-black/15')}>{owned.includes(item.ingredient)&&<Check size={13}/>}</button><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="font-black capitalize">{item.ingredient}</h3>{item.badge && <span className="rounded-full bg-[#f3f1eb] px-2.5 py-1 text-[10px] font-black">{item.badge}</span>}</div><div className="mt-1 text-xs text-black/40">Need {item.needed_quantity ?? item.quantity} {item.unit}{item.pantry_used ? ` · pantry covers ${item.pantry_used} ${item.unit}`:''}</div>{item.product ? <div className="mt-4 flex flex-col justify-between gap-3 rounded-2xl bg-[#f6f4ef] p-4 sm:flex-row sm:items-center"><div><div className="text-sm font-black">{item.product.name_original}</div><div className="mt-1 text-xs text-black/45">{item.product.brand || 'REWE'} · {item.product.package_size} {item.product.package_unit} · {item.packs} pack{item.packs===1?'':'s'}</div>{item.why && <div className="mt-1 text-[11px] text-black/35">{item.why}</div>}</div><div className="flex items-center gap-2"><b>{money(item.total)}</b>{item.product.id && <button onClick={() => changeProduct(item)} className="rounded-xl bg-white px-3 py-2 text-xs font-black shadow-sm">Change product</button>}{item.product.product_url && <a href={item.product.product_url} target="_blank" rel="noreferrer" className="rounded-xl bg-white p-2"><ExternalLink size={14}/></a>}</div></div> : <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">No compatible catalog product yet.</div>}<div className="mt-3 flex gap-2">{item.product?.id && <button onClick={() => purchase(item)} className="flex items-center gap-2 rounded-xl bg-black px-3 py-2 text-xs font-black text-white"><PackageCheck size={14}/>Purchased → pantry</button>}</div></div></div></div>)}</div>
      <aside className="h-fit rounded-[28px] bg-black p-6 text-white lg:sticky lg:top-24"><div className="text-xs font-black uppercase tracking-[.18em] text-white/40">Basket summary</div><div className="mt-3 text-4xl font-black">{money(summary?.total)}</div><div className="mt-2 text-sm text-white/50">{money(summary?.cost_per_serving)} / serving</div><div className="mt-6 space-y-3 border-t border-white/10 pt-5 text-sm"><Summary label="Items" value={basket.length}/><Summary label="Waste estimate" value={`${summary?.waste || 0}`}/><Summary label="Pantry-assisted" value={summary?.pantry_savings_items || 0}/><Summary label="Strategy" value={summary?.strategy || strategy}/></div></aside></div>}
  </section>;
}

function ProductModal({ item, close, changed }: { item: BasketItem; close: () => void; changed: () => Promise<void> }) {
  const [rows, setRows] = useState<Product[]>([]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (item.product?.id) api(`/products/${item.product.id}/alternatives?needed_qty=${item.needed_quantity || item.quantity}&unit=${encodeURIComponent(item.unit)}`).then(x => setRows(x.alternatives || [])).catch(() => setRows([]));
  }, [item]);
  async function search() { if (!query.trim()) return; const data = await api(`/products/search?q=${encodeURIComponent(query)}`); setRows(data.products || []); }
  async function use(product: Product) { if (!product.id) return; setBusy(true); try { await api('/products/replace',{method:'POST',body:JSON.stringify({ingredient:item.ingredient,product_id:product.id})}); await changed(); } finally { setBusy(false); } }
  async function restore() { setBusy(true); try { await api(`/products/replace/${encodeURIComponent(item.ingredient)}`,{method:'DELETE'}); await changed(); } finally { setBusy(false); } }
  return <div className="fixed inset-0 z-50 overflow-y-auto bg-black/50 p-4"><div className="mx-auto mt-8 max-w-2xl rounded-[30px] bg-white p-6 shadow-2xl"><div className="flex items-start justify-between"><div><div className="text-xs font-black uppercase tracking-[.18em] text-black/35">{item.ingredient}</div><h2 className="mt-1 text-2xl font-black">Change product</h2><p className="mt-1 text-sm text-black/45">Your choice persists and Bitewise will not silently replace it.</p></div><button onClick={close} className="rounded-full bg-[#f3f1eb] p-2"><X size={17}/></button></div><div className="mt-5 flex gap-2"><input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>e.key==='Enter'&&search()} placeholder="Search REWE catalog or brand" className="min-w-0 flex-1 rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm outline-none"/><button onClick={search} className="rounded-xl bg-black px-4 text-white"><Search size={16}/></button></div><button onClick={restore} disabled={busy} className="mt-3 text-xs font-black underline">Restore Bitewise recommendation</button><div className="mt-5 max-h-[58vh] space-y-2 overflow-y-auto">{rows.map(product => <div key={product.id || product.name_original} className="rounded-2xl border border-black/7 p-4"><div className="flex items-start justify-between gap-3"><div><div className="font-black">{product.name_original}</div><div className="mt-1 text-xs text-black/40">{product.brand || 'REWE'} · {product.package_size} {product.package_unit}{product.availability ? ` · ${product.availability}`:''}</div></div><b>{money(product.price)}</b></div><div className="mt-3 flex gap-2"><button onClick={() => use(product)} disabled={busy || !product.id} className="rounded-xl bg-black px-3 py-2 text-xs font-black text-white disabled:opacity-30">Use this instead</button>{product.product_url && <a href={product.product_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded-xl bg-[#f3f1eb] px-3 py-2 text-xs font-black">Open REWE <ExternalLink size={12}/></a>}</div></div>)}{!rows.length && <div className="py-8 text-center text-sm text-black/40">No alternatives loaded yet.</div>}</div></div></div>;
}

function PantryPage({ items, reload, run }: any) {
  const [ingredient, setIngredient] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [unit, setUnit] = useState('unit');
  async function add() { if (!ingredient.trim()) return; await run(async () => { await api('/pantry',{method:'POST',body:JSON.stringify({ingredient,quantity,unit,confidence:'user_confirmed',source:'manual'})}); setIngredient(''); await reload(); }); }
  async function change(item: PantryItem, delta: number) { await run(async () => { await api(`/pantry/${item.id}`,{method:'PATCH',body:JSON.stringify({quantity:Math.max(0,item.quantity+delta)})}); await reload(); }); }
  async function remove(id: number) { await run(async () => { await api(`/pantry/${id}`,{method:'DELETE'}); await reload(); }); }
  return <section><PageTitle eyebrow="Inventory" title="Pantry" description="Estimated after purchases and meals; manual corrections always win."/><div className="mt-6 grid gap-4 rounded-[26px] bg-white p-5 shadow-sm sm:grid-cols-[1fr_120px_120px_auto]"><input value={ingredient} onChange={e=>setIngredient(e.target.value)} placeholder="Ingredient" className="rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm outline-none"/><input type="number" min="0" value={quantity} onChange={e=>setQuantity(Number(e.target.value))} className="rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm outline-none"/><input value={unit} onChange={e=>setUnit(e.target.value)} className="rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm outline-none"/><button onClick={add} className="rounded-xl bg-black px-4 py-2.5 text-sm font-black text-white">Add</button></div><div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{items.map((item: PantryItem) => <div key={item.id} className="rounded-[24px] bg-white p-5 shadow-sm"><div className="flex justify-between"><div><div className="font-black capitalize">{item.ingredient}</div><div className="mt-1 text-xs text-black/40">{item.confidence.replace('_',' ')} · {item.source}</div></div><span className={classNames('h-fit rounded-full px-2.5 py-1 text-[10px] font-black',item.status==='running-low'?'bg-amber-100 text-amber-800':item.status==='out'?'bg-red-100 text-red-700':'bg-emerald-100 text-emerald-800')}>{item.status}</span></div><div className="mt-5 flex items-center justify-between"><div className="text-2xl font-black">{Number(item.quantity).toFixed(1)} <span className="text-sm text-black/40">{item.unit}</span></div><div className="flex gap-1"><button onClick={()=>change(item,-1)} className="rounded-lg bg-[#f3f1eb] p-2"><Minus size={14}/></button><button onClick={()=>change(item,1)} className="rounded-lg bg-[#f3f1eb] p-2"><Plus size={14}/></button><button onClick={()=>remove(item.id)} className="rounded-lg bg-[#f3f1eb] p-2"><Trash2 size={14}/></button></div></div></div>)}{!items.length && <div className="text-sm text-black/40">Pantry is empty.</div>}</div></section>;
}

function RewePage({ status, refresh, loading }: any) {
  return <section><PageTitle eyebrow="Catalog" title="REWE data" description="Manual public-category snapshot. Bitewise never claims these prices are live checkout prices."/><div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4"><Stat label="Products" value={status?.products || 0}/><Stat label="Status" value={status?.status || '—'}/><Stat label="Postcode" value={status?.postcode || '13353'}/><Stat label="Successful categories" value={`${status?.categories_successful || 0}/${status?.categories_processed || 0}`}/></div><div className="mt-5 rounded-[28px] bg-white p-6 shadow-sm"><div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><div className="font-black">Catalog snapshot</div><div className="mt-1 text-sm text-black/45">Last updated: {status?.last_updated ? new Date(status.last_updated).toLocaleString() : 'Never'} · Errors: {status?.errors || 0}</div></div><button onClick={refresh} disabled={loading} className="flex items-center justify-center gap-2 rounded-2xl bg-black px-5 py-3 text-sm font-black text-white disabled:opacity-40"><RefreshCw size={15} className={loading?'animate-spin':''}/>Refresh 17 categories</button></div></div></section>;
}

function SettingsPage({ postcode, setPostcode, savePostcode, strategy, setStrategy }: any) {
  return <section><PageTitle eyebrow="Preferences" title="Settings" description="Keep location and shopping philosophy explicit so optimization stays predictable."/><div className="mt-6 grid gap-5 lg:grid-cols-2"><div className="rounded-[28px] bg-white p-6 shadow-sm"><div className="font-black">REWE postcode</div><p className="mt-1 text-sm text-black/45">Used as catalog context. Default is 13353.</p><div className="mt-4 flex gap-2"><input value={postcode} onChange={e=>setPostcode(e.target.value)} maxLength={5} className="min-w-0 flex-1 rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm outline-none"/><button onClick={savePostcode} className="rounded-xl bg-black px-4 text-sm font-black text-white">Save</button></div></div><div className="rounded-[28px] bg-white p-6 shadow-sm"><div className="font-black">Default shopping strategy</div><p className="mt-1 text-sm text-black/45">Best Value is the recommended default.</p><div className="mt-4"><StrategyPicker value={strategy} onChange={setStrategy} compact/></div></div></div></section>;
}

function StrategyPicker({ value, onChange, compact=false }: { value: Strategy; onChange: (v: Strategy) => void; compact?: boolean }) {
  return <div className={classNames('grid gap-2',compact?'grid-cols-1':'mt-6 sm:grid-cols-2 xl:grid-cols-4')}>{strategies.map(item => <button key={item.id} onClick={()=>onChange(item.id)} className={classNames('rounded-2xl border p-4 text-left transition',value===item.id?'border-black bg-black text-white':'border-black/8 bg-white hover:border-black/20')}><div className="text-lg">{item.icon}</div><div className="mt-2 text-sm font-black">{item.label}</div><div className={classNames('mt-1 text-[11px]',value===item.id?'text-white/50':'text-black/40')}>{item.detail}</div></button>)}</div>;
}

function MobileNav({ tab, navigate, selected }: { tab: Tab; navigate: (t: Tab) => void; selected: number }) {
  const items: { id: Tab; icon: React.ReactNode; label: string }[] = [
    { id:'discover',icon:<Sparkles size={18}/>,label:'Discover' },
    { id:'picks',icon:<Heart size={18}/>,label:`Picks${selected?` ${selected}`:''}` },
    { id:'today',icon:<ChefHat size={18}/>,label:'Today' },
    { id:'shopping',icon:<ShoppingBasket size={18}/>,label:'Basket' },
  ];
  return <div className="fixed inset-x-3 bottom-3 z-40 grid grid-cols-4 rounded-2xl bg-black p-1.5 text-white shadow-2xl md:hidden">{items.map(item => <button key={item.id} onClick={()=>navigate(item.id)} className={classNames('flex flex-col items-center gap-1 rounded-xl py-2 text-[10px] font-bold',tab===item.id?'bg-white text-black':'text-white/60')}>{item.icon}{item.label}</button>)}</div>;
}

function PageTitle({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) { return <div><div className="text-xs font-black uppercase tracking-[.18em] text-black/35">{eyebrow}</div><h1 className="mt-2 text-4xl font-black tracking-tight">{title}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-black/45">{description}</p></div>; }
function Pill({ children }: { children: React.ReactNode }) { return <span className="inline-flex items-center gap-1 rounded-full bg-[#f3f1eb] px-2.5 py-1.5 text-[11px] font-bold">{children}</span>; }
function Summary({ label, value }: { label: string; value: any }) { return <div className="flex justify-between gap-3"><span className="text-white/45">{label}</span><b className="text-right">{String(value)}</b></div>; }
function Stat({ label, value }: { label: string; value: any }) { return <div className="rounded-[24px] bg-white p-5 shadow-sm"><div className="text-xs font-black uppercase tracking-[.14em] text-black/35">{label}</div><div className="mt-2 text-2xl font-black">{String(value)}</div></div>; }
function Empty({ icon, title, text, action }: { icon: React.ReactNode; title: string; text: string; action?: React.ReactNode }) { return <div className="mt-7 rounded-[28px] border border-dashed border-black/15 bg-white p-12 text-center"><div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-[#f3f1eb] text-black/25">{icon}</div><h3 className="mt-5 text-xl font-black">{title}</h3><p className="mt-2 text-sm text-black/45">{text}</p>{action&&<div className="mt-5">{action}</div>}</div>; }
function Loading() { return <div className="mt-8 grid place-items-center rounded-[28px] bg-white p-16"><RefreshCw size={24} className="animate-spin text-black/35"/></div>; }
