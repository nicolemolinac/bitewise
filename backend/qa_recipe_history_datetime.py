from datetime import date, datetime, timezone
from decimal import Decimal
import json

from app.server import _json_history_default


def main():
    payload = {
        "created_at": datetime(2026, 11, 3, 12, 30, tzinfo=timezone.utc),
        "updated_on": date(2026, 11, 3),
        "price": Decimal("4.25"),
        "tags": {"salmon", "lunch"},
    }
    encoded = json.dumps(payload, ensure_ascii=False, default=_json_history_default)
    decoded = json.loads(encoded)
    assert decoded["created_at"] == "2026-11-03T12:30:00+00:00"
    assert decoded["updated_on"] == "2026-11-03"
    assert decoded["price"] == 4.25
    assert sorted(decoded["tags"]) == ["lunch", "salmon"]
    print("Recipe history datetime serialization QA passed")


if __name__ == "__main__":
    main()
