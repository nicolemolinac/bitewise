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
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

from app.database import (
    AppSetting, CatalogRun, Product, SessionLocal, _auto_import_rewe_csv_snapshot,
    _snapshot_pack_pricing, _snapshot_package_size, _snapshot_float,
)


def main():
    assert _snapshot_float("NaN") is None
    assert _snapshot_float("inf") is None
    assert _snapshot_float("-inf") is None

    pack_price, price_per_gram = _snapshot_pack_pricing(
        "Alete Kinderkeks 180g (1 kg = 11,06 €)", 180, "g", 11.06, 0.0614
    )
    assert pack_price == 1.99
    assert abs(price_per_gram - 0.01106) < 0.000001
    assert _snapshot_package_size("Drink 2x200ml", 200, "ml") == 400
    assert _snapshot_package_size("Nuts 4x50g", 50, "g") == 200

    db = SessionLocal()
    try:
        first_count = db.query(Product).filter(Product.supermarket == "REWE").count()
        assert first_count >= 11000, (
            f"Expected the complete ~12k REWE catalog snapshot, got only {first_count} products"
        )
        sample = db.query(Product).filter(
            Product.name_original.ilike("%Alete bewusst Kinderkeks Schoko 180g%")
        ).first()
        assert sample is not None, "Expected a known package-price sample in the snapshot"
        assert sample.price is not None and abs(sample.price - 1.99) < 0.02, sample.price
        assert sample.price_per_unit is not None and abs(sample.price_per_unit - 0.01106) < 0.0001
        assert sample.availability == "unknown", "Snapshot stock must not be represented as live-confirmed"
        run = db.query(CatalogRun).order_by(CatalogRun.id.desc()).first()
        assert run is not None and run.status == "snapshot"
        source = db.get(AppSetting, "rewe_snapshot_source")
        assert source is not None and source.value == "committed-csv-snapshot"
        alete = db.query(Product).filter(Product.name_original.like("Alete bewusst Kinderkeks Schoko%")).first()
        if alete:
            assert abs(alete.price - 1.99) < 0.02, f"Expected normalized 180g pack price near €1.99, got {alete.price}"
        multipack = db.query(Product).filter(Product.name_original.like("%2x200ml%")).first()
        if multipack:
            assert multipack.package_size == 400, f"Expected 400ml multi-pack, got {multipack.package_size}"
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
