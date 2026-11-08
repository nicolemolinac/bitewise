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
    _read_rewe_snapshot_rows, _snapshot_pack_pricing, _snapshot_package_size, _snapshot_package_unit,
)
from app.ingredient_aliases import canonical_ingredient_terms, ingredient_product_match_type, ingredient_search_terms


def _write_csv(path, content):
    path.write_text(content, encoding="utf-8")


def qa_snapshot_csv_validation():
    with tempfile.TemporaryDirectory(prefix="bitewise-csv-validation-qa-") as directory:
        root = Path(directory)
        valid = root / "valid.csv"
        header = "id,supermarket,external_id,ingredient,name_original,name_normalized,price\n"
        row = '1,REWE,sku-1,salmon,Salmon Fillet 200g,salmon fillet 200g,4.99\n'
        _write_csv(valid, header + row + row)
        parsed = _read_rewe_snapshot_rows(valid)
        assert len(parsed) == 1, f"Identical duplicate SKU rows should be deduplicated: {len(parsed)}"
        assert parsed[0]["external_id"] == "sku-1"

        conflict = root / "conflict.csv"
        _write_csv(conflict, header + row + '2,REWE,sku-1,tuna,Tuna Fillet 200g,tuna fillet 200g,5.99\n')
        try:
            _read_rewe_snapshot_rows(conflict)
        except ValueError as exc:
            assert "conflicting rows" in str(exc)
        else:
            raise AssertionError("Conflicting duplicate external IDs must abort CSV parsing")

        missing_header = root / "missing-header.csv"
        _write_csv(missing_header, "id,supermarket,external_id,name_original\n1,REWE,sku-1,Salmon 200g\n")
        try:
            _read_rewe_snapshot_rows(missing_header)
        except ValueError as exc:
            assert "missing required columns" in str(exc)
        else:
            raise AssertionError("CSV with missing required header columns must fail")

        malformed = root / "malformed.csv"
        _write_csv(malformed, header + '3,REWE,sku-3,rice,Rice 1kg,rice 1kg,2.99,unexpected-extra-column\n')
        try:
            _read_rewe_snapshot_rows(malformed)
        except ValueError as exc:
            assert "unexpected extra columns" in str(exc)
        else:
            raise AssertionError("CSV rows with extra fields must fail")

        broken_quote = root / "broken-quote.csv"
        _write_csv(broken_quote, header + '4,REWE,sku-4,salmon,"Unclosed product name\n')
        try:
            _read_rewe_snapshot_rows(broken_quote)
        except ValueError as exc:
            assert "malformed" in str(exc)
        else:
            raise AssertionError("CSV with an unterminated quoted field must fail")

        wrong_width = root / "wrong-width.csv"
        _write_csv(wrong_width, "1,REWE,sku-1,salmon,Salmon Fillet 200g\n")
        try:
            _read_rewe_snapshot_rows(wrong_width)
        except ValueError as exc:
            assert "columns; expected" in str(exc)
        else:
            raise AssertionError("Headerless CSV with unsupported column count must fail")


def main():
    qa_snapshot_csv_validation()
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

    # Full-catalog audit vocabulary regressions from previously unmapped REWE titles.
    assert "salami" in canonical_ingredient_terms("Aoste Luftgetrocknete Ringsalami 250g")
    assert "spinach" in canonical_ingredient_terms("Babyspinat 250g")
    assert "oyster mushroom" in canonical_ingredient_terms("Bio Austernpilze 200g")
    assert "grana padano" in canonical_ingredient_terms("Agriform Bio Grana Padano Keil 150g")
    assert "kefir" in canonical_ingredient_terms("Activia Kefir mild 345g")
    assert "bulgur" in canonical_ingredient_terms("Ahama Bulgur 500g")
    assert "agave syrup" in canonical_ingredient_terms("Alnatura Bio Agavendicksaft 250ml")
    assert "rapeseed oil" in canonical_ingredient_terms("Albaöl Rapsöl mit Buttergeschmack 0,75l")
    assert "apple cider vinegar" in canonical_ingredient_terms("Alnatura Bio Apfelessig naturtrüb 0,5l")
    assert "herring" in canonical_ingredient_terms("Appel Zarte Filets vom Hering 200g")
    assert "olive" in canonical_ingredient_terms("Alnatura Bio Origin Oliven ohne Stein 350g")
    assert "falafel" in canonical_ingredient_terms("Bauck Mühle Falafel Bio Glutenfrei 160g")
    assert "chia seeds" in canonical_ingredient_terms("Alnatura Bio Chia Samen 200g")
    assert "flaxseed oil" in canonical_ingredient_terms("Alnatura Bio Leinöl 250ml")
    # Compound ingredients must match the full phrase or an explicit German alias.
    assert "zwiebel rot" in ingredient_search_terms("red onion")
    assert ingredient_product_match_type("red onion", "Zwiebel rot 500g") == "exact"
    assert ingredient_product_match_type("red onion", "Maybelline Red Punch Nagellack") is None
    assert "senf" in ingredient_search_terms("mustard")
    assert ingredient_product_match_type("mustard", "Bautz'ner Senf mittelscharf 200ml") == "exact"
    assert ingredient_product_match_type("mustard", "Butcher's Honey Mustard Sauce 300ml") is None
    assert ingredient_product_match_type("mustard", "Kühne Senfgurken würzig 215g") is None
    assert ingredient_product_match_type("mustard", "Frosta High Protein Schlemmerfilet Brokkoli Senf 360g") is None
    assert ingredient_product_match_type("broccoli", "Frosta High Protein Schlemmerfilet Brokkoli Senf 360g") is None
    assert ingredient_product_match_type("fish", "Frosta High Protein Schlemmerfilet Brokkoli Senf 360g") == "substitute"
    assert ingredient_product_match_type("chocolate", "Dr. Oetker Kuvertüre Vollmilch 150g") == "exact"
    assert ingredient_product_match_type("chocolate", "ja! Kuvertüre Zartbitter 200g") == "exact"
    assert "sesame paste" in canonical_ingredient_terms("Alnatura Bio Tahin Sesammus 250g")
    assert "mayonnaise" in canonical_ingredient_terms("Allgroo Sushi Mayo cremig 150ml")
    assert "rapeseed oil" in canonical_ingredient_terms("Albaöl Air Fryer Spray vegan 190ml")
    assert "red onion" in canonical_ingredient_terms("REWE Bio Zwiebeln rot 500g")
    assert "mustard" in canonical_ingredient_terms("Bautz'ner Senf mittelscharf 250ml")

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
    invalid_price, invalid_unit_price = _snapshot_pack_pricing(
        "Plain product 500g", 500, "g", -2.50, -0.005
    )
    assert invalid_price is None and invalid_unit_price is None

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
