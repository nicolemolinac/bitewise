import React, { ChangeEvent, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { CalendarPlus, ExternalLink, ImagePlus, PackagePlus, Plus, Trash2, X } from 'lucide-react';

const K = 'bitewise.v3.';
const DAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

type CustomProduct = {
  id: string;
  name: string;
  brand: string;
  store: string;
  url: string;
  image: string;
  price: number | null;
  category: string;
  notes: string;
};

type CustomSchedule = Record<string, number[]>;

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(K + key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  localStorage.setItem(K + key, JSON.stringify(value));
}

function currentTab() {
  return read<string>('tab', 'discover');
}

function uid() {
  return `custom-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function imageFileToDataUrl(file: File): Promise<string> {
  if (file.size > 1_500_000) throw new Error('Image is too large. Use an image under 1.5 MB.');
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Could not read image.'));
    reader.readAsDataURL(file);
  });
}

export default function CustomProductPlanner() {
  const [tab, setTab] = useState(currentTab);
  const [products, setProducts] = useState<CustomProduct[]>(() => read('customProducts', []));
  const [schedule, setSchedule] = useState<CustomSchedule>(() => read('customProductSchedule', {}));
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState<CustomProduct>({
    id: '', name: '', brand: '', store: 'Amazon', url: '', image: '', price: null, category: 'Coffee', notes: '',
  });

  useEffect(() => {
    const refresh = () => setTab(currentTab());
    window.addEventListener('bitewise:statechange', refresh as EventListener);
    window.addEventListener('storage', refresh);
    return () => {
      window.removeEventListener('bitewise:statechange', refresh as EventListener);
      window.removeEventListener('storage', refresh);
    };
  }, []);

  useEffect(() => save('customProducts', products), [products]);
  useEffect(() => save('customProductSchedule', schedule), [schedule]);

  const todayIndex = (new Date().getDay() + 6) % 7;
  const todayProducts = useMemo(
    () => products.filter(product => (schedule[product.id] || []).includes(todayIndex)),
    [products, schedule, todayIndex],
  );

  async function chooseImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      setError('');
      const image = await imageFileToDataUrl(file);
      setDraft(current => ({ ...current, image }));
    } catch (err: any) {
      setError(err?.message || 'Could not use this image.');
    }
  }

  function addProduct() {
    const name = draft.name.trim();
    if (!name) {
      setError('Product name is required.');
      return;
    }
    const product = { ...draft, id: uid(), name, store: draft.store.trim() || 'Other' };
    setProducts(current => [...current, product]);
    setSchedule(current => ({ ...current, [product.id]: [] }));
    setDraft({ id: '', name: '', brand: '', store: 'Amazon', url: '', image: '', price: null, category: 'Coffee', notes: '' });
    setError('');
    setOpen(false);
  }

  function toggleDay(productId: string, day: number) {
    setSchedule(current => {
      const days = current[productId] || [];
      const next = days.includes(day) ? days.filter(value => value !== day) : [...days, day].sort();
      return { ...current, [productId]: next };
    });
  }

  function removeProduct(productId: string) {
    setProducts(current => current.filter(product => product.id !== productId));
    setSchedule(current => {
      const next = { ...current };
      delete next[productId];
      return next;
    });
  }

  const host = typeof document !== 'undefined' ? document.querySelector('main') : null;
  if (!host || (tab !== 'plan' && tab !== 'today')) return null;

  return createPortal(
    <>
      {tab === 'plan' && (
        <section className="mt-6 rounded-[28px] bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-xs font-black uppercase tracking-[.16em] text-[#18392b]/35">Outside REWE</div>
              <h2 className="mt-1 text-2xl font-black text-[#17211b]">Custom products</h2>
              <p className="mt-1 text-sm text-[#18392b]/50">Coffee pods, supplements, snacks or anything you buy from Amazon, DM or another shop.</p>
            </div>
            <button onClick={() => setOpen(true)} className="inline-flex items-center gap-2 rounded-xl bg-[#18392b] px-4 py-3 text-sm font-black text-white">
              <Plus size={15}/> Add product
            </button>
          </div>

          {products.length ? (
            <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {products.map(product => (
                <article key={product.id} className="overflow-hidden rounded-[24px] bg-[#f7f4ee]">
                  <div className="aspect-[16/9] bg-[#ece8df]">
                    {product.image ? <img src={product.image} alt={product.name} className="h-full w-full object-cover"/> : <div className="grid h-full place-items-center text-[#18392b]/25"><PackagePlus size={38}/></div>}
                  </div>
                  <div className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-[.14em] text-[#18392b]/35">{product.category || 'Custom'} · {product.store}</div>
                        <div className="mt-1 font-black">{product.name}</div>
                        <div className="text-xs text-[#18392b]/45">{product.brand}{product.price != null ? `${product.brand ? ' · ' : ''}€${product.price.toFixed(2)}` : ''}</div>
                      </div>
                      <button onClick={() => removeProduct(product.id)} className="rounded-lg bg-white p-2 text-[#18392b]/45" aria-label={`Remove ${product.name}`}><Trash2 size={14}/></button>
                    </div>
                    {product.notes && <p className="mt-3 text-xs text-[#18392b]/55">{product.notes}</p>}
                    <div className="mt-4 text-[10px] font-black uppercase tracking-[.14em] text-[#18392b]/35">Add to calendar</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {DAYS.map((day, index) => {
                        const active = (schedule[product.id] || []).includes(index);
                        return <button key={day} onClick={() => toggleDay(product.id, index)} className={`rounded-full px-2.5 py-1.5 text-xs font-black ${active ? 'bg-[#18392b] text-white' : 'bg-white text-[#18392b]/45'}`}>{day}</button>;
                      })}
                    </div>
                    {product.url && <a href={product.url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1 text-xs font-black text-[#18392b] underline">Open product <ExternalLink size={12}/></a>}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <button onClick={() => setOpen(true)} className="mt-5 flex w-full items-center justify-center gap-2 rounded-[22px] border border-dashed border-[#18392b]/15 p-8 text-sm font-black text-[#18392b]/45">
              <CalendarPlus size={18}/> Add your first non-REWE product
            </button>
          )}
        </section>
      )}

      {tab === 'today' && todayProducts.length > 0 && (
        <section className="mt-6">
          <div className="mb-3 text-xs font-black uppercase tracking-[.16em] text-[#18392b]/35">Also today</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {todayProducts.map(product => (
              <article key={product.id} className="flex overflow-hidden rounded-[22px] bg-white shadow-sm">
                <div className="h-28 w-28 shrink-0 bg-[#ece8df]">{product.image ? <img src={product.image} alt={product.name} className="h-full w-full object-cover"/> : <div className="grid h-full place-items-center text-[#18392b]/20"><PackagePlus/></div>}</div>
                <div className="min-w-0 flex-1 p-4">
                  <div className="text-[10px] font-black uppercase tracking-[.14em] text-[#18392b]/35">{product.category} · {product.store}</div>
                  <div className="mt-1 truncate font-black">{product.name}</div>
                  {product.notes && <div className="mt-1 line-clamp-2 text-xs text-[#18392b]/45">{product.notes}</div>}
                  {product.url && <a href={product.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs font-black underline">Open <ExternalLink size={11}/></a>}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {open && (
        <div className="fixed inset-0 z-[100] overflow-y-auto bg-black/50 p-4" onClick={() => setOpen(false)}>
          <div className="mx-auto mt-8 max-w-xl rounded-[30px] bg-[#f7f4ee] p-5 shadow-2xl sm:p-6" onClick={event => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <div><div className="text-xs font-black uppercase tracking-[.16em] text-[#18392b]/35">Personal product</div><h2 className="mt-1 text-2xl font-black">Add custom product</h2></div>
              <button onClick={() => setOpen(false)} className="rounded-full bg-white p-2"><X size={17}/></button>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-black text-[#18392b]/55 sm:col-span-2">Product name<input value={draft.name} onChange={e => setDraft({...draft, name:e.target.value})} placeholder="Nescafé Dolce Gusto Cappuccino pods" className="mt-1 w-full rounded-xl bg-white px-3 py-3 text-sm outline-none"/></label>
              <label className="text-xs font-black text-[#18392b]/55">Brand<input value={draft.brand} onChange={e => setDraft({...draft, brand:e.target.value})} placeholder="Nescafé" className="mt-1 w-full rounded-xl bg-white px-3 py-3 text-sm outline-none"/></label>
              <label className="text-xs font-black text-[#18392b]/55">Store<input value={draft.store} onChange={e => setDraft({...draft, store:e.target.value})} placeholder="Amazon" className="mt-1 w-full rounded-xl bg-white px-3 py-3 text-sm outline-none"/></label>
              <label className="text-xs font-black text-[#18392b]/55">Category<select value={draft.category} onChange={e => setDraft({...draft, category:e.target.value})} className="mt-1 w-full rounded-xl bg-white px-3 py-3 text-sm outline-none"><option>Coffee</option><option>Drink</option><option>Snack</option><option>Breakfast</option><option>Supplement</option><option>Household</option><option>Other</option></select></label>
              <label className="text-xs font-black text-[#18392b]/55">Price (€)<input type="number" min="0" step="0.01" value={draft.price ?? ''} onChange={e => setDraft({...draft, price:e.target.value === '' ? null : Number(e.target.value)})} className="mt-1 w-full rounded-xl bg-white px-3 py-3 text-sm outline-none"/></label>
              <label className="text-xs font-black text-[#18392b]/55 sm:col-span-2">Product link<input value={draft.url} onChange={e => setDraft({...draft, url:e.target.value})} placeholder="https://www.amazon.de/..." className="mt-1 w-full rounded-xl bg-white px-3 py-3 text-sm outline-none"/></label>
              <label className="text-xs font-black text-[#18392b]/55 sm:col-span-2">Image URL<input value={draft.image.startsWith('data:') ? '' : draft.image} onChange={e => setDraft({...draft, image:e.target.value})} placeholder="https://.../product-image.jpg" className="mt-1 w-full rounded-xl bg-white px-3 py-3 text-sm outline-none"/></label>
              <label className="sm:col-span-2 flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-[#18392b]/15 bg-white px-4 py-4 text-sm font-black text-[#18392b]/55"><ImagePlus size={16}/> Upload image from phone/laptop<input type="file" accept="image/*" onChange={chooseImage} className="hidden"/></label>
              {draft.image && <div className="sm:col-span-2 overflow-hidden rounded-2xl bg-white"><img src={draft.image} alt="Product preview" className="h-44 w-full object-cover"/></div>}
              <label className="text-xs font-black text-[#18392b]/55 sm:col-span-2">Notes<input value={draft.notes} onChange={e => setDraft({...draft, notes:e.target.value})} placeholder="1 capsule every morning" className="mt-1 w-full rounded-xl bg-white px-3 py-3 text-sm outline-none"/></label>
            </div>
            {error && <div className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-sm font-bold text-red-700">{error}</div>}
            <button onClick={addProduct} className="mt-5 w-full rounded-xl bg-[#18392b] px-5 py-3.5 text-sm font-black text-white">Save product</button>
          </div>
        </div>
      )}
    </>,
    host,
  );
}
