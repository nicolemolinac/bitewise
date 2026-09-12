from fastapi import Request
from fastapi.responses import JSONResponse

from .cloud_sync import auth_enabled, authenticate_request, router as cloud_router
from .main import app

# Cloud-only routes live beside the existing API to keep local development backwards compatible.
app.include_router(cloud_router)


@app.middleware("http")
async def private_bitewise(request: Request, call_next):
    """When Supabase is configured, protect every Bitewise API route with the user's session."""
    path = request.url.path
    if auth_enabled() and path.startswith("/api/") and path != "/api/health" and request.method != "OPTIONS":
        try:
            request.state.bitewise_user = authenticate_request(request)
        except Exception as exc:
            status = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "Unauthorized")
            return JSONResponse(status_code=status, content={"detail": detail})
    return await call_next(request)
