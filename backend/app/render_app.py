import base64
import hmac
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .server import app


def _service_request_allowed(request: Request) -> bool:
    expected = os.getenv("SERVICE_TOKEN", "")
    supplied = request.headers.get("x-service-token", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


@app.middleware("http")
async def private_basic_auth(request: Request, call_next):
    if request.url.path == "/api/health" or _service_request_allowed(request):
        return await call_next(request)

    username = os.getenv("APP_USERNAME", "")
    password = os.getenv("APP_PASSWORD", "")
    if not username or not password:
        return await call_next(request)

    header = request.headers.get("authorization", "")
    ok = False
    if header.lower().startswith("basic "):
        try:
            raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            supplied_user, supplied_password = raw.split(":", 1)
            ok = hmac.compare_digest(supplied_user, username) and hmac.compare_digest(supplied_password, password)
        except Exception:
            ok = False

    if not ok:
        return PlainTextResponse(
            "Bitewise is private.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Bitewise"'},
        )

    return await call_next(request)


frontend_dist = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
