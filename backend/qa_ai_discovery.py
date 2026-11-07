"""Offline QA: AI discovery uses the real catalog context without surrendering creativity."""
import json
from types import SimpleNamespace

from app.ai import gemini_efficient as module


def run():
    service = module.GeminiService()
    service.key = "qa-only"
    service.client = object()
    captured = {}
    original_pantry = module._pantry_context
    original_catalog = module._catalog_context
    original_taste = module._taste_context

    module._pantry_context = lambda: ["chicken (300 g)", "rice (200 g)"]
    module._catalog_context = lambda query="", limit=60, max_chars=1600, include_intelligence=False: (
        ("chicken, rice, broccoli, passata", "prepared components: passata; frozen shortcuts: broccoli")
        if include_intelligence else "chicken, rice, broccoli, passata"
    )
    module._taste_context = lambda: "cuisines: Italian, Asian; food styles: high protein, quick"

    payload = [
        {"id": "qa-idea-1", "name": "Chicken Teriyaki Bowl", "description": "Ginger soy chicken with rice", "time": 25, "cost": 3.5, "calories": 520, "meal_type": "dinner", "cuisine": "Asian", "tags": ["High Protein"], "image": ""},
        {"id": "qa-idea-2", "name": "Tomato Chickpea Curry", "description": "Chickpeas in a rich tomato curry", "time": 30, "cost": 2.8, "calories": 480, "meal_type": "dinner", "cuisine": "Indian", "tags": ["Vegetarian"], "image": ""},
    ]

    def fake_generate(instruction):
        captured["instruction"] = instruction
        return SimpleNamespace(text=json.dumps(payload)), "qa-model"

    service._generate_once = fake_generate
    try:
        ideas = service.generate_meals("quick high-protein dinner with chicken and rice")
    finally:
        module._pantry_context = original_pantry
        module._catalog_context = original_catalog
        module._taste_context = original_taste

    prompt = captured["instruction"]
    assert "quick high-protein dinner with chicken and rice" in prompt
    assert "chicken, rice, broccoli, passata" in prompt
    assert "Italian, Asian" in prompt
    assert "chicken (300 g)" in prompt
    assert "prepared components: passata" in prompt
    assert "never let this override the search" in prompt.lower()
    assert "do not restrict ideas to the list" in prompt.lower()
    assert len(ideas) == 2 and all(item["is_concept"] for item in ideas)
    assert all(item["ingredients"] == [] and item["steps"] == [] for item in ideas)
    print("AI discovery QA passed: Gemini remains the idea creator; catalog, pantry and learned taste are compact secondary context.")


if __name__ == "__main__":
    run()
