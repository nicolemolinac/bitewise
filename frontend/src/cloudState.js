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
