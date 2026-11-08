import assert from "node:assert/strict";
import test from "node:test";

import { CLOUD_STATE_KEYS, isCloudStateKey } from "../src/cloudState.js";

test("allows known personal UI state", () => {
  for (const key of ["liked", "calendarAssignments", "basket", "profile", "cookingAlerts"]) {
    assert.equal(isCloudStateKey(`bitewise.v3.${key}`), true, key);
  }
});

test("allows per-recipe Cooking Mode sessions", () => {
  assert.equal(isCloudStateKey("bitewise.v3.cooking:recipe-123"), true);
  assert.equal(isCloudStateKey("bitewise.v3.cooking:abc_456"), true);
});

test("rejects catalog, cache, unrelated and malformed keys", () => {
  for (const key of [
    "bitewise.v3.products",
    "bitewise.v3.catalog",
    "bitewise.v3.reweCache",
    "bitewise.v3.cooking:",
    "bitewise.v3.cooking:recipe:extra",
    "other-app.liked",
    "liked",
  ]) {
    assert.equal(isCloudStateKey(key), false, key);
  }
});

test("allowlist remains explicit and excludes product catalog state", () => {
  assert.equal(CLOUD_STATE_KEYS.has("products"), false);
  assert.equal(CLOUD_STATE_KEYS.has("catalog"), false);
});

test("cloud snapshot includes cooking progress and excludes catalog/cache entries", async () => {
  const { createCloudStateSnapshot } = await import("../src/cloudState.js");
  const snapshot = createCloudStateSnapshot([
    ["bitewise.v3.liked", '["recipe-1"]'],
    ["bitewise.v3.cooking:recipe-1", JSON.stringify({ completed: [0, 2], timers: { 1: { remaining: 45 } } })],
    ["bitewise.v3.cookingAlerts", "true"],
    ["bitewise.v3.products", '[{"id":1}]'],
    ["bitewise.v3.reweCache", '{"large":"cache"}'],
    ["other-app.profile", '{"name":"not ours"}'],
  ]);
  assert.deepEqual(snapshot, {
    liked: ["recipe-1"],
    "cooking:recipe-1": { completed: [0, 2], timers: { 1: { remaining: 45 } } },
    cookingAlerts: true,
  });
});
