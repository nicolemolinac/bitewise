"""Regression QA for lexical search recall beyond the old 240-row cutoff."""

import os
import tempfile
from pathlib import Path

_QA_DB_DIR = tempfile.TemporaryDirectory(prefix="bitewise-catalog-recall-qa-")
os.environ["DATABASE_URL"] = ""
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_QA_DB_DIR.name) / "qa.sqlite")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Product
from app import server


def main():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    # These broad SQL hits match only the ingredient column and should not
    # outrank a real product that appears after the former 240-row cutoff.
    session.add_all([
        Product(
            external_id=f"noise-{index}",
            ingredient="rice",
            name_original=f"Unrelated shelf item {index}",
            name_normalized=f"unrelated shelf item {index}",
            category="Kochen & Backen",
            package_size=500,
            package_unit="g",
            price=1.49,
            price_per_unit=0.00298,
            availability="available",
        )
        for index in range(240)
    ])
    target = Product(
        external_id="target-langkornreis",
        ingredient="rice",
        name_original="REWE Langkornreis 500g",
        name_normalized="rewe langkornreis 500g",
        category="Kochen & Backen",
        package_size=500,
        package_unit="g",
        price=1.79,
        price_per_unit=0.00358,
        availability="available",
    )
    session.add(target)
    session.commit()

    profile = {
        "name_en": "rice",
        "name_de": "Reis",
        "aliases": ["Langkornreis"],
        "form": "dry",
    }
    adapter = server.main_module.CatalogAdapter(session)
    results = adapter.search("rice", intelligence=profile)

    assert any(
        row.get("name_original") == "REWE Langkornreis 500g"
        and row.get("ingredient_match_type") == "exact"
        for row in results
    ), "A valid exact match after row 240 was hidden by the SQL candidate cap"

    session.close()
    engine.dispose()
    print("CATALOG SEARCH RECALL QA PASS: exact product after the former 240-row cutoff was found")


if __name__ == "__main__":
    main()
