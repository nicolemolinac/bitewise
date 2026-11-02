"""Regression QA for expanding a selected meal concept without undefined context names."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.gemini_efficient import GeminiService


def main():
    service = object.__new__(GeminiService)
    service.key = "test-key"
    service.client = object()

    generated = [{
        "id": "test-recipe",
        "name": "Air fryer chicken bowl",
        "description": "A simple chicken and rice bowl",
        "time": 20,
        "difficulty": "Easy",
        "cost": 3.0,
        "calories": 500,
        "meal_type": "lunch",
        "cuisine": "International",
        "tags": [],
        "ingredients": [["chicken breast", 150, "g"]],
        "steps": [{"text": "Cook the chicken in the air fryer.", "minutes": 15}],
        "image": "",
    }]

    with patch("app.ai.gemini_efficient._pantry_context", return_value=["rice (200 g)"]) as pantry, patch(
        "app.ai.gemini_efficient._persist_generated", return_value=[dict(generated[0])]
    ), patch.object(
        service,
        "_generate_once",
        return_value=(SimpleNamespace(text=json.dumps(generated)), "mock-model"),
    ):
        recipe = service.expand_concept(
            {"id": "concept-test", "name": "Air fryer chicken bowl", "meal_type": "lunch"},
            "quick lunch",
            ["air fryer", "microwave"],
        )

    pantry.assert_called_once_with()
    assert recipe["name"] == "Air fryer chicken bowl"
    assert recipe["expanded_from_concept"] == "concept-test"
    assert recipe["generation_model"] == "mock-model"
    print("Recipe expansion QA PASS: pantry context, mocked generation and concept linkage OK")


if __name__ == "__main__":
    main()
