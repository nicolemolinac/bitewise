"""QA for malformed Gemini output: quantities, units, tags and step metadata."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

_QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-ai-sanitize-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_QA_TEMP.name) / "qa.sqlite")
os.environ["BITEWISE_AI_MEALS_PATH"] = str(Path(_QA_TEMP.name) / "ai_meals.json")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"

from app.ai.gemini import _sanitize_meal, _sanitize_steps
from app.ai.gemini_efficient import GeminiService


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
            ["boolean quantity", True, "g"],
        ],
        "steps": [
            {"text": "Boolean timer must be discarded", "minutes": True},
            {"text": "Numeric-string timer is normalized", "minutes": "2"},
        ],
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
    assert meal["steps"] == [
        {"text": "Boolean timer must be discarded", "minutes": None},
        {"text": "Numeric-string timer is normalized", "minutes": 2},
    ]

    boolean_metadata = _sanitize_meal({
        "name": "Boolean metadata test",
        "time": True,
        "cost": True,
        "calories": True,
        "ingredients": [["rice", 50, "g"]],
    })
    assert boolean_metadata is not None
    assert boolean_metadata["time"] == 30
    assert boolean_metadata["cost"] == 3.5
    assert boolean_metadata["calories"] == 500

    assert _sanitize_meal({"name": "No usable ingredients", "ingredients": [
        ["salt", 0, "g"], ["oil", float("inf"), "ml"]
    ]}) is None
    assert _sanitize_steps([{"text": "Cook", "minutes": 999}]) == [{"text": "Cook", "minutes": None}]
    assert _sanitize_steps("bad") == []

    # The lightweight Discover generator has a separate schema from full recipes.
    # Malformed metadata must not crash the request or leak NaN/Infinity into JSON.
    service = object.__new__(GeminiService)
    service.key = "qa-key"
    service.client = object()
    generated = [
        {
            "id": "concept-salmon",
            "name": "Salmon lunch bowl",
            "description": "Salmon with rice",
            "time": "NaN",
            "cost": "Infinity",
            "calories": "unknown",
            "meal_type": "brunch-ish",
            "tags": "quick high protein",
            "image": "http://not-secure.example/image.jpg",
        },
        {"id": "empty-name", "name": "  "},
    ]
    with patch("app.ai.gemini_efficient._pantry_context", return_value=[]), patch.object(
        service,
        "_generate_once",
        return_value=(SimpleNamespace(text=json.dumps(generated)), "mock-model"),
    ):
        concepts = service.generate_meals("lunch with salmon")

    assert len(concepts) == 1
    concept = concepts[0]
    assert concept["time"] == 20
    assert concept["cost"] == 3.5
    assert concept["calories"] == 400
    assert concept["meal_type"] == "dinner"
    assert concept["tags"] == []
    assert concept["image"] == ""
    assert concept["ingredients"] == [] and concept["steps"] == []
    assert concept["is_concept"] is True

    print("AI output sanitization QA PASS: recipe and discovery metadata are normalized safely")


if __name__ == "__main__":
    main()
