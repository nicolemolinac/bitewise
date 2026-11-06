"""Verify the committed REWE CSV snapshot seeds an empty local database once.

Run from backend/: python qa_catalog_snapshot.py
"""
import os
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-catalog-snapshot-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "snapshot.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"

from app.database import AppSetting, CatalogRun, Product, SessionLocal, _auto_import_rewe_csv_snapshot


def main():
    db = SessionLocal()
    try:
        first_count = db.query(Product).filter(Product.supermarket == "REWE").count()
        assert first_count >= 1000, f"Expected a populated REWE snapshot, got {first_count}"
        run = db.query(CatalogRun).order_by(CatalogRun.id.desc()).first()
        assert run is not None and run.status == "snapshot"
        source = db.get(AppSetting, "rewe_snapshot_source")
        assert source is not None and source.value == "committed-csv-snapshot"
    finally:
        db.close()

    _auto_import_rewe_csv_snapshot()
    db = SessionLocal()
    try:
        second_count = db.query(Product).filter(Product.supermarket == "REWE").count()
        assert second_count == first_count, "Snapshot import must be idempotent"
    finally:
        db.close()

    print(f"REWE CSV snapshot QA PASS: {first_count} products imported once")


if __name__ == "__main__":
    main()
