import json
import os

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .database import SessionLocal, UserState

router = APIRouter(prefix="/api")


class UserStateIn(BaseModel):
    state: dict = Field(default_factory=dict)


def auth_enabled() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_PUBLISHABLE_KEY"))


def authenticate_request(request: Request) -> dict:
    """Validate a Supabase access token and optionally lock the app to one email."""
    if not auth_enabled():
        return {"id": "local-dev", "email": "local@bitewise"}

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to Bitewise first")
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(401, "Missing Bitewise session")

    url = os.getenv("SUPABASE_URL", "").rstrip("/") + "/auth/v1/user"
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "apikey": key},
            timeout=8,
        )
    except requests.RequestException as exc:
        raise HTTPException(503, f"Auth service unavailable: {exc}") from exc
    if response.status_code != 200:
        raise HTTPException(401, "Bitewise session expired. Sign in again.")
    user = response.json()

    allowed = os.getenv("ALLOWED_USER_EMAIL", "").strip().lower()
    email = str(user.get("email") or "").strip().lower()
    if allowed and email != allowed:
        raise HTTPException(403, "This private Bitewise app is not available for this account")
    if not user.get("id"):
        raise HTTPException(401, "Invalid Bitewise user")
    return user


def request_user(request: Request) -> dict:
    cached = getattr(request.state, "bitewise_user", None)
    return cached or authenticate_request(request)


@router.get("/user-state")
def get_user_state(request: Request):
    user = request_user(request)
    db = SessionLocal()
    try:
        row = db.get(UserState, str(user["id"]))
        state = {}
        if row and row.state_json:
            try:
                parsed = json.loads(row.state_json)
                if isinstance(parsed, dict):
                    state = parsed
            except Exception:
                state = {}
        return {"user_id": user["id"], "email": user.get("email"), "state": state, "updated_at": row.updated_at if row else None}
    finally:
        db.close()


@router.put("/user-state")
def put_user_state(payload: UserStateIn, request: Request):
    user = request_user(request)
    db = SessionLocal()
    try:
        user_id = str(user["id"])
        row = db.get(UserState, user_id)
        encoded = json.dumps(payload.state, ensure_ascii=False, separators=(",", ":"))
        if row:
            row.state_json = encoded
        else:
            db.add(UserState(user_id=user_id, state_json=encoded))
        db.commit()
        return {"ok": True, "user_id": user_id}
    finally:
        db.close()
