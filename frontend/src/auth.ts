import { createClient, type Session } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL || '';
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || '';

export const authConfigured = Boolean(url && key);
export const supabase = authConfigured ? createClient(url, key) : null;

let currentSession: Session | null = null;

export function setCurrentSession(session: Session | null) {
  currentSession = session;
}

export async function getAccessToken() {
  if (!supabase) return null;
  if (currentSession?.access_token) return currentSession.access_token;
  const { data } = await supabase.auth.getSession();
  currentSession = data.session;
  return data.session?.access_token || null;
}

export async function signInWithGoogle() {
  if (!supabase) throw new Error('Supabase is not configured.');
  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: window.location.origin },
  });
  if (error) throw error;
}

export async function signOut() {
  if (!supabase) return;
  await supabase.auth.signOut();
  currentSession = null;
}
