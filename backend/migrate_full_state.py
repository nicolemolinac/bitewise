"""Copy the existing local Bitewise SQLite state into the configured Postgres database.

This migration is intentionally conservative: each table is copied only when the
cloud table is empty, so an existing cloud state is never overwritten. Set
DATABASE_URL before running it from the laptop.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

if not os.getenv("DATABASE_URL"):
    raise SystemExit("DATABASE_URL is required. Point it at the Bitewise cloud Postgres database first.")

os.environ.setdefault("AUTO_RESTORE_LOCAL_REWE", "false")

from app.database import (  # noqa: E402
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

BACKEND_DIR = Path(__file__).resolve().parent
SOURCE = Path(os.getenv("BITEWISE_LOCAL_DB_PATH") or BACKEND_DIR / "data" / "grocery.db").expanduser().resolve()

MODELS = [
    ("products", Product),
    ("events", UserEvent),
    ("pantry", PantryItem),
    ("product_overrides", ProductOverride),
    ("catalog_runs", CatalogRun),
    ("shopping_state", ShoppingState),
    ("plans", Plan),
    ("planned_meals", PlannedMeal),
    ("user_state", UserState),
]


def coerce(model, key, value):
    column = model.__table__.columns.get(key)
    if column is None or value is None:
        return value
    python_type = None
    try:
        python_type = column.type.python_type
    except Exception:
        pass
    if python_type is datetime and not isinstance(value, datetime):
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None
    if python_type is bool:
        return bool(value)
    return value


def copy_table(source, db, table_name, model):
    tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if table_name not in tables:
        return 0, "missing-local"
    if db.query(model).count() > 0:
        return 0, "cloud-not-empty"

    rows = source.execute(f'SELECT * FROM "{table_name}"').fetchall()
    allowed = {column.name for column in model.__table__.columns}
    copied = 0
    for row in rows:
        payload = {k: coerce(model, k, row[k]) for k in row.keys() if k in allowed}
        db.add(model(**payload))
        copied += 1
    db.flush()
    return copied, "copied"


def migrate_settings(source, db):
    tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "settings" not in tables:
        return 0
    copied = 0
    for row in source.execute('SELECT * FROM "settings"').fetchall():
        key = str(row["key"])
        value = str(row["value"])
        target = db.get(AppSetting, key)
        if target is None:
            db.add(AppSetting(key=key, value=value))
            copied += 1
    db.flush()
    return copied


def main():
    if not SOURCE.exists():
        raise SystemExit(f"Local Bitewise database not found: {SOURCE}")

    source = sqlite3.connect(SOURCE)
    source.row_factory = sqlite3.Row
    db = SessionLocal()
    report = {}
    try:
        for table_name, model in MODELS:
            copied, status = copy_table(source, db, table_name, model)
            report[table_name] = {"copied": copied, "status": status}
        report["settings"] = {"copied": migrate_settings(source, db), "status": "merged"}
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        source.close()
        db.close()

    print("Bitewise migration complete")
    for table_name, item in report.items():
        print(f"  {table_name}: {item['copied']} ({item['status']})")


if __name__ == "__main__":
    main()
