"""Regression QA for datetime-safe serialization of expanded recipe history."""
import json
from datetime import datetime, timezone

from app.server import _history_meal_json


def main():
    created = datetime(2026, 11, 3, 21, 15, 30, tzinfo=timezone.utc)
    recipe = {
        "id": "salmon-bowl-test",
        "name": "Salmon bowl",
        "product_matches": [
            {"product": "Salmon fillet", "last_checked_at": created}
        ],
        "metadata": {"generated_at": created},
    }

    encoded = _history_meal_json(recipe)
    restored = json.loads(encoded)
    assert restored["product_matches"][0]["last_checked_at"] == "2026-11-03T21:15:30+00:00"
    assert restored["metadata"]["generated_at"] == "2026-11-03T21:15:30+00:00"
    assert restored["name"] == "Salmon bowl"
    print("Recipe history datetime serialization QA PASS")


if __name__ == "__main__":
    main()
