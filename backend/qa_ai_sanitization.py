"""QA for malformed Gemini output: quantities, units, tags and step metadata."""
import os
from pathlib import Path
import tempfile

_QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-ai-sanitize-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_QA_TEMP.name) / "qa.sqlite")
os.environ["BITEWISE_AI_MEALS_PATH"] = str(Path(_QA_TEMP.name) / "ai_meals.json")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"

from app.ai.gemini import _sanitize_meal, _sanitize_steps


def main():
    meal = _sanitize_meal({
        "id": "qa-salmon",
        "name": "Salmon rice bowl",
        "time": float("nan"),
        "cost": float("inf"),
        "calories": "not-a-number",
        "meal_type": "brunch-ish",
        "tags": "quick high protein",
        "ingredients": [
            ["salmon", 150, "g"],
            ["rice", 75, "grams"],
            ["cucumber", 0, "g"],
            ["salt", -1, "g"],
            ["pepper", float("nan"), "g"],
            ["oil", float("inf"), "ml"],
            ["garlic", 2, "clove"],
            ["water", 200, "milliliters"],
            ["unknown", 1, "handful"],
            ["broken", "a splash", "ml"],
        ],
        "steps": "This must not become one step per character.",
    })
    assert meal is not None
    assert meal["ingredients"] == [
        ["salmon", 150.0, "g"],
        ["rice", 75.0, "g"],
        ["garlic", 2.0, "cloves"],
        ["water", 200.0, "ml"],
    ]
    assert meal["time"] == 30
    assert meal["cost"] == 3.5
    assert meal["calories"] == 500
    assert meal["meal_type"] == "dinner"
    assert meal["tags"] == ["AI Generated"]
    assert meal["steps"] == []

    assert _sanitize_meal({"name": "No usable ingredients", "ingredients": [
        ["salt", 0, "g"], ["oil", float("inf"), "ml"]
    ]}) is None
    assert _sanitize_steps([{"text": "Cook", "minutes": 999}]) == [{"text": "Cook", "minutes": None}]
    assert _sanitize_steps("bad") == []

    print("AI output sanitization QA PASS: rejects invalid quantities/units and normalizes metadata safely")


if __name__ == "__main__":
    main()
