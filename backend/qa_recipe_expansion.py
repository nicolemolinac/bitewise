"""Regression QA for expanding multiple distinct meal concepts in sequence."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import call, patch

from app.ai.gemini_efficient import GeminiService
from app.server import _assign_expanded_recipe_identity, _json_history_default


def main():
    service = object.__new__(GeminiService)
    service.key = "test-key"
    service.client = object()

    first_generated = [{
        "id": "generic-recipe-id",
        "name": "Air fryer chicken pizza",
        "description": "A simple chicken pizza",
        "time": 20,
        "difficulty": "Easy",
        "cost": 3.0,
        "calories": 500,
        "meal_type": "dinner",
        "cuisine": "Italian",
        "tags": [],
        "ingredients": [["chicken breast", 150, "g"]],
        "steps": [{"text": "Cook the chicken in the air fryer.", "minutes": 15}],
        "image": "",
    }]
    second_generated = [{
        **first_generated[0],
        "name": "Margherita pizza",
        "description": "A simple tomato and mozzarella pizza",
    }]

    with patch(
        "app.ai.gemini_efficient._pantry_context",
        side_effect=[["chicken"], ["tomatoes"]],
    ) as pantry, patch(
        "app.ai.gemini_efficient._persist_generated",
        side_effect=[[dict(first_generated[0])], [dict(second_generated[0])]],
    ), patch.object(
        service,
        "_generate_once",
        side_effect=[
            (SimpleNamespace(text=json.dumps(first_generated)), "mock-model"),
            (SimpleNamespace(text=json.dumps(second_generated)), "mock-model"),
        ],
    ):
        first = service.expand_concept(
            {"id": "pizza-concept-one", "name": "Air fryer chicken pizza", "meal_type": "dinner"},
            "pizza",
            ["air fryer", "microwave"],
        )
        second = service.expand_concept(
            {"id": "pizza-concept-two", "name": "Margherita pizza", "meal_type": "dinner"},
            "different pizza",
            ["air fryer", "microwave"],
        )

    pantry.assert_has_calls([call(), call()])
    first = _assign_expanded_recipe_identity(first, "pizza-concept-one")
    second = _assign_expanded_recipe_identity(second, "pizza-concept-two")
    assert first["name"] == "Air fryer chicken pizza"
    assert second["name"] == "Margherita pizza"
    assert first["id"] != second["id"], "Distinct concepts must never collide when Gemini reuses a generic recipe ID"
    assert first["source_concept_id"] == "pizza-concept-one"
    assert second["source_concept_id"] == "pizza-concept-two"

    # Keep the datetime serialization regression on the same multi-expansion path.
    encoded = json.dumps(
        {"created_at": datetime(2026, 11, 15, 12, 30, tzinfo=timezone.utc)},
        default=_json_history_default,
    )
    assert json.loads(encoded)["created_at"] == "2026-11-15T12:30:00+00:00"

    print("Recipe expansion QA PASS: two distinct concepts, unique IDs and datetime-safe history serialization")


if __name__ == "__main__":
    main()
