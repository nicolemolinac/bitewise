import AppV3 from './AppV3';
import AuthGate from './AuthGate';
import { authConfigured, getAccessToken } from './auth';
import { isCloudStateKey, queueCloudSync } from './cloudSync';

const V2 = 'bitewise.v2.';
const V3 = 'bitewise.v3.';
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

// Preserve the user's existing V2 choices the first time V3 opens.
if (typeof window !== 'undefined') {
  const keys = ['tab','liked','skipped','mealType','filter','brain','appliances','basket','summary','strategy','owned'];
  for (const key of keys) {
    const next = window.localStorage.getItem(V3 + key);
    const previous = window.localStorage.getItem(V2 + key);
    if (next == null && previous != null) window.localStorage.setItem(V3 + key, previous);
  }

  // Keep the existing network contract while also attaching the Supabase session to
  // every Bitewise API call when cloud auth is enabled.
  const marker = '__bitewiseAdaptiveFetchPatched__';
  const w = window as typeof window & Record<string, unknown>;
  if (!w[marker]) {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      try {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
        if (url.endsWith('/api/shopping') && typeof init?.body === 'string') {
          const payload = JSON.parse(init.body);
          if (payload?.servings && typeof payload.servings === 'object') {
            payload.servings = Object.fromEntries(
              Object.entries(payload.servings).map(([id, value]) => [id, Math.max(1, Math.round(Number(value) || 1))]),
            );
            init = { ...init, body: JSON.stringify(payload) };
          }
        }
        if (authConfigured && url.startsWith(API)) {
          const token = await getAccessToken();
          if (token) {
            const headers = new Headers(init?.headers || {});
            headers.set('Authorization', `Bearer ${token}`);
            init = { ...init, headers };
          }
        }
      } catch {
        // Leave unrelated requests untouched.
      }
      return originalFetch(input, init);
    };
    w[marker] = true;
  }

  // AppV3 persists user choices through localStorage. Only keys explicitly approved
  // for cross-device state are uploaded. REWE catalog/cache data stays server-side.
  const syncMarker = '__bitewiseCloudStoragePatched__';
  if (!w[syncMarker]) {
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key: string, value: string) {
      originalSetItem.call(this, key, value);
      if (this === window.localStorage && isCloudStateKey(key)) queueCloudSync();
    };
    w[syncMarker] = true;
  }
}

export default function AppV3Entry() {
  return <AuthGate><AppV3 /></AuthGate>;
}
