import React, { useEffect, useMemo, useState } from 'react';
import {
  Heart,
  ShoppingBasket,
  ChefHat,
  Plus,
  Minus,
  X,
  Check,
  RefreshCw,
  Sparkles,
  UtensilsCrossed,
  Clock3,
  Euro,
  ArrowRight,
} from 'lucide-react';
import { createRoot } from 'react-dom/client';
import './index.css';

const API = 'http://localhost:8000/api';

async function api(path: string, opts?: RequestInit) {
  const response = await fetch(API + path, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...opts,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

type Meal = {
  id: string;
  name: string;
  description: string;
  time: number;
  difficulty: string;
  cost: number;
  cuisine: string;
  tags: string[];
  ingredients: any[];
  image: string;
};

type Basket = {
  ingredient: string;
  quantity: number;
  unit: string;
  product: any;
  packs: number;
  total: number;
  waste: number;
};

const modes = [
  { id: 'random', label: 'For me', icon: Sparkles },
  { id: 'quick', label: 'Quick', icon: Clock3 },
  { id: 'cheap', label: 'Cheap', icon: Euro },
  { id: 'healthy', label: 'Healthy', icon: Heart },
  { id: 'high-protein', label: 'High protein', icon: ChefHat },
  { id: 'one-pot', label: 'One pot', icon: UtensilsCrossed },
  { id: 'meal-prep', label: 'Meal prep', icon: ShoppingBasket },
  { id: 'asian', label: 'Asian', icon: UtensilsCrossed },
  { id: 'mexican', label: 'Mexican', icon: UtensilsCrossed },
  { id: 'italian', label: 'Italian', icon: UtensilsCrossed },
  { id: 'mediterranean', label: 'Mediterranean', icon: UtensilsCrossed },
  { id: 'latin-american', label: 'Latin', icon: UtensilsCrossed },
  { id: 'german', label: 'German', icon: UtensilsCrossed },
];

function App() {
  const [tab, setTab] = useState<'discover' | 'picks' | 'shopping' | 'pantry' | 'rewe'>('discover');
  const [mode, setMode] = useState('random');
  const [brainDump, setBrainDump] = useState('');

  const [meals, setMeals] = useState<Meal[]>([]);
  const [likedMeals, setLikedMeals] = useState<Meal[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);

  const [servings, setServings] = useState(2);

  const [basket, setBasket] = useState<Basket[]>([]);
  const [total, setTotal] = useState(0);
  const [costPerServing, setCostPerServing] = useState(0);

  const [owned, setOwned] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const [optMode, setOptMode] = useState<'cheapest' | 'less-waste'>(
    'cheapest'
  );

  async function load(selectedMode = mode) {
    setLoading(true);

    try {
      const data = await api(
        `/meals?mode=${encodeURIComponent(selectedMode)}`
      );

      const incoming: Meal[] = Array.isArray(data)
        ? data
        : data.meals || [];

      const filtered = incoming.filter(
        (meal) =>
          !skipped.includes(meal.id) &&
          !likedMeals.some((liked) => liked.id === meal.id)
      );

      setMeals(filtered);
    } catch (error) {
      console.error('Failed to load meals:', error);
      setMeals([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function reactToMeal(meal: Meal, liked: boolean) {
    try {
      await api('/events', {
        method: 'POST',
        body: JSON.stringify({
          meal_id: meal.id,
          event: liked ? 'like' : 'skip',
        }),
      });
    } catch (error) {
      console.error('Could not save event:', error);
    }

    if (liked) {
      setLikedMeals((current) => [...current, meal]);
    } else {
      setSkipped((current) => [...current, meal.id]);
    }

    setMeals((current) => current.filter((item) => item.id !== meal.id));
  }

  async function applyBrainDump() { if (!brainDump.trim()) return; const result=await api('/brain-dump?prompt='+encodeURIComponent(brainDump),{method:'POST'}); handleModeChange(result.mode); }

  function handleModeChange(nextMode: string) {
    setMode(nextMode);
    load(nextMode);
  }

  async function generateShoppingList(
    requestedMode = optMode,
    overrideOwned = owned
  ) {
    if (!likedMeals.length) return;

    setLoading(true);

    try {
      const data = await api('/shopping', {
        method: 'POST',
        body: JSON.stringify({
          meal_ids: likedMeals.map((meal) => meal.id),
          servings,
          owned: overrideOwned,
          mode: requestedMode,
        }),
      });

      setBasket(data.items || data.basket || []);
      setTotal(Number(data.total || 0));
      setCostPerServing(Number(data.cost_per_serving || 0));
      setTab('shopping');
    } catch (error) {
      console.error('Could not generate shopping list:', error);
    } finally {
      setLoading(false);
    }
  }

  async function changeOptimization(
    nextMode: 'cheapest' | 'less-waste'
  ) {
    setOptMode(nextMode);
    await generateShoppingList(nextMode, owned);
  }

  async function toggleOwned(ingredient: string) {
    const nextOwned = owned.includes(ingredient)
      ? owned.filter((item) => item !== ingredient)
      : [...owned, ingredient];

    setOwned(nextOwned);

    if (likedMeals.length) {
      await generateShoppingList(optMode, nextOwned);
    }
  }

  function removeMeal(id: string) {
    setLikedMeals((current) =>
      current.filter((meal) => meal.id !== id)
    );
  }

  async function replaceMeal(id: string) {
    const nextSkipped = skipped.includes(id)
      ? skipped
      : [...skipped, id];

    setSkipped(nextSkipped);

    setMeals((current) =>
      current.filter((meal) => meal.id !== id)
    );

    await loadWithFilters(mode, likedMeals, nextSkipped);
  }

  async function loadWithFilters(
    selectedMode: string,
    currentLiked: Meal[],
    currentSkipped: string[]
  ) {
    setLoading(true);

    try {
      const data = await api(
        `/meals?mode=${encodeURIComponent(selectedMode)}`
      );

      const incoming: Meal[] = Array.isArray(data)
        ? data
        : data.meals || [];

      setMeals(
        incoming.filter(
          (meal) =>
            !currentSkipped.includes(meal.id) &&
            !currentLiked.some((liked) => liked.id === meal.id)
        )
      );
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  const selectedCount = likedMeals.length;

  const grouped = useMemo(() => {
    const groups: Record<string, Basket[]> = {
      Produce: [],
      Protein: [],
      Pantry: [],
      Dairy: [],
      Other: [],
    };

    basket.forEach((item) => {
      const name = item.ingredient.toLowerCase();

      if (
        name.includes('chicken') ||
        name.includes('beef') ||
        name.includes('salmon') ||
        name.includes('tofu') ||
        name.includes('egg') ||
        name.includes('tuna')
      ) {
        groups.Protein.push(item);
      } else if (
        name.includes('milk') ||
        name.includes('yogurt') ||
        name.includes('cheese')
      ) {
        groups.Dairy.push(item);
      } else if (
        name.includes('tomato') ||
        name.includes('onion') ||
        name.includes('pepper') ||
        name.includes('carrot') ||
        name.includes('spinach') ||
        name.includes('broccoli') ||
        name.includes('avocado') ||
        name.includes('lettuce')
      ) {
        groups.Produce.push(item);
      } else if (
        name.includes('rice') ||
        name.includes('pasta') ||
        name.includes('flour') ||
        name.includes('oil') ||
        name.includes('salt') ||
        name.includes('sauce') ||
        name.includes('spice')
      ) {
        groups.Pantry.push(item);
      } else {
        groups.Other.push(item);
      }
    });

    return groups;
  }, [basket]);

  return (
    <div className="min-h-screen bg-[#f7f6f2] text-[#191817]">
      <header className="sticky top-0 z-40 border-b border-black/5 bg-[#f7f6f2]/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8">
          <button
            onClick={() => setTab('discover')}
            className="flex items-center gap-3"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-black text-white">
              <UtensilsCrossed size={20} />
            </div>

            <div className="text-left">
              <div className="text-lg font-black tracking-tight">
                Bitewise
              </div>
              <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-black/40">
                Food, optimized
              </div>
            </div>
          </button>

          <nav className="hidden items-center gap-1 rounded-full border border-black/5 bg-white p-1 shadow-sm md:flex">
            <NavButton
              active={tab === 'discover'}
              onClick={() => setTab('discover')}
              icon={<Sparkles size={15} />}
            >
              Discover
            </NavButton>

            <NavButton
              active={tab === 'picks'}
              onClick={() => setTab('picks')}
              icon={<Heart size={15} />}
              count={selectedCount}
            >
              My picks
            </NavButton>

            <NavButton
              active={tab === 'shopping'}
              onClick={() => setTab('shopping')}
              icon={<ShoppingBasket size={15} />}
            >
              Basket
            </NavButton>
          </nav>

          <div className="flex items-center gap-2 rounded-full bg-white px-3 py-2 text-xs font-bold shadow-sm">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Berlin
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 pb-28 pt-6 lg:px-8 lg:pb-12">
        {tab === 'discover' && (
          <DiscoverPage
            meals={meals}
            loading={loading}
            mode={mode}
            onModeChange={handleModeChange}
            onLike={(meal) => reactToMeal(meal, true)}
            onSkip={(meal) => reactToMeal(meal, false)}
            selectedCount={selectedCount}
            brainDump={brainDump}
            setBrainDump={setBrainDump}
            onBrainDump={applyBrainDump}
            onViewPicks={() => setTab('picks')}
          />
        )}

        {tab === 'picks' && (
          <PicksPage
            meals={likedMeals}
            servings={servings}
            setServings={setServings}
            onRemove={removeMeal}
            onReplace={replaceMeal}
            onGenerate={() => generateShoppingList()}
            loading={loading}
            onDiscover={() => setTab('discover')}
          />
        )}

        {tab === 'pantry' && <PantryPage />}
        {tab === 'rewe' && <RewePage />}
        {tab === 'shopping' && (
          <ShoppingPage
            basket={basket}
            total={total}
            costPerServing={costPerServing}
            owned={owned}
            onToggleOwned={toggleOwned}
            optMode={optMode}
            onChangeOptimization={changeOptimization}
            loading={loading}
            onBack={() => setTab('picks')}
          />
        )}
      </main>

      <div className="fixed right-5 bottom-5 z-40 hidden gap-2 md:flex"><button onClick={() => setTab('pantry')} className="rounded-full bg-white px-4 py-2 text-xs font-bold shadow">Pantry</button><button onClick={() => setTab('rewe')} className="rounded-full bg-black px-4 py-2 text-xs font-bold text-white shadow">REWE data</button></div>
      <MobileNav
        tab={tab}
        setTab={setTab}
        selectedCount={selectedCount}
      />
    </div>
  );
}

function NavButton({
  active,
  onClick,
  icon,
  children,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 rounded-full px-4 py-2 text-sm font-bold transition ${
        active
          ? 'bg-black text-white'
          : 'text-black/50 hover:bg-black/5 hover:text-black'
      }`}
    >
      {icon}
      {children}

      {count !== undefined && count > 0 && (
        <span
          className={`flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[10px] ${
            active
              ? 'bg-white text-black'
              : 'bg-black text-white'
          }`}
        >
          {count}
        </span>
      )}
    </button>
  );
}

function DiscoverPage({
  meals,
  loading,
  mode,
  onModeChange,
  onLike,
  onSkip,
  selectedCount,
  onViewPicks,
  brainDump,
  setBrainDump,
  onBrainDump,
}: {
  meals: Meal[];
  loading: boolean;
  mode: string;
  onModeChange: (mode: string) => void;
  onLike: (meal: Meal) => void;
  onSkip: (meal: Meal) => void;
  selectedCount: number;
  onViewPicks: () => void;
  brainDump: string;
  setBrainDump: (value: string) => void;
  onBrainDump: () => void;
}) {
  return (
    <section>
      <div className="mb-8 grid gap-6 lg:grid-cols-[1.2fr_.8fr]">
        <div className="relative overflow-hidden rounded-[32px] bg-[#191817] px-7 py-10 text-white lg:px-10 lg:py-14">
          <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-white/10 blur-3xl" />

          <div className="relative max-w-2xl">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-bold">
              <Sparkles size={14} />
              AI food planner
            </div>

            <h1 className="max-w-xl text-4xl font-black tracking-tight sm:text-5xl lg:text-6xl">
              What do you actually want to eat?
            </h1>

            <p className="mt-5 max-w-xl text-base leading-7 text-white/60 sm:text-lg">
              Pick the meals you like. Bitewise turns your choices into
              an optimized grocery basket.
            </p>
          </div>
        </div>

        <div className="rounded-[32px] border border-black/5 bg-white p-7 shadow-sm">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-xs font-black uppercase tracking-[0.18em] text-black/40">
                Your week
              </div>
              <div className="mt-2 text-3xl font-black">
                {selectedCount}
              </div>
              <div className="mt-1 text-sm text-black/45">
                meals selected
              </div>
            </div>

            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#f3f1eb]">
              <Heart size={21} />
            </div>
          </div>

          <button
            onClick={onViewPicks}
            className="mt-8 flex w-full items-center justify-between rounded-2xl bg-black px-4 py-3 text-sm font-bold text-white transition hover:bg-black/80"
          >
            Review my picks
            <ArrowRight size={17} />
          </button>
        </div>
      </div>

      <div className="mb-7 rounded-[24px] border border-black/5 bg-white p-4 shadow-sm"><div className="text-xs font-black uppercase tracking-[.18em] text-black/40">Brain Dump</div><div className="mt-3 flex gap-2"><input value={brainDump} onChange={e => setBrainDump(e.target.value)} onKeyDown={e => e.key === 'Enter' && onBrainDump()} placeholder="Fancy but easy tonight, cheap Mexican dinner..." className="min-w-0 flex-1 rounded-xl bg-[#f4f2ed] px-3 py-2 text-sm outline-none"/><button onClick={onBrainDump} className="rounded-xl bg-black px-4 text-sm font-bold text-white">Find</button></div></div>

      <div className="mb-7">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-black">Find your vibe</h2>
            <p className="mt-1 text-sm text-black/45">
              Choose what sounds good right now.
            </p>
          </div>

          <button
            onClick={() => onModeChange('random')}
            className="hidden items-center gap-2 rounded-full border border-black/10 bg-white px-4 py-2 text-xs font-bold md:flex"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>

        <div className="hide-scroll flex gap-2 overflow-x-auto pb-2">
          {modes.map((item) => {
            const Icon = item.icon;

            return (
              <button
                key={item.id}
                onClick={() => onModeChange(item.id)}
                className={`flex shrink-0 items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-bold transition ${
                  mode === item.id
                    ? 'border-black bg-black text-white'
                    : 'border-black/8 bg-white text-black/55 hover:border-black/20 hover:text-black'
                }`}
              >
                <Icon size={15} />
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      {loading ? (
        <MealSkeletonGrid />
      ) : meals.length === 0 ? (
        <div className="rounded-[28px] border border-dashed border-black/15 bg-white p-12 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-[#f3f1eb]">
            <ChefHat size={25} />
          </div>

          <h3 className="mt-5 text-xl font-black">
            No more meals here
          </h3>

          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-black/45">
            Try another preference and we'll find you something different.
          </p>

          <button
            onClick={() => onModeChange('random')}
            className="mt-6 rounded-full bg-black px-5 py-3 text-sm font-bold text-white"
          >
            Show me something else
          </button>
        </div>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {meals.map((meal) => (
            <MealCard
              key={meal.id}
              meal={meal}
              onLike={() => onLike(meal)}
              onSkip={() => onSkip(meal)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function MealCard({
  meal,
  onLike,
  onSkip,
}: {
  meal: Meal;
  onLike: () => void;
  onSkip: () => void;
}) {
  return (
    <article className="card-shadow group overflow-hidden rounded-[28px] bg-white">
      <div className="relative aspect-[4/3] overflow-hidden bg-[#e9e6de]">
        {meal.image ? (
          <img
            src={meal.image}
            alt={meal.name}
            className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
            onError={(event) => {
              event.currentTarget.style.display = 'none';
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <UtensilsCrossed
              size={50}
              className="text-black/15"
            />
          </div>
        )}

        <div className="absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-black/40 to-transparent pointer-events-none" />

        <div className="absolute top-4 left-4 flex gap-2">
          <span className="rounded-full bg-white/92 px-3 py-1.5 text-[11px] font-black backdrop-blur-md">
            {meal.cuisine}
          </span>

          {meal.cost !== undefined && (
            <span className="rounded-full bg-black/75 px-3 py-1.5 text-[11px] font-black text-white backdrop-blur-md">
              €{Number(meal.cost).toFixed(2)}
            </span>
          )}
        </div>
      </div>

      <div className="p-5">
        <h3 className="text-xl font-black tracking-tight">
          {meal.name}
        </h3>

        <p className="mt-2 min-h-[42px] text-sm leading-6 text-black/50">
          {meal.description}
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          <span className="flex items-center gap-1.5 rounded-full bg-[#f4f2ed] px-3 py-1.5 text-[11px] font-bold">
            <Clock3 size={13} />
            {meal.time} min
          </span>

          <span className="rounded-full bg-[#f4f2ed] px-3 py-1.5 text-[11px] font-bold">
            {meal.difficulty}
          </span>

          {(meal.tags || []).slice(0, 2).map((tag) => (
            <span
              key={tag}
              className="rounded-full bg-[#f4f2ed] px-3 py-1.5 text-[11px] font-bold"
            >
              {tag}
            </span>
          ))}
        </div>

        <div className="mt-5 grid grid-cols-[auto_1fr] gap-2">
          <button
            onClick={onSkip}
            className="flex h-12 items-center justify-center gap-2 rounded-2xl border border-black/10 px-4 text-sm font-bold transition hover:bg-black/5"
          >
            <X size={17} />
            No
          </button>

          <button
            onClick={onLike}
            className="flex h-12 items-center justify-center gap-2 rounded-2xl bg-black px-4 text-sm font-bold text-white transition hover:bg-black/80"
          >
            <Heart size={17} />
            I'd eat this
          </button>
        </div>
      </div>
    </article>
  );
}

function PicksPage({
  meals,
  servings,
  setServings,
  onRemove,
  onReplace,
  onGenerate,
  loading,
  onDiscover,
}: {
  meals: Meal[];
  servings: number;
  setServings: React.Dispatch<React.SetStateAction<number>>;
  onRemove: (id: string) => void;
  onReplace: (id: string) => void;
  onGenerate: () => void;
  loading: boolean;
  onDiscover: () => void;
}) {
  const estimatedTotal = meals.reduce(
    (sum, meal) => sum + Number(meal.cost || 0),
    0
  );

  return (
    <section>
      <div className="mb-8 flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div>
          <div className="text-xs font-black uppercase tracking-[0.18em] text-black/35">
            Step 2
          </div>
          <h1 className="mt-2 text-4xl font-black tracking-tight">
            Your picks
          </h1>
          <p className="mt-2 text-sm text-black/45">
            Fine-tune your meals before we build the basket.
          </p>
        </div>

        <button
          onClick={onDiscover}
          className="flex items-center justify-center gap-2 rounded-full border border-black/10 bg-white px-5 py-3 text-sm font-bold"
        >
          <Plus size={16} />
          Add more meals
        </button>
      </div>

      {meals.length === 0 ? (
        <div className="rounded-[28px] border border-dashed border-black/15 bg-white p-12 text-center">
          <Heart className="mx-auto text-black/20" size={42} />

          <h3 className="mt-5 text-xl font-black">
            Nothing selected yet
          </h3>

          <p className="mt-2 text-sm text-black/45">
            Go discover some meals you would actually eat.
          </p>

          <button
            onClick={onDiscover}
            className="mt-6 rounded-full bg-black px-5 py-3 text-sm font-bold text-white"
          >
            Discover meals
          </button>
        </div>
      ) : (
        <div className="grid gap-7 lg:grid-cols-[1fr_340px]">
          <div className="space-y-4">
            {meals.map((meal) => (
              <div
                key={meal.id}
                className="flex gap-4 rounded-[24px] border border-black/5 bg-white p-3 shadow-sm"
              >
                <div className="h-28 w-28 shrink-0 overflow-hidden rounded-[18px] bg-[#eeeae2] sm:h-32 sm:w-40">
                  {meal.image ? (
                    <img
                      src={meal.image}
                      alt={meal.name}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center">
                      <UtensilsCrossed
                        size={30}
                        className="text-black/15"
                      />
                    </div>
                  )}
                </div>

                <div className="min-w-0 flex-1 py-1">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="font-black">{meal.name}</h3>
                      <p className="mt-1 text-xs text-black/40">
                        {meal.time} min · {meal.cuisine}
                      </p>
                    </div>

                    <button
                      onClick={() => onRemove(meal.id)}
                      className="rounded-full p-2 text-black/30 hover:bg-black/5 hover:text-black"
                    >
                      <X size={16} />
                    </button>
                  </div>

                  <div className="mt-6 flex items-center justify-between">
                    <span className="text-sm font-black">
                      €{Number(meal.cost || 0).toFixed(2)}
                    </span>

                    <button
                      onClick={() => onReplace(meal.id)}
                      className="flex items-center gap-1.5 rounded-full border border-black/10 px-3 py-1.5 text-xs font-bold"
                    >
                      <RefreshCw size={12} />
                      Replace
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <aside className="h-fit rounded-[28px] bg-black p-6 text-white lg:sticky lg:top-24">
            <div className="text-xs font-black uppercase tracking-[0.18em] text-white/40">
              Grocery plan
            </div>

            <h2 className="mt-2 text-2xl font-black">
              Build my basket
            </h2>

            <div className="mt-7">
              <div className="text-xs font-bold text-white/40">
                Servings
              </div>

              <div className="mt-2 flex items-center justify-between rounded-2xl bg-white/10 p-2">
                <button
                  onClick={() =>
                    setServings((value) => Math.max(1, value - 1))
                  }
                  className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10"
                >
                  <Minus size={16} />
                </button>

                <span className="text-lg font-black">
                  {servings}
                </span>

                <button
                  onClick={() =>
                    setServings((value) => Math.min(12, value + 1))
                  }
                  className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10"
                >
                  <Plus size={16} />
                </button>
              </div>
            </div>

            <div className="mt-6 flex justify-between border-t border-white/10 pt-5 text-sm">
              <span className="text-white/50">Selected meals</span>
              <span className="font-bold">{meals.length}</span>
            </div>

            <div className="mt-3 flex justify-between text-sm">
              <span className="text-white/50">Estimated meal cost</span>
              <span className="font-bold">
                €{estimatedTotal.toFixed(2)}
              </span>
            </div>

            <button
              onClick={onGenerate}
              disabled={loading}
              className="mt-7 flex w-full items-center justify-center gap-2 rounded-2xl bg-white px-4 py-4 text-sm font-black text-black disabled:opacity-50"
            >
              {loading ? (
                <RefreshCw size={17} className="animate-spin" />
              ) : (
                <ShoppingBasket size={17} />
              )}
              Optimize grocery list
            </button>
          </aside>
        </div>
      )}
    </section>
  );
}

function ProductAlternatives({product,onClose}:{product:any;onClose:()=>void}){const [rows,setRows]=useState<any[]>([]);useEffect(()=>{if(product?.id)api('/products/'+product.id+'/alternatives').then(x=>setRows(x.alternatives||[]))},[product]);return <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"><div className="w-full max-w-lg rounded-3xl bg-white p-6"><div className="flex justify-between"><h2 className="text-xl font-black">Change product</h2><button onClick={onClose}>Close</button></div><div className="mt-4 space-y-2">{rows.map(x=><a key={x.id} href={x.product_url||'#'} target="_blank" className="block rounded-xl bg-[#f4f2ed] p-3"><b>{x.name_original}</b><span className="float-right">EUR {x.price}</span><small className="block">{x.package_size} {x.package_unit} - Open REWE</small><button onClick={async e=>{e.preventDefault();await api('/products/replace',{method:'POST',body:JSON.stringify({ingredient:product.ingredient,product_id:x.id})});onClose()}} className="mt-2 rounded-lg bg-black px-3 py-1 text-xs font-bold text-white">Use this instead</button></a>)}</div></div></div>};

function ShoppingPage({
  basket,
  total,
  costPerServing,
  owned,
  onToggleOwned,
  optMode,
  onChangeOptimization,
  loading,
  onBack,
}: {
  basket: Basket[];
  total: number;
  costPerServing: number;
  owned: string[];
  onToggleOwned: (ingredient: string) => void;
  optMode: 'cheapest' | 'less-waste';
  onChangeOptimization: (
    mode: 'cheapest' | 'less-waste'
  ) => void;
  loading: boolean;
  onBack: () => void;
}) {
  return (
    <section>
      <div className="mb-8">
        <button
          onClick={onBack}
          className="mb-5 flex items-center gap-2 text-sm font-bold text-black/45 hover:text-black"
        >
          ← Back to picks
        </button>

        <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <div className="text-xs font-black uppercase tracking-[0.18em] text-black/35">
              Step 3
            </div>
            <h1 className="mt-2 text-4xl font-black tracking-tight">
              Your grocery basket
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-black/45">
              We combine ingredients across your meals and optimize
              the shopping list for Berlin prices.
            </p>
          </div>

          <div className="flex rounded-full bg-white p-1 shadow-sm">
            <button
              onClick={() => onChangeOptimization('cheapest')}
              className={`rounded-full px-4 py-2 text-xs font-bold ${
                optMode === 'cheapest'
                  ? 'bg-black text-white'
                  : 'text-black/45'
              }`}
            >
              Cheapest
            </button>

            <button
              onClick={() => onChangeOptimization('less-waste')}
              className={`rounded-full px-4 py-2 text-xs font-bold ${
                optMode === 'less-waste'
                  ? 'bg-black text-white'
                  : 'text-black/45'
              }`}
            >
              Less waste
            </button>
          </div>
        </div>
      </div>

      {loading ? (
        <MealSkeletonGrid />
      ) : basket.length === 0 ? (
        <div className="rounded-[28px] bg-white p-12 text-center">
          <ShoppingBasket
            size={42}
            className="mx-auto text-black/20"
          />

          <h3 className="mt-5 text-xl font-black">
            Your basket is empty
          </h3>
        </div>
      ) : (
        <div className="grid gap-7 lg:grid-cols-[1fr_340px]">
          <div className="space-y-7">
            {Object.entries(groupedFromBasket(basket)).map(
              ([group, items]) =>
                items.length > 0 && (
                  <div key={group}>
                    <div className="mb-3 text-xs font-black uppercase tracking-[0.18em] text-black/35">
                      {group}
                    </div>

                    <div className="overflow-hidden rounded-[24px] bg-white shadow-sm">
                      {items.map((item, index) => {
                        const isOwned = owned.includes(
                          item.ingredient
                        );

                        return (
                          <div
                            key={`${item.ingredient}-${index}`}
                            className="flex items-center gap-4 border-b border-black/5 px-5 py-4 last:border-0"
                          >
                            <button
                              onClick={() =>
                                onToggleOwned(item.ingredient)
                              }
                              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${
                                isOwned
                                  ? 'border-black bg-black text-white'
                                  : 'border-black/15 bg-white'
                              }`}
                            >
                              {isOwned && <Check size={14} />}
                            </button>

                            <div className="min-w-0 flex-1">
                              <div
                                className={`text-sm font-bold ${
                                  isOwned
                                    ? 'text-black/30 line-through'
                                    : ''
                                }`}
                              >
                                {item.ingredient}
                              </div>

                              <div className="mt-1 text-xs text-black/40">
                                {item.quantity} {item.unit}
                                {item.packs
                                  ? ` · ${item.packs} pack${
                                      item.packs > 1 ? 's' : ''
                                    }`
                                  : ''}
                              </div>
                            </div>

                            <div className="text-right">
                              <div className="text-sm font-black">
                                €
                                {Number(
                                  item.total || 0
                                ).toFixed(2)}
                              </div>

                              {item.product?.store && (
                                <div className="mt-1 text-[10px] font-bold uppercase text-black/35">
                                  {item.product.store}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )
            )}
          </div>

          <aside className="h-fit rounded-[28px] bg-black p-6 text-white lg:sticky lg:top-24">
            <div className="flex items-center gap-2 text-white/50">
              <ShoppingBasket size={17} />
              <span className="text-xs font-black uppercase tracking-[0.18em]">
                Optimized total
              </span>
            </div>

            <div className="mt-4 text-5xl font-black tracking-tight">
              €{Number(total).toFixed(2)}
            </div>

            <div className="mt-2 text-sm text-white/45">
              €{Number(costPerServing).toFixed(2)} per serving
            </div>

            <div className="mt-7 space-y-3 border-t border-white/10 pt-5">
              <div className="flex justify-between text-sm">
                <span className="text-white/45">Items</span>
                <span className="font-bold">{basket.length}</span>
              </div>

              <div className="flex justify-between text-sm">
                <span className="text-white/45">Already have</span>
                <span className="font-bold">{owned.length}</span>
              </div>
            </div>

            <div className="mt-7 rounded-2xl bg-white/10 p-4">
              <div className="text-xs font-black">
                Smart shopping
              </div>

              <p className="mt-2 text-xs leading-5 text-white/45">
                Ingredients are consolidated across your selected meals
                so you avoid unnecessary duplicate purchases.
              </p>
            </div>
          </aside>
        </div>
      )}
    </section>
  );
}

function groupedFromBasket(basket: Basket[]) {
  const groups: Record<string, Basket[]> = {
    Produce: [],
    Protein: [],
    Pantry: [],
    Dairy: [],
    Other: [],
  };

  basket.forEach((item) => {
    const name = item.ingredient.toLowerCase();

    if (
      name.includes('chicken') ||
      name.includes('beef') ||
      name.includes('salmon') ||
      name.includes('tofu') ||
      name.includes('egg') ||
      name.includes('tuna')
    ) {
      groups.Protein.push(item);
    } else if (
      name.includes('milk') ||
      name.includes('yogurt') ||
      name.includes('cheese')
    ) {
      groups.Dairy.push(item);
    } else if (
      name.includes('tomato') ||
      name.includes('onion') ||
      name.includes('pepper') ||
      name.includes('carrot') ||
      name.includes('spinach') ||
      name.includes('broccoli') ||
      name.includes('avocado') ||
      name.includes('lettuce')
    ) {
      groups.Produce.push(item);
    } else if (
      name.includes('rice') ||
      name.includes('pasta') ||
      name.includes('flour') ||
      name.includes('oil') ||
      name.includes('salt') ||
      name.includes('sauce') ||
      name.includes('spice')
    ) {
      groups.Pantry.push(item);
    } else {
      groups.Other.push(item);
    }
  });

  return groups;
}

function MealSkeletonGrid() {
  return (
    <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
      {[1, 2, 3, 4, 5, 6].map((item) => (
        <div
          key={item}
          className="overflow-hidden rounded-[28px] bg-white"
        >
          <div className="skeleton aspect-[4/3]" />
          <div className="space-y-3 p-5">
            <div className="skeleton h-6 w-3/4 rounded-lg" />
            <div className="skeleton h-4 w-full rounded-lg" />
            <div className="skeleton h-4 w-2/3 rounded-lg" />
            <div className="skeleton h-11 w-full rounded-2xl" />
          </div>
        </div>
      ))}
    </div>
  );
}

function MobileNav({
  tab,
  setTab,
  selectedCount,
}: {
  tab: 'discover' | 'picks' | 'shopping';
  setTab: React.Dispatch<
    React.SetStateAction<'discover' | 'picks' | 'shopping' | 'pantry' | 'rewe'>
  >;
  selectedCount: number;
}) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-50 border-t border-black/5 bg-white/95 px-4 py-3 backdrop-blur-xl md:hidden">
      <div className="mx-auto flex max-w-md items-center justify-around">
        <MobileNavButton
          active={tab === 'discover'}
          onClick={() => setTab('discover')}
          icon={<Sparkles size={19} />}
          label="Discover"
        />

        <MobileNavButton
          active={tab === 'picks'}
          onClick={() => setTab('picks')}
          icon={<Heart size={19} />}
          label="Picks"
          count={selectedCount}
        />

        <MobileNavButton
          active={tab === 'shopping'}
          onClick={() => setTab('shopping')}
          icon={<ShoppingBasket size={19} />}
          label="Basket"
        />
      </div>
    </div>
  );
}

function MobileNavButton({
  active,
  onClick,
  icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`relative flex min-w-20 flex-col items-center gap-1 text-[10px] font-bold ${
        active ? 'text-black' : 'text-black/35'
      }`}
    >
      {icon}
      {label}

      {count !== undefined && count > 0 && (
        <span className="absolute right-2 top-[-4px] flex h-4 min-w-4 items-center justify-center rounded-full bg-black px-1 text-[9px] text-white">
          {count}
        </span>
      )}
    </button>
  );
}

function RewePage(){const [data,setData]=useState<any>(null);const [busy,setBusy]=useState(false);const load=async()=>setData(await api('/rewe/status'));useEffect(()=>{load()},[]);const refresh=async()=>{setBusy(true);try{await api('/rewe/refresh',{method:'POST'});await load()}finally{setBusy(false)}};return <section className="mx-auto max-w-2xl"><div className="rounded-[28px] bg-white p-7 shadow-sm"><div className="text-xs font-black uppercase tracking-[.18em] text-black/40">REWE data</div><h1 className="mt-2 text-3xl font-black">Catalog status</h1><div className="mt-6 grid grid-cols-2 gap-4"><div>Postcode <b className="block">{data?.postcode || '13353'}</b></div><div>Products <b className="block">{data?.products || 0}</b></div><div>Status <b className="block">{data?.status || 'Not refreshed'}</b></div><div>Errors <b className="block">{data?.errors || 0}</b></div></div><p className="mt-6 text-sm text-black/45">Manual catalog snapshot. Prices and availability are not live.</p><button onClick={refresh} disabled={busy} className="mt-5 rounded-2xl bg-black px-5 py-3 text-sm font-bold text-white">{busy ? 'Updating...' : 'Update REWE catalog'}</button></div></section>}
function PantryPage(){const [items,setItems]=useState<any[]>([]);const [name,setName]=useState('');const load=async()=>setItems(await api('/pantry'));useEffect(()=>{load()},[]);const add=async()=>{if(!name)return;await api('/pantry',{method:'POST',body:JSON.stringify({ingredient:name,quantity:1,unit:'unit',confidence:'user_confirmed'})});setName('');load()};return <section className="mx-auto max-w-2xl"><div className="rounded-[28px] bg-white p-7 shadow-sm"><div className="text-xs font-black uppercase tracking-[.18em] text-black/40">Pantry</div><h1 className="mt-2 text-3xl font-black">What you have</h1><div className="mt-5 flex gap-2"><input className="flex-1 rounded-xl border border-black/10 px-3 py-2" value={name} onChange={e=>setName(e.target.value)} placeholder="Add ingredient"/><button onClick={add} className="rounded-xl bg-black px-4 text-sm font-bold text-white">Add</button></div><div className="mt-5 space-y-2">{items.map(x=><div key={x.id} className="flex justify-between rounded-xl bg-[#f4f2ed] p-4"><b>{x.ingredient}</b><span>{x.quantity} {x.unit} - {x.confidence}</span></div>)}</div></div></section>}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
