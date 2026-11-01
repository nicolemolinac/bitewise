# Run Bitewise locally

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
uvicorn app.server:app --reload --host 127.0.0.1 --port 8000
```

API: `http://localhost:8000/api/health`

Optional Google AI Studio configuration (meal photos use Google Images via local Playwright/Chrome and do not need a Pexels API key):

```bash
cp .env.example .env
# set GEMINI_API_KEY and optionally GEMINI_MODEL
```

REWE refresh uses the configured Bitewise postcode and **Delivery / Lieferservice only**. The HTTP scraper is tried first; Playwright is used automatically when REWE blocks HTTP or does not expose enough localized prices.

For normal local use:

```bash
REWE_BROWSER_ENABLED=true
```

If REWE changes its location modal and you need to watch the browser while diagnosing it:

```bash
REWE_BROWSER_HEADLESS=false
```

The browser session stores its local REWE postcode/delivery context in `backend/data/rewe_storage_state.json`. This file is ignored by Git and can be deleted to force a clean location selection.

## Frontend

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5174` when using the Chief Officer launcher. Use `localhost` (not `127.0.0.1`) to match the configured CORS origin.

For a different backend URL, copy `.env.example` to `.env` and change `VITE_API_URL`.

## Validation

```bash
cd backend && python -m compileall app && python -c "from app.main import app; print(app.title)" && python qa_smoke.py
cd ../frontend && npm run build
```
