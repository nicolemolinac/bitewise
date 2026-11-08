import { getAccessToken } from './auth';
import { CLOUD_STATE_KEYS, createCloudStateSnapshot, isCloudStateKey, mergeCloudState } from './cloudState.js';
export { CLOUD_STATE_KEYS, isCloudStateKey } from './cloudState.js';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const PREFIX = 'bitewise.v3.';

let syncTimer: number | null = null;
let syncing = false;
let syncRequested = false;

function localSnapshot() {
  const entries: Array<[string, string | null]> = [];
  // Iterate actual localStorage keys so dynamic Cooking Mode sessions are included.
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const storageKey = window.localStorage.key(index);
    if (!storageKey) continue;
    entries.push([storageKey, window.localStorage.getItem(storageKey)]);
  }
  return createCloudStateSnapshot(entries, PREFIX);
}

function applySnapshot(state: Record<string, unknown>) {
  for (const [key, value] of Object.entries(state || {})) {
    if (!isCloudStateKey(PREFIX + key)) continue;
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
  const local = localSnapshot();
  if (remote?.state && Object.keys(remote.state).length) {
    const merged = mergeCloudState(local, remote.state);
    applySnapshot(merged);
    const hasLocalOnlyState = Object.keys(local).some(key => !(key in remote.state));
    if (hasLocalOnlyState) {
      await authed('/user-state', { method: 'PUT', body: JSON.stringify({ state: merged }) });
      return 'merged';
    }
    return 'downloaded';
  }
  if (Object.keys(local).length) {
    await authed('/user-state', { method: 'PUT', body: JSON.stringify({ state: local }) });
    return 'uploaded';
  }
  return 'empty';
}

export function queueCloudSync() {
  syncRequested = true;
  if (syncTimer !== null) window.clearTimeout(syncTimer);
  syncTimer = window.setTimeout(async () => {
    syncTimer = null;
    if (syncing) return;
    syncing = true;
    try {
      // If local state changes while a request is in flight, send a fresh
      // snapshot after it completes rather than silently dropping that change.
      while (syncRequested) {
        syncRequested = false;
        await authed('/user-state', {
          method: 'PUT',
          body: JSON.stringify({ state: localSnapshot() }),
        });
      }
    } catch (error) {
      console.warn('Bitewise cloud sync failed', error);
    } finally {
      syncing = false;
      if (syncRequested) queueCloudSync();
    }
  }, 500);
}
