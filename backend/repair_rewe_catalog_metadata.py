"""One-time repair of legacy REWE package sizes and derived unit prices.

Run from backend/: python repair_rewe_catalog_metadata.py
Loads backend/.env, then uses the configured local/managed database.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")
os.environ["BITEWISE_REPAIR_CATALOG_SNAPSHOT"] = "true"

from app.database import _repair_rewe_package_metadata_once

# database.py also invokes the migration on import; this explicit call is
# idempotent and ensures the operation runs if import order changes later.
_repair_rewe_package_metadata_once()
