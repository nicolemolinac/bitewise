import assert from "node:assert/strict";
import test from "node:test";

import { parseApiResponse } from "../src/apiResponse.js";

function response({ ok = false, status = 500, body = "" } = {}) {
  return { ok, status, text: async () => body };
}

test("extracts FastAPI detail instead of displaying raw JSON", async () => {
  await assert.rejects(
    parseApiResponse(response({
      status: 502,
      body: JSON.stringify({ detail: "Recipe expansion failed: Gemini unavailable" }),
    })),
    /Recipe expansion failed: Gemini unavailable/,
  );
});

test("formats FastAPI validation errors", async () => {
  await assert.rejects(
    parseApiResponse(response({
      status: 422,
      body: JSON.stringify({ detail: [{ loc: ["body", "concept", "name"], msg: "Field required" }] }),
    })),
    /body.concept.name: Field required/,
  );
});

test("preserves useful plain-text proxy errors", async () => {
  await assert.rejects(
    parseApiResponse(response({ status: 503, body: "Service temporarily unavailable" })),
    /Service temporarily unavailable/,
  );
});

test("parses successful JSON payloads", async () => {
  assert.deepEqual(
    await parseApiResponse(response({ ok: true, status: 200, body: JSON.stringify({ meal: { id: "recipe-1" } }) })),
    { meal: { id: "recipe-1" } },
  );
});

test("rejects a successful non-JSON response clearly", async () => {
  await assert.rejects(
    parseApiResponse(response({ ok: true, status: 200, body: "<html>proxy page</html>" })),
    /Bitewise API returned an invalid JSON response/,
  );
});
