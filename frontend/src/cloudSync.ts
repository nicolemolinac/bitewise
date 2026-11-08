import { getAccessToken } from './auth';
import { CLOUD_STATE_KEYS, createCloudStateSnapshot, isCloudStateKey, mergeCloudState } from './cloudState.js';
export { CLOUD_STATE_KEYS, isCloudStateKey } from './cloudState.js';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const PREFIX = 'bitewise.v3.';

let syncTimer: number | null = null;
let syncing = false;
let syncRequested = false;
let applyingRemoteSnapshot = false;
const pendingSet = new Map<string, unknown>();
const pendingDelete = new Set<string>();

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
  applyingRemoteSnapshot = true;
  try {
    const acceptedKeys = new Set(Object.keys(state || {}).filter(key => isCloudStateKey(PREFIX + key)));
    for (const [key] of Object.entries(localSnapshot())) {
      if (!acceptedKeys.has(key)) window.localStorage.removeItem(PREFIX + key);
    }
    for (const [key, value] of Object.entries(state || {})) {
      if (!isCloudStateKey(PREFIX + key)) continue;
      window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
    }
  } finally {
    applyingRemoteSnapshot = false;
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
  if (remote?.state && (Object.keys(remote.state).length || (remote.deleted_keys || []).length)) {
    const merged = mergeCloudState(local, remote.state, remote.deleted_keys || []);
    applySnapshot(merged);
    const deleted = new Set(remote.deleted_keys || []);
    const hasLocalOnlyState = Object.keys(local).some(key => !(key in remote.state) && !deleted.has(key));
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

export function queueCloudSync(storageKey?: string, rawValue?: string, deleted = false) {
  if (applyingRemoteSnapshot) return;
  if (storageKey && isCloudStateKey(storageKey)) {
    const key = storageKey.slice(PREFIX.length);
    if (deleted) {
      pendingSet.delete(key);
      pendingDelete.add(key);
    } else {
      try {
        pendingSet.set(key, JSON.parse(rawValue ?? "null"));
      } catch {
        pendingSet.set(key, rawValue ?? "");
      }
      pendingDelete.delete(key);
    }
  } else if (!storageKey) {
    // Compatibility for existing callers: queue a full allowlisted snapshot as
    // per-key updates rather than replacing another device's unrelated keys.
    for (const [key, value] of Object.entries(localSnapshot())) {
      pendingSet.set(key, value);
      pendingDelete.delete(key);
    }
  }
  syncRequested = true;
  if (syncTimer !== null) window.clearTimeout(syncTimer);
  syncTimer = window.setTimeout(async () => {
    syncTimer = null;
    if (syncing) return;
    syncing = true;
    try {
      while (syncRequested || pendingSet.size || pendingDelete.size) {
        syncRequested = false;
        const set = Object.fromEntries(pendingSet);
        const del = Array.from(pendingDelete);
        pendingSet.clear();
        pendingDelete.clear();
        try {
          await authed('/user-state/changes', {
            method: 'PUT',
            body: JSON.stringify({ set, delete: del }),
          });
        } catch (error) {
          // Retain failed deltas unless a newer local edit for that key exists.
          for (const [key, value] of Object.entries(set)) {
            if (!pendingSet.has(key) && !pendingDelete.has(key)) pendingSet.set(key, value);
          }
          for (const key of del) {
            if (!pendingSet.has(key)) pendingDelete.add(key);
          }
          throw error;
        }
      }
    } catch (error) {
      console.warn('Bitewise cloud sync failed', error);
    } finally {
      syncing = false;
      if (syncRequested || pendingSet.size || pendingDelete.size) queueCloudSync();
    }
  }, 500);
}
