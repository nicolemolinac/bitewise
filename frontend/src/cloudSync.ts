import { getAccessToken } from './auth';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const PREFIX = 'bitewise.v3.';
let syncTimer: number | null = null;
let syncing = false;

function localSnapshot() {
  const state: Record<string, unknown> = {};
  for (let i = 0; i < window.localStorage.length; i++) {
    const key = window.localStorage.key(i);
    if (!key || !key.startsWith(PREFIX)) continue;
    try {
      state[key.slice(PREFIX.length)] = JSON.parse(window.localStorage.getItem(key) || 'null');
    } catch {
      state[key.slice(PREFIX.length)] = window.localStorage.getItem(key);
    }
  }
  return state;
}

function applySnapshot(state: Record<string, unknown>) {
  for (const [key, value] of Object.entries(state || {})) {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  }
}

async function authed(path: string, options?: RequestInit) {
  const token = await getAccessToken();
  const r = await fetch(API + path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers || {}),
    },
  });
  if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
  return r.json();
}

export async function hydrateCloudState() {
  const remote = await authed('/user-state');
  if (remote?.state && Object.keys(remote.state).length) {
    applySnapshot(remote.state);
    return 'downloaded';
  }
  const state = localSnapshot();
  if (Object.keys(state).length) {
    await authed('/user-state', { method: 'PUT', body: JSON.stringify({ state }) });
    return 'uploaded';
  }
  return 'empty';
}

export function queueCloudSync() {
  if (syncTimer) window.clearTimeout(syncTimer);
  syncTimer = window.setTimeout(async () => {
    if (syncing) return;
    syncing = true;
    try {
      await authed('/user-state', {
        method: 'PUT',
        body: JSON.stringify({ state: localSnapshot() }),
      });
    } catch (error) {
      console.warn('Bitewise cloud sync failed', error);
    } finally {
      syncing = false;
    }
  }, 500);
}
