import React, { useEffect, useState } from 'react';
import { Database, RefreshCw, X } from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

type ReweStatus = {
  products?: number;
  status?: string;
  postcode?: string;
  categories_successful?: number;
  categories_processed?: number;
  categories_failed?: number;
  errors?: number;
  last_updated?: string;
  fetch_mode?: string;
};

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

export default function ReweCatalogControl() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<ReweStatus | null>(null);
  const [postcode, setPostcode] = useState('13353');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    loadStatus().catch(() => undefined);
  }, []);

  async function loadStatus() {
    const [nextStatus, settings] = await Promise.all([
      api('/rewe/status'),
      api('/settings'),
    ]);
    setStatus(nextStatus);
    setPostcode(settings.postcode || nextStatus.postcode || '13353');
  }

  async function savePostcode() {
    if (!/^\d{5}$/.test(postcode)) {
      setError('Postcode must be 5 digits.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await api('/settings', {
        method: 'PATCH',
        body: JSON.stringify({ postcode }),
      });
      await loadStatus();
    } catch (err: any) {
      setError(err?.message || 'Could not save postcode.');
    } finally {
      setLoading(false);
    }
  }

  async function refreshCatalog() {
    setLoading(true);
    setError('');
    try {
      await api('/rewe/refresh', { method: 'POST' });
      await loadStatus();
    } catch (err: any) {
      setError(err?.message || 'REWE refresh failed.');
    } finally {
      setLoading(false);
    }
  }

  const categories = `${status?.categories_successful || 0}/${status?.categories_processed || 0}`;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-36 right-5 z-[70] flex items-center gap-2 rounded-full bg-[#2f6b4f] px-4 py-3 text-xs font-black text-white shadow-xl transition hover:-translate-y-0.5 hover:shadow-2xl md:bottom-20"
        title="REWE catalog"
        aria-label="Open REWE catalog controls"
      >
        <Database size={15} />
        REWE catalog
        {status?.products ? <span className="rounded-full bg-white/15 px-2 py-0.5">{status.products}</span> : null}
      </button>

      {open && (
        <div className="fixed inset-0 z-[90] overflow-y-auto bg-black/50 p-4" onClick={() => setOpen(false)}>
          <div
            className="mx-auto mt-10 max-w-2xl rounded-[30px] bg-[#f7f4ee] p-6 shadow-2xl"
            onClick={event => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-xs font-black uppercase tracking-[.18em] text-[#18392b]/35">Laptop maintenance</div>
                <h2 className="mt-1 text-3xl font-black text-[#17211b]">REWE data</h2>
                <p className="mt-1 text-sm text-[#18392b]/50">Manage the durable REWE snapshot stored by the backend. Phones only consume the results they need and never download the full catalog.</p>
              </div>
              <button onClick={() => setOpen(false)} className="rounded-full bg-white p-2 shadow-sm"><X size={17} /></button>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Products" value={status?.products || 0} />
              <Stat label="Status" value={status?.status || '—'} />
              <Stat label="Postcode" value={status?.postcode || postcode} />
              <Stat label="Categories" value={categories} />
            </div>

            <div className="mt-5 rounded-[22px] bg-white p-5 shadow-sm">
              <div className="font-black">Delivery postcode</div>
              <div className="mt-1 text-xs text-[#18392b]/45">Changing postcode updates catalog context. Refresh afterwards only when you intentionally want a new snapshot.</div>
              <div className="mt-3 flex gap-2">
                <input
                  value={postcode}
                  maxLength={5}
                  inputMode="numeric"
                  onChange={event => setPostcode(event.target.value.replace(/\D/g, '').slice(0, 5))}
                  className="min-w-0 flex-1 rounded-xl bg-[#f3f1eb] px-3 py-2.5 text-sm outline-none"
                />
                <button onClick={savePostcode} disabled={loading} className="rounded-xl bg-[#18392b] px-4 text-sm font-black text-white disabled:opacity-40">Save</button>
              </div>
            </div>

            <div className="mt-4 rounded-[22px] bg-white p-5 shadow-sm">
              <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
                <div>
                  <div className="font-black">Permanent catalog snapshot</div>
                  <div className="mt-1 text-xs text-[#18392b]/45">
                    Last updated: {status?.last_updated ? new Date(status.last_updated).toLocaleString() : 'Never'}
                    {' · '}Errors: {status?.errors || 0}
                    {status?.fetch_mode ? ` · ${status.fetch_mode}` : ''}
                  </div>
                  <div className="mt-1 text-xs text-[#18392b]/45">No automatic refresh is required. Reuse this snapshot for months and refresh manually when you want newer REWE data.</div>
                </div>
                <button
                  onClick={refreshCatalog}
                  disabled={loading}
                  className="flex items-center justify-center gap-2 rounded-xl bg-[#18392b] px-5 py-3 text-sm font-black text-white disabled:opacity-40"
                >
                  <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
                  {loading ? 'Refreshing…' : 'Refresh full catalog'}
                </button>
              </div>
            </div>

            {error && <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm font-bold text-red-700">{error}</div>}
          </div>
        </div>
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-[18px] bg-white p-4 shadow-sm">
      <div className="text-[10px] font-black uppercase tracking-[.14em] text-[#18392b]/35">{label}</div>
      <div className="mt-1 text-xl font-black text-[#17211b]">{String(value)}</div>
    </div>
  );
}
