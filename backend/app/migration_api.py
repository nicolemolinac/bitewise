from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .database import (
    AppSetting,
    CatalogRun,
    PantryItem,
    Plan,
    PlannedMeal,
    Product,
    ProductOverride,
    SessionLocal,
    ShoppingState,
    UserEvent,
    UserState,
)

router = APIRouter(prefix="/api/migration", tags=["migration"])

MODELS = {
    "products": Product,
    "events": UserEvent,
    "pantry": PantryItem,
    "product_overrides": ProductOverride,
    "catalog_runs": CatalogRun,
    "shopping_state": ShoppingState,
    "plans": Plan,
    "planned_meals": PlannedMeal,
    "user_state": UserState,
}


class ImportPayload(BaseModel):
    tables: dict[str, list[dict[str, Any]]] = {}
    settings: list[dict[str, Any]] = []


def coerce(model, key: str, value: Any):
    column = model.__table__.columns.get(key)
    if column is None or value is None:
        return value
    try:
        python_type = column.type.python_type
    except Exception:
        python_type = None
    if python_type is datetime and not isinstance(value, datetime):
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None
    if python_type is bool:
        return bool(value)
    return value


@router.post("/import")
def import_local_state(payload: ImportPayload):
    db = SessionLocal()
    report: dict[str, Any] = {}
    try:
        for table_name, model in MODELS.items():
            incoming = payload.tables.get(table_name) or []
            if not incoming:
                report[table_name] = {"copied": 0, "status": "no-input"}
                continue
            existing = db.query(model).count()
            if existing:
                report[table_name] = {"copied": 0, "status": "cloud-not-empty", "existing": existing}
                continue

            allowed = {column.name for column in model.__table__.columns}
            copied = 0
            for row in incoming:
                values = {k: coerce(model, k, v) for k, v in row.items() if k in allowed}
                db.add(model(**values))
                copied += 1
            db.flush()
            report[table_name] = {"copied": copied, "status": "copied"}

        settings_copied = 0
        for row in payload.settings:
            key = str(row.get("key") or "").strip()
            if not key:
                continue
            if db.get(AppSetting, key) is None:
                db.add(AppSetting(key=key, value=str(row.get("value") or "")))
                settings_copied += 1
        report["settings"] = {"copied": settings_copied, "status": "merged"}

        db.commit()
        return {"ok": True, "report": report}
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Bitewise migration failed: {str(exc)[:500]}")
    finally:
        db.close()
