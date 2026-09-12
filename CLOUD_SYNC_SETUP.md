# Bitewise cloud sync setup

Bitewise now supports one private Google account shared across laptop + phone.

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
```

Keep the existing `GEMINI_API_KEY`, REWE settings and CORS settings.

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

## 6. Run the authenticated backend

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

- If the cloud state is empty and the laptop already has Bitewise data, the laptop uploads its existing `bitewise.v3.*` state automatically.
- If cloud state already exists, Bitewise downloads it before the app mounts.
- Subsequent changes are saved automatically with a short debounce.

This includes current V3 local state such as picks, skips, plan-related preferences, profile, appliances, basket, extras, strategy and owned state. Backend data such as pantry, events, plans and REWE catalog already lives in the shared backend database.

## Phone

Once the frontend/backend are deployed over HTTPS:

1. Open Bitewise on the phone.
2. Sign in with the same Google account.
3. The cloud snapshot is downloaded before the app opens.
4. Add Bitewise to the Home Screen to use it as the installed PWA.
