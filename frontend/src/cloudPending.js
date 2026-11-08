// Pure helpers for the durable offline cloud-sync queue.
export function restorePending(raw, isAllowed) {
  const set = new Map();
  const deleted = new Set();
  if (!raw) return { set, deleted };
  try {
    const parsed = JSON.parse(raw);
    if (parsed?.set && typeof parsed.set === "object" && !Array.isArray(parsed.set)) {
      for (const [key, value] of Object.entries(parsed.set)) {
        if (isAllowed(key)) set.set(key, value);
      }
    }
    if (Array.isArray(parsed?.delete)) {
      for (const key of parsed.delete) {
        if (typeof key === "string" && isAllowed(key)) deleted.add(key);
      }
    }
  } catch {
    // A corrupt pending blob must not prevent the app from starting.
  }
  for (const key of deleted) set.delete(key);
  return { set, deleted };
}

export function serializePending(set, deleted) {
  if (!set.size && !deleted.size) return null;
  return JSON.stringify({ set: Object.fromEntries(set), delete: [...deleted] });
}

export function acknowledgePendingChanges(set, deleted, sentSet, sentDelete) {
  for (const [key, value] of Object.entries(sentSet)) {
    if (!deleted.has(key) && JSON.stringify(set.get(key)) === JSON.stringify(value)) {
      set.delete(key);
    }
  }
  for (const key of sentDelete) deleted.delete(key);
}
