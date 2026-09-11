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
uvicorn app.main:app --reload --port 8000
```

Set `GEMINI_API_KEY` in `.env` if you want AI meal generation/adaptation. Google AI Studio provides API keys; keep the key server-side only.

### 2. Frontend
```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`.

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
REWE's public shop exposes products, but concrete prices can depend on the selected market/location. The adapter therefore tries a live search and falls back safely to local seed products. This keeps the entire UX functional even if REWE changes markup, blocks automation, or requires a location cookie. Replace `backend/app/rewe/adapter.py` with an official/API-backed implementation when available.

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
