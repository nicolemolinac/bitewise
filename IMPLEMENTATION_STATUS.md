# Bitewise implementation status

This branch upgrades the MVP into the product loop described in the master scope:

**Discover → Like / Skip / Dislike → Plan → Shop → Purchase → Pantry → Eat → Learn → Repeat**

## Implemented in this branch

- Visual Discover flow with Like, Skip and Dislike signals
- Brain Dump structured intent parsing (English + common Spanish phrases)
- 1 / 2 / 4 week plans
- Plan regeneration, swap and remove actions
- Move planned meals between days without regenerating the whole plan
- Today screen
- Cooked / Eaten / Skipped plan states
- Pantry deduction after cooked/eaten meals
- Pantry confidence/source/status states
- Manual pantry correction CRUD
- Purchase → pantry flow
- Shopping state persistence
- 4 shopping strategies: Maximum Savings, Best Value, Plan Efficiency, Premium
- Value scoring using price, package size, waste, plan reuse and premium signals
- Pantry-aware shopping optimization
- Budget guardrail UI that rebuilds plans from cheaper candidates using Maximum Savings
- Explicit package-leftover intelligence with reuse suggestions
- Review and undo Dislike decisions
- Product overrides that persist per ingredient
- Product alternatives and catalog search
- Restore Bitewise recommendation
- Open REWE product links
- Manual REWE refresh across all configured categories
- Pagination traversal and partial-failure reporting
- Product upsert/dedupe and price history fields
- Catalog freshness/status UI
- Postcode setting and validation
- Product search over normalized/original/translated/brand/ingredient fields
- REWE data explicitly labeled as a catalog snapshot rather than live checkout pricing
- Mobile navigation
- Settings UI
- CI workflow for Python import/syntax, critical route contracts and frontend TypeScript/Vite build
- `.gitignore` for virtualenv, node_modules, build output and Zone.Identifier files

## Important product behavior

- User product overrides win over automatic optimization until restored.
- Manual pantry corrections are authoritative.
- Cooked/eaten consumption is deducted only once when state transitions from an unconsumed state.
- Incompatible pantry/product units are not silently merged.
- Best Value is the default shopping strategy.
- Budget is a planning guardrail; REWE catalog prices are snapshots and are not presented as guaranteed checkout totals.
- Leftover suggestions are derived from estimated package waste in the optimized basket.
- REWE checkout/login is never automated.

## Validation

The GitHub Actions workflow in `.github/workflows/ci.yml` checks:

1. Backend dependency install
2. Python compileall
3. FastAPI import
4. Presence of critical product-loop API routes
5. Frontend `npm ci`
6. TypeScript + Vite production build
