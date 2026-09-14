"""Push the current local Bitewise SQLite state into the private cloud service.

Run from backend/ after the Render service is live:
    python push_local_state_to_cloud.py

The script asks for the cloud URL and Basic Auth credentials. It never prints the
password and the cloud endpoint refuses to overwrite non-empty tables.
"""

from __future__ import annotations

import getpass
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import requests

BACKEND_DIR = Path(__file__).resolve().parent
SOURCE = Path(os.getenv("BITEWISE_LOCAL_DB_PATH") or BACKEND_DIR / "data" / "grocery.db").expanduser().resolve()
TABLES = [
    "products",
    "events",
    "pantry",
    "product_overrides",
    "catalog_runs",
    "shopping_state",
    "plans",
    "planned_meals",
    "user_state",
]


def rows(source: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    existing = {x[0] for x in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in existing:
        return []
    return [dict(row) for row in source.execute(f'SELECT * FROM "{table}"').fetchall()]


def main():
    if not SOURCE.exists():
        raise SystemExit(f"Local Bitewise database not found: {SOURCE}")

    cloud = (os.getenv("BITEWISE_CLOUD_URL") or input("Bitewise cloud URL: ").strip()).rstrip("/")
    if not cloud:
        raise SystemExit("Cloud URL is required.")
    username = os.getenv("APP_USERNAME") or input("Username: ").strip()
    password = os.getenv("APP_PASSWORD") or getpass.getpass("Password: ")

    source = sqlite3.connect(SOURCE)
    source.row_factory = sqlite3.Row
    try:
        payload = {"tables": {name: rows(source, name) for name in TABLES}, "settings": rows(source, "settings")}
    finally:
        source.close()

    response = requests.post(
        f"{cloud}/api/migration/import",
        auth=(username, password),
        timeout=120,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False, default=str),
    )
    if not response.ok:
        raise SystemExit(f"Cloud import failed ({response.status_code}): {response.text[:1000]}")
    result = response.json()
    print("Bitewise local state migrated safely to cloud.")
    for table, info in (result.get("report") or {}).items():
        print(f"  {table}: {info.get('copied', 0)} ({info.get('status', '')})")


if __name__ == "__main__":
    main()
