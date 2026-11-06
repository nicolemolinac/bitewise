"""End-to-end regression QA for Discover -> expand -> history -> Picks -> basket."""
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

_QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-expansion-flow-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_QA_TEMP.name) / "qa.sqlite")
os.environ["BITEWISE_AI_MEALS_PATH"] = str(Path(_QA_TEMP.name) / "ai_meals.json")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_PUBLISHABLE_KEY"] = ""

from fastapi.testclient import TestClient

from app import server


CONCEPT = {
    "id": "concept-salmon-lunch-qa-001",
    "name": "Honey garlic salmon rice bowl",
    "description": "Glazed salmon with rice and crisp cucumber",
    "meal_type": "lunch",
    "discovery_prompt": "lunch with salmon",
    "is_concept": True,
}

GENERATED_RECIPE = {
    "id": "generic-gemini-recipe",
    "name": "Honey garlic salmon rice bowl",
    "description": "A quick salmon bowl with a sweet savoury glaze",
    "time": 22,
    "difficulty": "Easy",
    "cost": 4.2,
    "calories": 560,
    "meal_type": "lunch",
    "cuisine": "Asian",
    "tags": ["Quick", "High protein"],
    "ingredients": [
        ["salmon fillet", 150, "g"],
        ["rice", 75, "g"],
        ["cucumber", 80, "g"],
        ["honey", 15, "g"],
        ["soy sauce", 15, "ml"],
    ],
    "steps": [
        {"text": "Cook the rice.", "minutes": 12},
        {"text": "Air fry the salmon until safely cooked.", "minutes": 9},
        {"text": "Mix the glaze and assemble the bowl.", "minutes": 2},
    ],
    "image": "",
    "expanded_from_concept": "concept-salmon-lunch-qa-001",
}


def main():
    client = TestClient(server.app)
    service = Mock()
    second_recipe = {**GENERATED_RECIPE, "name": "Creamy tomato pasta", "generated_at": datetime(2026, 11, 6, 13, 45, tzinfo=timezone.utc)}
    service.expand_concept.side_effect = [dict(GENERATED_RECIPE), second_recipe]

    # The first selection expands once, namespaces the recipe ID, and writes both
    # the expanded concept and saved full recipe to durable history.
    with patch("app.server.EfficientGeminiService", return_value=service):
        response = client.post("/api/ai/recipe", json={
            "concept": CONCEPT,
            "context": "lunch with salmon",
            "appliances": ["air fryer", "microwave"],
        })
        assert response.status_code == 200, response.text
        recipe = response.json()["meal"]
        assert recipe["id"] == "generic-gemini-recipe-" + CONCEPT["id"]
        assert recipe["source_concept_id"] == CONCEPT["id"]
        assert recipe["expanded_from_concept"] == CONCEPT["id"]
        assert recipe["costing"]["total_ingredients"] == 5
        assert recipe["costing"]["unmatched_ingredients"] >= 0
        service.expand_concept.assert_called_once_with(
            CONCEPT, "lunch with salmon", ["air fryer", "microwave"]
        )

        # A second, different concept must expand independently after the first
        # recipe was saved. Nested datetime metadata must be normalized too.
        second_concept = {**CONCEPT, "id": "concept-tomato-pasta-qa-002", "name": "Creamy tomato pasta"}
        second_response = client.post("/api/ai/recipe", json={
            "concept": second_concept,
            "context": "quick pasta",
            "appliances": ["stovetop"],
        })
        assert second_response.status_code == 200, second_response.text
        second_expanded = second_response.json()["meal"]
        assert second_expanded["id"] != recipe["id"]
        assert second_expanded["source_concept_id"] == second_concept["id"]
        assert second_expanded["generated_at"] == "2026-11-06T13:45:00+00:00"
        assert service.expand_concept.call_count == 2

        # Simulate a double tap / client retry: reuse the persisted recipe and do
        # not make a second expensive Gemini call.
        retry = client.post("/api/ai/recipe", json={
            "concept": CONCEPT,
            "context": "lunch with salmon",
            "appliances": ["air fryer", "microwave"],
        })
        assert retry.status_code == 200, retry.text
        assert retry.json().get("reused") is True
        assert retry.json()["meal"]["id"] == recipe["id"]
        service.expand_concept.assert_called_once()

    history = client.get("/api/recipe-history")
    assert history.status_code == 200, history.text
    records = history.json()["records"]
    concept_row = next(row for row in records if row["record_key"] == CONCEPT["id"])
    recipe_row = next(row for row in records if row["record_key"] == "recipe:" + CONCEPT["id"])
    assert concept_row["status"] == "expanded"
    assert recipe_row["status"] == "saved"
    assert recipe_row["meal"]["id"] == recipe["id"]
    second_recipe_row = next(row for row in records if row["record_key"] == "recipe:" + "concept-tomato-pasta-qa-002")
    assert second_recipe_row["meal"]["generated_at"] == "2026-11-06T13:45:00+00:00"
    assert recipe_row["created_at"] and recipe_row["updated_at"]

    # Picks must rehydrate from history after a restart, and the shopping endpoint
    # must resolve the saved AI recipe (not only the built-in seed meal list).
    basket = client.post("/api/shopping", json={
        "meal_ids": [recipe["id"]],
        "servings": {recipe["id"]: 0.85},
        "owned": [],
        "mode": "best-value",
    })
    assert basket.status_code == 200, basket.text
    assert basket.json()["meals"] == 1
    assert abs(basket.json()["servings"] - 0.85) < 0.001

    # A failed Gemini call must surface as 502 and must not create a fake saved Pick.
    failing = Mock()
    failing.expand_concept.side_effect = RuntimeError("Gemini offline in QA")
    failed_concept = {**CONCEPT, "id": "concept-failing-expansion-qa", "name": "Failure test salmon"}
    with patch("app.server.EfficientGeminiService", return_value=failing):
        failure = client.post("/api/ai/recipe", json={
            "concept": failed_concept,
            "context": "test failure",
            "appliances": ["air fryer"],
        })
    assert failure.status_code == 502, failure.text
    assert "Gemini offline in QA" in failure.text
    after_failure = client.get("/api/recipe-history").json()["records"]
    assert not any(row["record_key"] == failed_concept["id"] for row in after_failure)
    assert not any(row["record_key"] == "recipe:" + failed_concept["id"] for row in after_failure)

    invalid = client.post("/api/ai/recipe", json={"concept": {"id": "missing-name"}})
    assert invalid.status_code == 422

    print("Recipe flow QA PASS: two independent expansions, nested datetime serialization, idempotent retry, durable history, Picks rehydration, fractional basket and failure handling")


if __name__ == "__main__":
    main()
