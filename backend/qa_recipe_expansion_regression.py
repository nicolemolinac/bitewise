"""Regression checks for datetime-safe persistence and independent recipe identities.

Run from backend/: python qa_recipe_expansion_regression.py
"""
import json
import os
from pathlib import Path
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal

_QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-expansion-regression-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_QA_TEMP.name) / "qa.sqlite")
os.environ["BITEWISE_AI_MEALS_PATH"] = str(Path(_QA_TEMP.name) / "ai_meals.json")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"

from app.server import _assign_expanded_recipe_identity, _json_safe


def run():
    nested = {
        "id": "recipe-generic",
        "created_at": datetime(2026, 11, 6, 12, 30, tzinfo=timezone.utc),
        "best_before": date(2026, 11, 10),
        "cost": Decimal("4.25"),
        "product_matches": [
            {"product": {"last_checked_at": datetime(2026, 11, 6, 12, 0)}},
            {"metadata": {"flags": {"available", "priced"}}},
        ],
    }
    safe = _json_safe(nested)
    encoded = json.dumps(safe, ensure_ascii=False)
    decoded = json.loads(encoded)

    assert decoded["created_at"] == "2026-11-06T12:30:00+00:00"
    assert decoded["best_before"] == "2026-11-10"
    assert decoded["cost"] == 4.25
    assert decoded["product_matches"][0]["product"]["last_checked_at"] == "2026-11-06T12:00:00"
    assert decoded["product_matches"][1]["metadata"]["flags"] == ["available", "priced"]

    first = {"id": "ai-pasta"}
    second = {"id": "ai-pasta"}
    _assign_expanded_recipe_identity(first, "concept-pasta-1")
    _assign_expanded_recipe_identity(second, "concept-pasta-2")
    assert first["id"] != second["id"]
    assert first["source_concept_id"] == "concept-pasta-1"
    assert second["source_concept_id"] == "concept-pasta-2"

    # Repeating the same concept produces the same stable identity for idempotent retries.
    retry = {"id": "ai-pasta"}
    _assign_expanded_recipe_identity(retry, "concept-pasta-1")
    assert retry["id"] == first["id"]

    print("PASS: nested datetime/date/Decimal serialization and independent recipe identities")


if __name__ == "__main__":
    run()
