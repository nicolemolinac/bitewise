import React, { useEffect, useMemo, useState } from 'react';
import { CalendarDays, ChevronDown, RotateCcw, Sparkles, WalletCards, X } from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

async function api(path: string, options?: RequestInit) {
  const response = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) },
    ...options,
  });
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  return response.json();
}

type Meal = {
  id: string;
  name: string;
  cost: number;
  ingredients: [string, number, string][];
};

type PlannedMeal = {
  id: number;
  meal_id: string;
  day_index: number;
  servings: number;
  status: string;
  meal: Meal;
};

type Plan = {
  id: number;
  weeks: number;
  servings: number;
  strategy: string;
  budget?: number | null;
  meals: PlannedMeal[];
};

type Leftover = {
  ingredient: string;
  waste: number;
  unit: string;
  source_meals?: string[];
  suggestion?: string;
};

export default function MvpControls() {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [dislikes, setDislikes] = useState<Meal[]>([]);
  const [catalogMeals, setCatalogMeals] = useState<Meal[]>([]);
  const [leftovers, setLeftovers] = useState<Leftover[]>([]);
  const [budget, setBudget] = useState('60');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  async function load() {
    const [plansData, dislikeData, mealsData] = await Promise.all([
      api('/plans'),
      api('/events/dislikes'),
      api('/meals?mode=random'),
    ]);
    const latest: Plan | null = plansData.plans?.[0] || null;
    setPlan(latest);
    setDislikes(dislikeData.meals || []);
    setCatalogMeals(mealsData.meals || []);
    if (latest?.budget) setBudget(String(latest.budget));
    if (latest) await loadLeftovers(latest, mealsData.meals || []);
  }

  async function loadLeftovers(current: Plan, mealPool: Meal[]) {
    const planned = current.meals.filter(x => x.status === 'planned');
    if (!planned.length) {
      setLeftovers([]);
      return;
    }
    const servings = Object.fromEntries(planned.map(x => [x.meal_id, x.servings]));
    const data = await api('/shopping', {
      method: 'POST',
      body: JSON.stringify({
        meal_ids: [...new Set(planned.map(x => x.meal_id))],
        servings,
        owned: [],
        mode: current.strategy || 'best-value',
      }),
    });
    const currentIds = new Set(planned.map(x => x.meal_id));
    const rows: Leftover[] = (data.items || data.basket || [])
      .filter((item: any) => Number(item.waste || 0) > 0)
      .sort((a: any, b: any) => Number(b.waste || 0) - Number(a.waste || 0))
      .slice(0, 6)
      .map((item: any) => {
        const nextMeal = mealPool.find(meal =>
          !currentIds.has(meal.id) && meal.ingredients?.some(([name]) => name.toLowerCase() === item.ingredient.toLowerCase()),
        );
        return {
          ingredient: item.ingredient,
          waste: Number(item.waste || 0),
          unit: item.unit,
          source_meals: item.source_meals,
          suggestion: nextMeal?.name,
        };
      });
    setLeftovers(rows);
  }

  useEffect(() => {
    if (open) load().catch(err => setMessage(err?.message || 'Could not load planner tools'));
  }, [open]);

  const projectedMealCost = useMemo(() => {
    if (!plan) return 0;
    return plan.meals.reduce((sum, row) => sum + Number(row.meal?.cost || 0) * Math.max(1, row.servings / 2), 0);
  }, [plan]);

  async function rebuildForBudget() {
    if (!plan) return;
    const target = Number(budget);
    if (!Number.isFinite(target) || target <= 0) {
      setMessage('Enter a budget above €0.');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      const cheapData = await api('/meals?mode=cheap');
      const cheapMeals: Meal[] = cheapData.meals || [];
      const days = plan.weeks * 7;
      const perDay = target / Math.max(days, 1);
      const eligible = cheapMeals
        .filter(meal => Number(meal.cost || 0) <= Math.max(perDay, 1.5))
        .sort((a, b) => Number(a.cost || 0) - Number(b.cost || 0));
      const pool = eligible.length >= 3 ? eligible : cheapMeals.slice().sort((a, b) => Number(a.cost || 0) - Number(b.cost || 0));
      const data = await api('/plans', {
        method: 'POST',
        body: JSON.stringify({
          weeks: plan.weeks,
          servings: plan.servings,
          strategy: 'maximum-savings',
          budget: target,
          meal_ids: pool.slice(0, Math.min(8, pool.length)).map(meal => meal.id),
        }),
      });
      setPlan(data);
      setMessage(`Created budget plan #${data.id} with a €${target.toFixed(0)} guardrail.`);
      await loadLeftovers(data, catalogMeals.length ? catalogMeals : pool);
    } catch (err: any) {
      setMessage(err?.message || 'Could not create budget plan');
    } finally {
      setBusy(false);
    }
  }

  async function moveMeal(row: PlannedMeal, nextDay: number) {
    if (!plan || nextDay === row.day_index) return;
    setBusy(true);
    try {
      await api(`/plans/${plan.id}/meals/${row.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ day_index: nextDay }),
      });
      const fresh = await api(`/plans/${plan.id}`);
      setPlan(fresh);
      setMessage(`${row.meal.name} moved to day ${nextDay + 1}.`);
    } catch (err: any) {
      setMessage(err?.message || 'Could not move meal');
    } finally {
      setBusy(false);
    }
  }

  async function undoDislike(meal: Meal) {
    setBusy(true);
    try {
      await api('/events', { method: 'POST', body: JSON.stringify({ meal_id: meal.id, action: 'undo-dislike' }) });
      setDislikes(current => current.filter(x => x.id !== meal.id));
      setMessage(`${meal.name} can be recommended again.`);
    } catch (err: any) {
      setMessage(err?.message || 'Could not restore meal');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-24 right-5 z-40 flex items-center gap-2 rounded-full bg-[#171715] px-4 py-3 text-xs font-black text-white shadow-xl md:bottom-6"
      >
        <Sparkles size={15} /> Planner tools
      </button>

      {open && (
        <div className="fixed inset-0 z-[80] bg-black/45 p-3 backdrop-blur-sm sm:p-6">
          <div className="ml-auto flex h-full w-full max-w-xl flex-col overflow-hidden rounded-[30px] bg-[#f5f3ee] shadow-2xl">
            <div className="flex items-center justify-between border-b border-black/5 bg-white px-5 py-4">
              <div>
                <div className="text-xs font-black uppercase tracking-[.16em] text-black/35">Finish the loop</div>
                <h2 className="text-xl font-black">Planner tools</h2>
              </div>
              <button onClick={() => setOpen(false)} className="rounded-full bg-[#f3f1eb] p-2"><X size={17} /></button>
            </div>

            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              {message && <div className="rounded-2xl bg-white px-4 py-3 text-sm font-semibold shadow-sm">{message}</div>}

              <section className="rounded-[24px] bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2"><WalletCards size={17} /><h3 className="font-black">Budget guardrail</h3></div>
                <p className="mt-2 text-xs leading-5 text-black/45">Rebuild the latest plan around cheaper meals and Maximum Savings. Basket prices remain a REWE catalog snapshot, not checkout guarantees.</p>
                <div className="mt-4 grid grid-cols-[1fr_auto] gap-2">
                  <div className="flex items-center rounded-2xl bg-[#f3f1eb] px-3"><span className="text-sm font-black">€</span><input value={budget} onChange={e => setBudget(e.target.value)} inputMode="decimal" className="min-w-0 flex-1 bg-transparent px-2 py-3 text-sm font-bold outline-none" /></div>
                  <button disabled={!plan || busy} onClick={rebuildForBudget} className="rounded-2xl bg-black px-4 text-sm font-black text-white disabled:opacity-40">Rebuild</button>
                </div>
                {plan && <div className="mt-3 flex justify-between text-xs text-black/45"><span>Current rough meal estimate</span><b className="text-black">€{projectedMealCost.toFixed(2)}</b></div>}
              </section>

              <section className="rounded-[24px] bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2"><Sparkles size={17} /><h3 className="font-black">Leftover intelligence</h3></div>
                <p className="mt-2 text-xs leading-5 text-black/45">Largest package leftovers from the current optimized basket, plus a reuse idea when another meal matches.</p>
                <div className="mt-4 space-y-2">
                  {!leftovers.length && <div className="rounded-2xl bg-[#f3f1eb] p-4 text-sm text-black/45">No meaningful leftover estimate yet.</div>}
                  {leftovers.map(row => <div key={row.ingredient} className="rounded-2xl bg-[#f3f1eb] p-4"><div className="flex justify-between gap-3"><b className="capitalize">{row.ingredient}</b><span className="text-xs font-black">~{row.waste.toFixed(1)} {row.unit} left</span></div>{row.suggestion && <div className="mt-1 text-xs text-black/45">Reuse idea: {row.suggestion}</div>}</div>)}
                </div>
              </section>

              <section className="rounded-[24px] bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2"><CalendarDays size={17} /><h3 className="font-black">Move meals</h3></div>
                <p className="mt-2 text-xs leading-5 text-black/45">Move a planned meal to another day without regenerating the whole plan.</p>
                <div className="mt-4 space-y-2">
                  {!plan?.meals?.length && <div className="rounded-2xl bg-[#f3f1eb] p-4 text-sm text-black/45">Create a plan first.</div>}
                  {plan?.meals?.filter(row => row.status === 'planned').slice(0, 14).map(row => (
                    <div key={row.id} className="flex items-center gap-3 rounded-2xl bg-[#f3f1eb] p-3">
                      <div className="min-w-0 flex-1"><div className="truncate text-sm font-black">{row.meal?.name}</div><div className="text-[11px] text-black/40">Day {row.day_index + 1}</div></div>
                      <div className="relative">
                        <select disabled={busy} value={row.day_index} onChange={e => moveMeal(row, Number(e.target.value))} className="appearance-none rounded-xl bg-white py-2 pl-3 pr-8 text-xs font-black outline-none">
                          {Array.from({ length: plan.weeks * 7 }, (_, i) => <option key={i} value={i}>Day {i + 1}</option>)}
                        </select>
                        <ChevronDown size={12} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2" />
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="rounded-[24px] bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2"><RotateCcw size={17} /><h3 className="font-black">Review dislikes</h3></div>
                <p className="mt-2 text-xs leading-5 text-black/45">Undo meals you previously marked as “don’t want”.</p>
                <div className="mt-4 space-y-2">
                  {!dislikes.length && <div className="rounded-2xl bg-[#f3f1eb] p-4 text-sm text-black/45">No disliked meals.</div>}
                  {dislikes.map(meal => <div key={meal.id} className="flex items-center justify-between gap-3 rounded-2xl bg-[#f3f1eb] p-3"><div className="min-w-0 truncate text-sm font-black">{meal.name}</div><button disabled={busy} onClick={() => undoDislike(meal)} className="shrink-0 rounded-xl bg-white px-3 py-2 text-xs font-black">Restore</button></div>)}
                </div>
              </section>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
