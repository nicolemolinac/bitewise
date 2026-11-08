import json
import os
from datetime import datetime

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import SessionLocal, UserState, UserStateEntry

router = APIRouter(prefix="/api")


class UserStateIn(BaseModel):
    state: dict = Field(default_factory=dict)


class UserStateChangesIn(BaseModel):
    set: dict = Field(default_factory=dict)
    delete: list[str] = Field(default_factory=list)


CLOUD_STATE_KEYS = {
    "tab", "liked", "skipped", "mealType", "filter", "brain", "appliances",
    "profile", "dayContexts", "calendarAssignments", "calendarView", "calendarCursor",
    "extras", "basket", "summary", "strategy", "owned", "customProducts",
    "customProductSchedule", "cookingAlerts",
}


def _valid_state_key(key: str) -> bool:
    return key in CLOUD_STATE_KEYS or (
        key.startswith("cooking:") and len(key) <= 180 and key.count(":") == 1
        and bool(key.split(":", 1)[1].strip())
    )


def _upsert_state_entry(db, user_id: str, key: str, value_json: str | None, is_deleted: bool) -> None:
    """Atomically insert/update one key on both supported database engines."""
    values = {
        "user_id": user_id,
        "state_key": key,
        "value_json": value_json,
        "is_deleted": is_deleted,
        "updated_at": datetime.utcnow(),
    }
    dialect = db.bind.dialect.name
    if dialect == "sqlite":
        statement = sqlite_insert(UserStateEntry).values(**values)
    elif dialect == "postgresql":
        statement = postgresql_insert(UserStateEntry).values(**values)
    else:
        raise RuntimeError(f"Unsupported cloud-state database dialect: {dialect}")
    statement = statement.on_conflict_do_update(
        index_elements=[UserStateEntry.user_id, UserStateEntry.state_key],
        set_={
            "value_json": statement.excluded.value_json,
            "is_deleted": statement.excluded.is_deleted,
            "updated_at": statement.excluded.updated_at,
        },
    )
    db.execute(statement)


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
    if not allowed:
        # Pantry, plans, events and settings are currently single-owner tables.
        # Do not let an arbitrary valid Supabase account access shared records.
        raise HTTPException(503, "Bitewise account allowlist is not configured")
    if email != allowed:
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
                    state = {key: value for key, value in parsed.items() if isinstance(key, str) and _valid_state_key(key)}
            except Exception:
                state = {}
        entries = db.query(UserStateEntry).filter(UserStateEntry.user_id == str(user["id"])).all()
        deleted_keys = []
        for entry in entries:
            if entry.is_deleted:
                state.pop(entry.state_key, None)
                deleted_keys.append(entry.state_key)
            elif entry.value_json is not None:
                try:
                    state[entry.state_key] = json.loads(entry.value_json)
                except (TypeError, ValueError):
                    state.pop(entry.state_key, None)
        return {
            "user_id": user["id"], "email": user.get("email"), "state": state,
            "deleted_keys": deleted_keys,
            "updated_at": max((entry.updated_at for entry in entries if entry.updated_at), default=(row.updated_at if row else None)),
        }
    finally:
        db.close()


@router.put("/user-state/changes")
def put_user_state_changes(payload: UserStateChangesIn, request: Request):
    """Apply only changed keys; deleted keys remain as tombstones for offline devices."""
    user = request_user(request)
    changed_keys = set(payload.set) | set(payload.delete)
    if len(changed_keys) > 100:
        raise HTTPException(413, "Too many cloud-state changes in one request")
    invalid = sorted(key for key in changed_keys if not isinstance(key, str) or not _valid_state_key(key))
    if invalid:
        raise HTTPException(422, f"Unsupported cloud-state keys: {invalid[:5]}")
    try:
        encoded_values = {
            key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            for key, value in payload.set.items()
        }
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "Cloud state contains values that cannot be serialized") from exc
    if sum(len(value.encode("utf-8")) for value in encoded_values.values()) > 1_000_000:
        raise HTTPException(413, "Cloud-state changes exceed 1 MB")

    db = SessionLocal()
    try:
        user_id = str(user["id"])
        existing_entries = db.query(UserStateEntry).filter(UserStateEntry.user_id == user_id).all()
        # One-time lazy migration: preserve the existing whole-snapshot state when
        # the first per-key client writes, without overwriting later per-key edits.
        if not existing_entries:
            legacy = db.get(UserState, user_id)
            if legacy and legacy.state_json:
                try:
                    old_state = json.loads(legacy.state_json)
                except (TypeError, ValueError):
                    old_state = {}
                if isinstance(old_state, dict):
                    for key, value in old_state.items():
                        if isinstance(key, str) and _valid_state_key(key):
                            db.add(UserStateEntry(
                                user_id=user_id, state_key=key,
                                value_json=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                                is_deleted=False,
                            ))
                    db.flush()

        for key in payload.delete:
            _upsert_state_entry(db, user_id, key, None, True)

        for key, encoded in encoded_values.items():
            if key in payload.delete:
                continue
            _upsert_state_entry(db, user_id, key, encoded, False)

        db.commit()
        return {"ok": True, "user_id": user_id, "changed": len(changed_keys)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.put("/user-state")
def put_user_state(payload: UserStateIn, request: Request):
    user = request_user(request)
    # Legacy snapshot clients are still supported during migration, but the
    # endpoint must enforce the same allowlist and payload bounds as delta writes.
    if not isinstance(payload.state, dict):
        raise HTTPException(422, "Cloud state must be a JSON object")
    if len(payload.state) > 100:
        raise HTTPException(413, "Too many cloud-state keys")
    invalid = sorted(key for key in payload.state if not isinstance(key, str) or not _valid_state_key(key))
    if invalid:
        raise HTTPException(422, f"Unsupported cloud-state keys: {invalid[:5]}")
    try:
        encoded = json.dumps(payload.state, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "Cloud state contains values that cannot be serialized") from exc
    if len(encoded.encode("utf-8")) > 1_000_000:
        raise HTTPException(413, "Cloud-state snapshot exceeds 1 MB")
    db = SessionLocal()
    try:
        user_id = str(user["id"])
        row = db.get(UserState, user_id)
        if row:
            row.state_json = encoded
        else:
            db.add(UserState(user_id=user_id, state_json=encoded))
        # Keep the legacy snapshot endpoint compatible with clients that have not
        # yet switched to per-key changes. Missing keys become durable tombstones.
        entries = {
            entry.state_key: entry
            for entry in db.query(UserStateEntry).filter(UserStateEntry.user_id == user_id).all()
        }
        for key, value in payload.state.items():
            if not isinstance(key, str) or not _valid_state_key(key):
                continue
            entry = entries.get(key)
            encoded_value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if entry is None:
                db.add(UserStateEntry(user_id=user_id, state_key=key, value_json=encoded_value, is_deleted=False))
            else:
                entry.value_json = encoded_value
                entry.is_deleted = False
        for key, entry in entries.items():
            if key not in payload.state:
                entry.value_json = None
                entry.is_deleted = True
        db.commit()
        return {"ok": True, "user_id": user_id}
    finally:
        db.close()
