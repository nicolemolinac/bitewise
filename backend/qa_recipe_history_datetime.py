"""Regression QA for recipe-history JSON serialization on insert and update.

Run from backend/: python qa_recipe_history_datetime.py
"""
from datetime import date, datetime, timezone
import os
from pathlib import Path
import tempfile
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import json

from starlette.requests import Request

QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-recipe-history-datetime-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(QA_TEMP.name) / "qa.sqlite")
os.environ["BITEWISE_AI_MEALS_PATH"] = str(Path(QA_TEMP.name) / "ai_meals.json")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"

from app import server
from app.server import _json_history_default, _upsert_recipe_history


class FakeQuery:
    def __init__(self, row):
        self.row = row

    def filter_by(self, **_filters):
        return self

    def first(self):
        return self.row


class FakeSession:
    def __init__(self, existing=None):
        self.row = existing
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def query(self, _model):
        return FakeQuery(self.row)

    def add(self, row):
        self.row = row
        self.added.append(row)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def make_request():
    request = Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/recipe-history",
        "raw_path": b"/api/recipe-history",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 123),
    })
    request.state.bitewise_user = {"id": "qa-datetime-owner"}
    return request


def payload_with_database_values():
    return {
        "id": "recipe-salmon-lunch",
        "name": "Salmon lunch bowl",
        "product_matches": [{
            "ingredient": "salmon",
            "product": {
                "name_original": "REWE Salmon Fillet",
                "last_checked_at": datetime(2026, 11, 3, 12, 30, tzinfo=timezone.utc),
                "price": Decimal("4.25"),
                "tags": {"salmon", "fresh"},
            },
        }],
        "created_on": date(2026, 11, 3),
    }


def main():
    payload = payload_with_database_values()

    # Keep a small direct contract test for each supported Python type.
    encoded = json.dumps(payload, ensure_ascii=False, default=_json_history_default)
    decoded = json.loads(encoded)
    product = decoded["product_matches"][0]["product"]
    assert product["last_checked_at"] == "2026-11-03T12:30:00+00:00"
    assert product["price"] == 4.25
    assert sorted(product["tags"]) == ["fresh", "salmon"]
    assert decoded["created_on"] == "2026-11-03"

    # Exercise the actual history INSERT path, not only json.dumps in isolation.
    insert_session = FakeSession()
    with patch.object(server, "SessionLocal", return_value=insert_session):
        _upsert_recipe_history(
            make_request(), "recipe:salmon-concept", "recipe", "saved", payload, "lunch with salmon"
        )
    assert insert_session.committed and insert_session.closed
    assert len(insert_session.added) == 1
    inserted = json.loads(insert_session.added[0].meal_json)
    assert inserted["product_matches"][0]["product"]["last_checked_at"] == "2026-11-03T12:30:00+00:00"

    # Exercise the UPDATE path too: old history rows must not reintroduce the bug.
    existing = SimpleNamespace(
        record_type="recipe",
        status="saved",
        name="Old salmon lunch",
        prompt=None,
        meal_json="{}",
        updated_at=None,
    )
    update_session = FakeSession(existing=existing)
    with patch.object(server, "SessionLocal", return_value=update_session):
        _upsert_recipe_history(
            make_request(), "recipe:salmon-concept", "recipe", "cooked", payload, "updated prompt"
        )
    assert update_session.committed and update_session.closed
    assert existing.status == "cooked"
    assert existing.prompt == "updated prompt"
    assert json.loads(existing.meal_json)["product_matches"][0]["product"]["price"] == 4.25
    assert isinstance(existing.updated_at, datetime)

    # Unknown objects must fail explicitly and roll back rather than silently stringify.
    bad_session = FakeSession()
    bad_payload = {"id": "bad", "name": "Bad recipe", "unexpected": object()}
    try:
        with patch.object(server, "SessionLocal", return_value=bad_session):
            _upsert_recipe_history(make_request(), "recipe:bad", "recipe", "saved", bad_payload)
    except TypeError as exc:
        assert "not JSON serializable" in str(exc)
    else:
        raise AssertionError("Unsupported objects must not be silently serialized")
    assert bad_session.rolled_back and bad_session.closed

    print("Recipe history datetime QA PASS: nested DB values serialize on insert/update; unsupported types roll back")


if __name__ == "__main__":
    main()
