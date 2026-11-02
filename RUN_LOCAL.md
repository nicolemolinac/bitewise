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

### REWE browser troubleshooting (macOS / local)

The REWE browser fallback attaches to Chrome for Testing over CDP. If no browser is already listening on port 9222, Bitewise now tries to start an isolated local Chrome for Testing profile automatically.

- Install the Playwright-managed Chrome for Testing browser once if you do not already have it: `cd backend && .venv/bin/python -m playwright install chromium`.
- If Chrome for Testing is installed in a non-standard location, set `CHROME_FOR_TESTING_PATH` in `backend/.env` to its executable path.
- The browser uses a separate profile in `backend/data/chrome-for-testing-profile`; it does not reuse or alter your personal Chrome profile.
- REWE delivery postcode and consent are saved in `backend/data/rewe_storage_state.json`.
- The first refresh may show REWE's consent and delivery-location prompts. Select Delivery / Lieferservice, not Pickup / Abholung.
- You do not need to pre-populate the REWE products database. The refresh creates/updates catalog rows. A postcode is configured separately in Bitewise Settings.

To test one category before refreshing the full catalog:

```bash
cd backend
.venv/bin/python qa_rewe_live.py
```

The live test uses postcode 13353 by default and can be blocked by REWE or network restrictions. The normal refresh is available from the app's REWE catalog control.
