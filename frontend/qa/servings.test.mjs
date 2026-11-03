import assert from "node:assert/strict";
import test from "node:test";

import { preserveFractionalServings } from "../src/servings.js";

test("preserves fractional serving quantities sent to shopping", () => {
  assert.deepEqual(
    preserveFractionalServings({
      small: 0.65,
      standard: 1,
      large: 1.4,
      numericString: "0.85",
    }),
    {
      small: 0.65,
      standard: 1,
      large: 1.4,
      numericString: 0.85,
    },
  );
});

test("falls back safely for invalid, non-finite and non-positive quantities", () => {
  assert.deepEqual(
    preserveFractionalServings({
      missing: undefined,
      nullValue: null,
      text: "not-a-number",
      zero: 0,
      negative: -0.5,
      infinity: Infinity,
    }),
    {
      missing: 1,
      nullValue: 1,
      text: 1,
      zero: 1,
      negative: 1,
      infinity: 1,
    },
  );
});

test("rejects non-object serving maps", () => {
  assert.deepEqual(preserveFractionalServings(null), {});
  assert.deepEqual(preserveFractionalServings(["0.85"]), {});
});
