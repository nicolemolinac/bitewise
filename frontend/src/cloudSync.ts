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

async function pushStateChanges(set: Record<string, unknown>) {
  if (!Object.keys(set).length) return;
  await authed('/user-state/changes', {
    method: 'PUT',
    body: JSON.stringify({ set, delete: [] }),
  });
}

export async function hydrateCloudState() {
  const remote = await authed('/user-state');
  const local = localSnapshot();
  const remoteState = remote?.state || {};
  const deleted = new Set<string>(remote?.deleted_keys || []);
  if (Object.keys(remoteState).length || deleted.size) {
    const merged = mergeCloudState(local, remoteState, [...deleted]);
    applySnapshot(merged);
    // Upload only genuinely local-only keys. Never replace a whole snapshot:
    // another device may have written unrelated keys since this GET started.
    const localOnly: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(local)) {
      if (!(key in remoteState) && !deleted.has(key)) localOnly[key] = value;
    }
    if (Object.keys(localOnly).length) {
      await pushStateChanges(localOnly);
      return 'merged';
    }
    return 'downloaded';
  }
  if (Object.keys(local).length) {
    await pushStateChanges(local);
    return 'uploaded';
  }
  return 'empty';
}

function schedulePendingSync(delayMs: number) {
  if (syncTimer !== null) window.clearTimeout(syncTimer);
  syncTimer = window.setTimeout(async () => {
    syncTimer = null;
    if (syncing) {
      syncRequested = true;
      return;
    }
    syncing = true;
    let failed = false;
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
          failed = true;
          // Retain failed deltas unless a newer local edit for that key exists.
          for (const [key, value] of Object.entries(set)) {
            if (!pendingSet.has(key) && !pendingDelete.has(key)) pendingSet.set(key, value);
          }
          for (const key of del) {
            if (!pendingSet.has(key)) pendingDelete.add(key);
          }
          console.warn('Bitewise cloud sync failed', error);
          break;
        }
      }
    } finally {
      syncing = false;
      if (syncRequested || pendingSet.size || pendingDelete.size) {
        // Back off on network/auth errors instead of retrying every 500 ms.
        schedulePendingSync(failed ? 5000 : 500);
      }
    }
  }, delayMs);
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
  schedulePendingSync(500);
}