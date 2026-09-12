import { getAccessToken } from './auth';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const PREFIX = 'bitewise.v3.';

// Only personal/UI state is allowed to travel between devices. The REWE product
// catalog remains server-side in Postgres and is queried on demand by the app.
// This explicit allowlist prevents a future catalog/cache key from accidentally
// copying thousands of products into phone localStorage.
export const CLOUD_STATE_KEYS = new Set([
  'tab',
  'liked',
  'skipped',
  'mealType',
  'filter',
  'brain',
  'appliances',
  'profile',
  'dayContexts',
  'calendarView',
  'extras',
  'basket',
  'summary',
  'strategy',
  'owned',
  'customProducts',
  'customProductSchedule',
]);

let syncTimer: number | null = null;
let syncing = false;

function localSnapshot() {
  const state: Record<string, unknown> = {};
  for (const key of CLOUD_STATE_KEYS) {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw == null) continue;
    try {
      state[key] = JSON.parse(raw);
    } catch {
      state[key] = raw;
    }
  }
  return state;
}

function applySnapshot(state: Record<string, unknown>) {
  for (const [key, value] of Object.entries(state || {})) {
    if (!CLOUD_STATE_KEYS.has(key)) continue;
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  }
}

export function isCloudStateKey(storageKey: string) {
  if (!storageKey.startsWith(PREFIX)) return false;
  return CLOUD_STATE_KEYS.has(storageKey.slice(PREFIX.length));
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
