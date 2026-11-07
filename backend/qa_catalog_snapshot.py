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
    _snapshot_pack_pricing, _snapshot_package_size, _snapshot_package_unit,
)


def main():
    pack_price, price_per_gram = _snapshot_pack_pricing(
        "Alete Kinderkeks 180g (1 kg = 11,06 €)", 180, "g", 11.06, 0.0614
    )
    assert pack_price == 1.99
    assert abs(price_per_gram - 0.01106) < 0.000001
    assert _snapshot_package_size("Drink 2x200ml", 200, "ml") == 400
    assert _snapshot_package_size("Nuts 4x50g", 50, "g") == 200
    assert _snapshot_package_size("Bonduelle Duo-Pack 2x140g 2x280g", 560, "g") == 280
    assert _snapshot_package_size("ja! Erbsen 3x140g 3x420g", 1260, "g") == 420
    assert _snapshot_package_size("Dovgan Eiscreme 6x120ml 6x130ml", 780, "ml") == 720

    # Full-catalog audit regressions: malformed units, dual-unit multipacks,
    # integer unit prices and German Pfand deposits.
    malformed_volume = "Granini Schorle 0,75ml 0,75l (1 l = 2,12 €) zzgl. 0,25 € Pfand"
    assert _snapshot_package_size(malformed_volume, 0.75, "ml") == 750
    dual_unit = "Bebivita Frucht 4x90ml 4x90g (1 kg = 7,47 €)"
    corrected_unit = _snapshot_package_unit(dual_unit, "ml")
    assert corrected_unit == "g"
    assert _snapshot_package_size(dual_unit, 360, corrected_unit) == 360

    cola_price, cola_per_ml = _snapshot_pack_pricing(
        "Coca-Cola 6x0,33l (1 l = 3 €) zzgl. 1,50 € Pfand",
        1980, "ml", 1.50, 0.004545,
    )
    assert cola_price == 7.44
    assert abs(cola_per_ml - 0.003) < 0.000001

    beer_price, beer_per_ml = _snapshot_pack_pricing(
        "Bier 20x0,5l (1 l = 2 €) zzgl. 3,10 € Pfand",
        10000, "ml", 3.10, 0.00031,
    )
    assert beer_price == 23.10
    assert abs(beer_per_ml - 0.002) < 0.000001

    multipack_price, multipack_per_ml = _snapshot_pack_pricing(
        "Crodino 6x98ml", 588, "ml", 5.99, 0.061122
    )
    assert multipack_price == 5.99
    assert abs(multipack_per_ml - (5.99 / 588)) < 0.000001

    db = SessionLocal()
    try:
        first_count = db.query(Product).filter(Product.supermarket == "REWE").count()
        assert first_count >= 1000, f"Expected a populated REWE snapshot, got {first_count}"
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
