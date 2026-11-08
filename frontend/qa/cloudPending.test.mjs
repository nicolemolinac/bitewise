import assert from "node:assert/strict";
import test from "node:test";

import { acknowledgePendingChanges, restorePending, serializePending } from "../src/cloudPending.js";

const allowed = key => ["liked", "basket", "profile"].includes(key) || /^cooking:[a-zA-Z0-9_-]+$/.test(key);

test("restores only allowlisted pending edits and deletions", () => {
  const restored = restorePending(JSON.stringify({
    set: { liked: ["recipe-1"], products: [{ id: 1 }], "cooking:recipe-2": { step: 3 } },
    delete: ["basket", "products", "cooking:"],
  }), allowed);
  assert.deepEqual(Object.fromEntries(restored.set), {
    liked: ["recipe-1"],
    "cooking:recipe-2": { step: 3 },
  });
  assert.deepEqual([...restored.deleted], ["basket"]);
});

test("corrupt or wrongly shaped pending data cannot break startup", () => {
  for (const raw of ["{broken", "null", "[]", JSON.stringify({ set: [], delete: "liked" })]) {
    const restored = restorePending(raw, allowed);
    assert.equal(restored.set.size, 0);
    assert.equal(restored.deleted.size, 0);
  }
});

test("serializes pending values and removes the storage blob when empty", () => {
  const set = new Map([["liked", ["recipe-1"]]]);
  const deleted = new Set(["basket"]);
  assert.deepEqual(JSON.parse(serializePending(set, deleted)), {
    set: { liked: ["recipe-1"] },
    delete: ["basket"],
  });
  set.clear();
  deleted.clear();
  assert.equal(serializePending(set, deleted), null);
});

test("acknowledges only the exact version sent and preserves newer local edits", () => {
  const set = new Map([["liked", ["newer"]], ["profile", { servings: 2 }]]);
  const deleted = new Set(["basket"]);
  acknowledgePendingChanges(
    set,
    deleted,
    { liked: ["older"], profile: { servings: 2 } },
    ["basket"],
  );
  assert.deepEqual(Object.fromEntries(set), { liked: ["newer"] });
  assert.equal(deleted.has("basket"), false);
});

test("a newer deletion survives acknowledgement of an older in-flight set", () => {
  const set = new Map();
  const deleted = new Set(["liked"]);
  acknowledgePendingChanges(set, deleted, { liked: ["old-value"] }, []);
  assert.equal(deleted.has("liked"), true);
});
