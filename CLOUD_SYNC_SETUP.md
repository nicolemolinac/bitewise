# Bitewise cloud sync setup

Bitewise uses one private Google account shared across laptop + phone, but the two devices have different responsibilities.

## Architecture

### Laptop / desktop

The laptop is the maintenance device:

- Run REWE scraping / full catalog refreshes.
- Inspect REWE catalog status and postcode.
- Perform the one-time migration of the existing local REWE snapshot.
- Use the full Bitewise UI.

### Cloud backend + Postgres

This is the durable source of truth that lets the phone work even when the laptop is off:

- Stores the permanent REWE product catalog and catalog-run metadata.
- Stores Bitewise backend state.
- Stores the user's cross-device UI state.
- Serves only the product rows/results requested by the phone; it does not send the full catalog to the phone.

### Phone / PWA

The phone is a lightweight client:

- Calendar / plan
- Today
- Picks and discovery choices
- Basket summary and product choices returned by the backend
- Pantry
- Extras and user preferences

The phone does **not** mount REWE maintenance controls, does not run the scraper, and does not download/store the full REWE catalog.

Cross-device localStorage sync uses an explicit allowlist of personal/UI keys. REWE catalog or technical cache keys are not eligible for phone sync.

## 1. Create a free Supabase project

Create a project at Supabase. In **Project Settings → API**, copy:

- Project URL
- Publishable key

In **Connect → Connection string**, copy the Postgres connection string for your backend.

## 2. Enable Google login

In Supabase go to **Authentication → Providers → Google** and enable it.

Create a Google OAuth Web Client in Google Cloud. Use the callback URL shown by Supabase on the Google provider page as an Authorized redirect URI.

In Supabase **Authentication → URL Configuration** add:

- `http://localhost:5173` while developing
- your production Bitewise URL once deployed

## 3. Frontend environment

Create `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000/api
VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
```

Never put a Supabase secret/service-role key in the frontend.

## 4. Backend environment

Add to `backend/.env`:

```env
DATABASE_URL=YOUR_SUPABASE_POSTGRES_CONNECTION_STRING
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
ALLOWED_USER_EMAIL=YOUR_GOOGLE_EMAIL
REWE_REFRESH_INTERVAL_DAYS=90
```

Keep the existing `GEMINI_API_KEY`, REWE settings and CORS settings.

`REWE_REFRESH_INTERVAL_DAYS` is only the intended maintenance cadence. Bitewise does not need to automatically refresh the full catalog every 90 days. The existing snapshot remains usable until you intentionally replace it.

For production, set `CORS_ORIGINS` to the deployed frontend URL. For local development keep `http://localhost:5173`.

## 5. Install/update dependencies

```bash
cd frontend
npm install
```

```bash
cd ../backend
source .venv/bin/activate
pip install -r requirements.txt
```

## 6. Preserve the existing REWE snapshot permanently

The REWE catalog should not be re-scraped on every deploy or device. Once `DATABASE_URL` points at Supabase/Postgres, run this one time from the laptop:

```bash
cd backend
source .venv/bin/activate
python migrate_rewe_snapshot.py
```

This copies the existing REWE products from `backend/data/grocery.db` into the persistent Postgres database, together with metadata for the latest successful snapshot.

After that:

- laptop and phone use the same persisted REWE catalog;
- the full catalog never has to be downloaded to the phone;
- backend restarts/redeploys do not erase it;
- there is no automatic REWE refresh schedule;
- the existing snapshot remains valid until a future manual refresh;
- `REWE_REFRESH_INTERVAL_DAYS=90` records the intended roughly quarterly cadence.

A later manual `/api/rewe/refresh` writes into the same persistent Postgres catalog. Existing product rows are not tied to ephemeral disk.

## 7. Run the authenticated backend

Use the cloud entrypoint, not `app.main`:

```bash
cd backend
source .venv/bin/activate
uvicorn app.server:app --reload --port 8000
```

Then run the frontend:

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173` and choose **Continue with Google**.

## First-login migration

- If cloud user state is empty and the laptop already has Bitewise personal/UI state, the laptop uploads that state automatically.
- If cloud user state already exists, Bitewise downloads it before the app mounts.
- Subsequent allowed state changes are saved automatically with a short debounce.

Allowed cross-device state includes picks, skips, plan-related preferences, profile, appliances, basket summary, extras, strategy and owned state.

The full REWE product catalog is deliberately excluded. The phone asks the API for only the products/results needed for the current screen.

## Phone

Once the frontend/backend are deployed over HTTPS:

1. Open Bitewise on the phone.
2. Sign in with the same Google account.
3. Personal/UI state is downloaded before the app opens.
4. Calendar, Today, Picks, Basket, Pantry and other lightweight screens use the same backend.
5. REWE maintenance controls are not mounted on the phone.
6. Add Bitewise to the Home Screen to use it as the installed PWA.

The laptop can be off while the phone is used, because the durable backend and database are online. The laptop is only required when you intentionally perform REWE maintenance/scraping.
