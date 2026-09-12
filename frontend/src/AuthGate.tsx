import { useEffect, useState, type ReactNode } from 'react';
import type { Session } from '@supabase/supabase-js';
import { authConfigured, setCurrentSession, signInWithGoogle, signOut, supabase } from './auth';
import { hydrateCloudState } from './cloudSync';

export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(!authConfigured);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!supabase) return;
    let alive = true;
    supabase.auth.getSession().then(async ({ data }) => {
      if (!alive) return;
      setSession(data.session);
      setCurrentSession(data.session);
      if (data.session) {
        try { await hydrateCloudState(); } catch (e: any) { setError(e.message || 'Cloud sync failed'); }
      }
      if (alive) setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange(async (_event, next) => {
      setSession(next);
      setCurrentSession(next);
      if (next) {
        setReady(false);
        try { await hydrateCloudState(); } catch (e: any) { setError(e.message || 'Cloud sync failed'); }
        setReady(true);
      }
    });
    return () => { alive = false; sub.subscription.unsubscribe(); };
  }, []);

  if (!authConfigured) return <>{children}</>;
  if (!ready) return <div className="min-h-dvh grid place-items-center bg-[#f6f4ef] text-[#171916]"><div className="text-center"><div className="mx-auto h-12 w-12 animate-pulse rounded-2xl bg-[#203d2f]"/><div className="mt-4 text-sm font-black">Syncing Bitewise…</div></div></div>;
  if (!session) return <div className="min-h-dvh bg-[#f6f4ef] px-5 py-10 text-[#171916]"><div className="mx-auto flex min-h-[80dvh] max-w-md flex-col justify-between rounded-[32px] bg-[#203d2f] p-7 text-white shadow-2xl"><div><div className="text-xs font-black uppercase tracking-[.18em] text-white/45">Bitewise</div><h1 className="mt-3 text-4xl font-black leading-[.95]">Your food life,<br/>synced everywhere.</h1><p className="mt-4 max-w-sm text-sm leading-6 text-white/65">Use the same Bitewise on your laptop and phone. Picks, pantry, plans, basket and settings stay in sync.</p></div><div><button onClick={()=>signInWithGoogle().catch(e=>setError(e.message))} className="w-full rounded-2xl bg-white px-5 py-4 text-sm font-black text-[#203d2f]">Continue with Google</button>{error&&<div className="mt-3 rounded-xl bg-red-500/15 p-3 text-xs font-bold text-red-100">{error}</div>}<div className="mt-3 text-center text-[11px] text-white/35">Private personal app · one account</div></div></div></div>;

  return <div>{children}<button onClick={()=>signOut()} className="fixed right-3 top-[calc(10px+env(safe-area-inset-top))] z-[90] hidden rounded-full bg-black/5 px-3 py-2 text-[10px] font-black text-black/45 md:block">Sign out</button></div>;
}
