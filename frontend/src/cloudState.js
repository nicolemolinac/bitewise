// Explicit allowlist for personal UI state. Product catalog/cache keys must
// never be copied into browser-to-cloud user state.
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
  'calendarAssignments',
  'calendarView',
  'calendarCursor',
  'extras',
  'basket',
  'summary',
  'strategy',
  'owned',
  'customProducts',
  'customProductSchedule',
  'cookingAlerts',
]);

export function isCloudStateKey(storageKey, prefix = 'bitewise.v3.') {
  if (typeof storageKey !== 'string' || !storageKey.startsWith(prefix)) return false;
  const key = storageKey.slice(prefix.length);
  // One independent session per recipe, e.g. cooking:recipe-123.
  return CLOUD_STATE_KEYS.has(key) || /^cooking:[^:]+$/.test(key);
}

export function createCloudStateSnapshot(entries, prefix = 'bitewise.v3.') {
  const state = {};
  for (const [storageKey, raw] of entries) {
    if (raw == null || !isCloudStateKey(storageKey, prefix)) continue;
    const key = storageKey.slice(prefix.length);
    try {
      state[key] = JSON.parse(raw);
    } catch {
      state[key] = raw;
    }
  }
  return state;
}

export function mergeCloudState(localState, remoteState) {
  const acceptedRemote = {};
  for (const [key, value] of Object.entries(remoteState || {})) {
    if (isCloudStateKey(`bitewise.v3.${key}`)) acceptedRemote[key] = value;
  }
  // Remote wins for keys present on both devices; local-only keys are retained
  // and can be uploaded so first-device data is not stranded locally.
  return { ...(localState || {}), ...acceptedRemote };
}
