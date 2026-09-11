import AppV3 from './AppV3';

const V2 = 'bitewise.v2.';
const V3 = 'bitewise.v3.';

// Preserve the user's existing V2 choices the first time V3 opens.
if (typeof window !== 'undefined') {
  const keys = ['tab','liked','skipped','mealType','filter','brain','appliances','basket','summary','strategy','owned'];
  for (const key of keys) {
    const next = window.localStorage.getItem(V3 + key);
    const previous = window.localStorage.getItem(V2 + key);
    if (next == null && previous != null) window.localStorage.setItem(V3 + key, previous);
  }

  // The existing FastAPI BasketIn model accepts integer servings. V3 calculates
  // adaptive portion units from body-size preference + guests, so normalize only
  // shopping payloads at the network boundary until the backend schema is widened.
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
      } catch {
        // Leave unrelated requests untouched.
      }
      return originalFetch(input, init);
    };
    w[marker] = true;
  }
}

export default AppV3;
