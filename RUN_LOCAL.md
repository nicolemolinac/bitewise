# Run Bitewise locally

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API: `http://localhost:8000/api/health`

Optional Google AI Studio configuration:

```bash
cp .env.example .env
# set GEMINI_API_KEY and optionally GEMINI_MODEL
```

## Frontend

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`.

For a different backend URL, copy `.env.example` to `.env` and change `VITE_API_URL`.

## Validation

```bash
cd backend && python -m compileall app && python -c "from app.main import app; print(app.title)"
cd ../frontend && npm run build
```
