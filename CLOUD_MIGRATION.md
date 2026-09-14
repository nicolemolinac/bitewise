# Bitewise cloud migration

Bitewise can now run as a private Render web app backed by the same persistent Postgres database on every device.

## Deployment

Use the repository `render.yaml`. The Render service needs:

- `DATABASE_URL` — the persistent Postgres/Neon connection string.
- `APP_USERNAME` and `APP_PASSWORD` — private HTTP Basic Auth for the web app.
- `SERVICE_TOKEN` — random secret used only by Personal AI OS to read Bitewise data server-to-server.
- `GEMINI_API_KEY` and `PEXELS_API_KEY` if those features are enabled.

The frontend and backend are built into one service. `VITE_API_URL=/api` is baked into the Docker build, so mobile and laptop use the same origin.

## Preserve existing local data

The cloud import endpoint is conservative: it refuses to replace a table that already contains data.

After the cloud service is live, pull the latest code on the laptop and run:

```bash
cd ~/proyectos/bitewise/backend
python push_local_state_to_cloud.py
```

The script reads the existing `backend/data/grocery.db`, asks for the Bitewise cloud URL and private login, and copies products, meal events, pantry, plans, planned meals, shopping state, overrides, settings, catalog runs and user state into cloud Postgres.

It is safe to run again: populated cloud tables are skipped instead of overwritten.

## Cross-device state

The browser app hydrates `/api/user-state` before rendering and syncs subsequent state changes back to the server, so laptop and phone share the same user state after migration.
