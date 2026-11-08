import { getAccessToken } from './auth';
import { acknowledgePendingChanges, restorePending, serializePending } from './cloudPending.js';
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
const PENDING_STORAGE_KEY = 'bitewise.internal.cloudPending.v1';

function persistPendingState() {
  try {
    const serialized = serializePending(pendingSet, pendingDelete);
    if (serialized === null) window.localStorage.removeItem(PENDING_STORAGE_KEY);
    else window.localStorage.setItem(PENDING_STORAGE_KEY, serialized);
  } catch (error) {
    console.warn('Bitewise could not persist pending cloud changes', error);
  }
}

try {
  const restored = restorePending(
    window.localStorage.getItem(PENDING_STORAGE_KEY),
    key => isCloudStateKey(PREFIX + key),
  );
  for (const [key, value] of restored.set) pendingSet.set(key, value);
  for (const key of restored.deleted) pendingDelete.add(key);
} catch (error) {
  console.warn('Bitewise could not restore pending cloud changes', error);
}

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

async function pushStateChanges(set: Record<string, unknown>, deleted: string[] = []) {
  if (!Object.keys(set).length && !deleted.length) return;
  await authed('/user-state/changes', {
    method: 'PUT',
    body: JSON.stringify({ set, delete: deleted }),
  });
}

function acknowledgePending(sentSet: Record<string, unknown>, sentDelete: string[]) {
  acknowledgePendingChanges(pendingSet, pendingDelete, sentSet, sentDelete);
  persistPendingState();
}

export async function hydrateCloudState() {
  let remote;
  try {
    remote = await authed('/user-state');
  } catch (error) {
    // Pending edits restored from a previous page session must keep retrying even
    // when the initial read fails (offline, expired session or transient API error).
    if (pendingSet.size || pendingDelete.size) schedulePendingSync(5000);
    throw error;
  }
  const local = localSnapshot();
  const remoteState = remote?.state || {};
  const deleted = new Set<string>(remote?.deleted_keys || []);
  const unsyncedSet = Object.fromEntries(pendingSet);
  const unsyncedDelete = [...pendingDelete];
  const merged = mergeCloudState(local, remoteState, [...deleted]);
  // A locally queued edit is newer than the last successful cloud snapshot.
  Object.assign(merged, unsyncedSet);
  for (const key of unsyncedDelete) delete merged[key];
  applySnapshot(merged);

  // Upload only genuinely local-only keys plus durable pending edits. Never
  // replace a whole snapshot: another device may have written other keys.
  const changes: Record<string, unknown> = { ...unsyncedSet };
  for (const [key, value] of Object.entries(local)) {
    if (!(key in remoteState) && !deleted.has(key) && !(key in unsyncedSet) && !pendingDelete.has(key)) {
      changes[key] = value;
    }
  }
  const hadRemote = Object.keys(remoteState).length > 0 || deleted.size > 0;
  const hadLocal = Object.keys(local).length > 0;
  if (Object.keys(changes).length || unsyncedDelete.length) {
    // Promote local-only keys into the durable queue before attempting network I/O.
    // Otherwise a failed first upload would leave them only in memory/localStorage
    // and they could be lost when the page closes before the next successful sync.
    for (const [key, value] of Object.entries(changes)) {
      pendingSet.set(key, value);
      pendingDelete.delete(key);
    }
    persistPendingState();
    try {
      await pushStateChanges(changes, unsyncedDelete);
      acknowledgePending(changes, unsyncedDelete);
    } catch (error) {
      schedulePendingSync(5000);
      throw error;
    }
    return hadRemote ? 'merged' : 'uploaded';
  }
  return hadRemote ? 'downloaded' : (hadLocal ? 'empty' : 'empty');
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
        try {
          await authed('/user-state/changes', {
            method: 'PUT',
            body: JSON.stringify({ set, delete: del }),
          });
          // Acknowledge only the exact values sent. Newer edits made while the
          // request was in flight remain queued for the next delta.
          acknowledgePendingChanges(pendingSet, pendingDelete, set, del);
          persistPendingState();
        } catch (error) {
          failed = true;
          persistPendingState();
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
      persistPendingState();
    } else {
      try {
        pendingSet.set(key, JSON.parse(rawValue ?? "null"));
      } catch {
        pendingSet.set(key, rawValue ?? "");
      }
      pendingDelete.delete(key);
      persistPendingState();
    }
  } else if (!storageKey) {
    // Compatibility for existing callers: queue a full allowlisted snapshot as
    // per-key updates rather than replacing another device's unrelated keys.
    for (const [key, value] of Object.entries(localSnapshot())) {
      pendingSet.set(key, value);
      pendingDelete.delete(key);
    }
    persistPendingState();
  }
  syncRequested = true;
  schedulePendingSync(500);
}