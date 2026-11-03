import assert from "node:assert/strict";
import test from "node:test";

import { isCanonicalReweProductUrl } from "../src/reweUrl.js";

test("accepts canonical HTTPS REWE product pages", () => {
  assert.equal(isCanonicalReweProductUrl("https://www.rewe.de/shop/p/salmon/123456"), true);
  assert.equal(isCanonicalReweProductUrl("https://rewe.de/shop/p/salmon/123456?source=qa"), true);
});

test("rejects lookalike hosts, non-HTTPS and non-product pages", () => {
  for (const url of [
    "http://www.rewe.de/shop/p/salmon/123456",
    "https://evil.rewe.de/shop/p/salmon/123456",
    "https://rewe.de.evil.example/shop/p/salmon/123456",
    "https://evilrewe.de/shop/p/salmon/123456",
    "https://www.rewe.de/shop/c/fisch/",
    "javascript:alert(1)",
    "",
    null,
  ]) {
    assert.equal(isCanonicalReweProductUrl(url), false, String(url));
  }
});
