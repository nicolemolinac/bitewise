# Bitewise — AI Grocery + Food Optimization Agent

A polished local MVP for discovering meals, learning preferences, building a weekly plan, consolidating ingredients, and optimizing a REWE basket.

## Stack
- React + TypeScript + Vite
- Tailwind CSS
- FastAPI + SQLite
- Google Gemini via `google-genai` (optional; app works without it)
- REWE adapter with live-search attempt + local seed fallback

## Run locally

### 1. Backend
```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.server:app --reload --port 8000
```

Set `GEMINI_API_KEY` in `.env` if you want AI meal generation/adaptation. Google AI Studio provides API keys; keep the key server-side only.

### 2. Frontend
```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown by Vite (the project commonly uses `http://localhost:5174`).

## MVP flow
1. Discover meal cards.
2. Tap Interested / Skip; preference scores update immediately.
3. Add meals to the week.
4. Adjust servings or replace meals.
5. Generate the consolidated shopping list.
6. Mark pantry items as already owned.
7. Match normalized ingredients to REWE products.
8. Switch between Cheapest and Best Value optimization.

## REWE notes
REWE's public shop exposes products, but concrete prices can depend on the selected market/location. Prices and availability are postcode-dependent. Refresh the catalog from the REWE Catalog control before expecting real product matches. The server never substitutes demo seed products for a real catalog match: unmatched ingredients are clearly reported instead of receiving invented prices. Local development uses SQLite by default; configure `DATABASE_URL` to use persistent PostgreSQL in a hosted environment.

## Architecture
```text
frontend/
backend/app/
  ai/                  Gemini adapter
  recommendations/    transparent scoring + diversity
  recipes/             seed recipes + ingredient normalization
  shopping/            consolidation + basket optimization
  rewe/                retailer adapter + seed products
  database/            SQLite models/session
```

## Environment
`backend/.env`:
```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.8-flash
REWE_LIVE_ENABLED=false
CORS_ORIGINS=http://localhost:5173
```

For a first local run, leave `REWE_LIVE_ENABLED=false`; the seed catalog gives deterministic results. Turn it on only after checking that live access is permitted for your use case.

## Release readiness checks

Before treating the app as ready for everyday use:

1. Refresh the REWE catalog for the intended postcode and confirm products have current prices and availability.
2. Generate one recipe and verify every ingredient is either matched to a real priced REWE product, covered by the pantry, or explicitly marked unmatched.
3. Compare Cheapest and Best Value and confirm the selected products and package prices change as expected.
4. Check both checkout package cost and proportional consumed-ingredient cost. For example, using 250 g from a 500 g pack must show the full pack price at checkout and half that price as consumed cost.
5. Build a basket from multiple recipes and confirm shared ingredients are consolidated before product matching.
6. Restart the backend and verify saved concepts, expanded recipes and the shopping basket can be reconstructed from persistent history.
7. For hosted use, verify `DATABASE_URL` points to persistent PostgreSQL. Do not rely on the local SQLite database or an ephemeral container filesystem for production history.
8. Run the app in a browser from discovery through recipe expansion and basket generation; verify Gemini errors are visible and do not create fake recipes or prices.

Deterministic QA scripts (run from `backend/`):

```bash
python qa_ingredient_costing.py
python qa_recipe_history.py
```

The first script checks unit conversions, pantry deductions, unmatched handling, and the difference between checkout and consumed cost. The second checks that recipe history and real catalog-based shopping survive a backend restart. These scripts do not replace a browser test against a freshly scraped REWE catalog.
