# Bitewise backend

FastAPI API for meal discovery, preference learning, planning, shopping optimization, REWE catalog snapshots and pantry state.

Key resources:

- `/api/meals`, `/api/events`
- `/api/brain-dump`
- `/api/plans`, `/api/today`
- `/api/shopping`, `/api/shopping/purchase`, `/api/shopping/state`
- `/api/pantry`
- `/api/products`, `/api/products/search`, `/api/products/{id}/alternatives`
- `/api/rewe/status`, `/api/rewe/refresh`
- `/api/settings`

REWE ingestion is manual and public-category based. It does not automate login or checkout and the UI/API labels catalog values as snapshots rather than real-time checkout prices.
