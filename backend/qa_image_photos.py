"""Deterministic QA for the Google Images meal-photo API contract.

This suite stubs browser/network access so CI verifies the route and payload contract
without depending on Google rate limits, cookies, or image-result changes.
"""
from fastapi.testclient import TestClient
from unittest.mock import patch

from app import main as main_module
from app import server
from app.ai import image_resolver


def test_query_is_specific_and_aesthetic():
    query = image_resolver._query({
        "name": "Heart-shaped eggs on avocado toast",
        "description": "A romantic breakfast with cherry tomatoes",
        "tags": ["breakfast", "romantic"],
        "ingredients": [["eggs", 2, "pcs"], ["avocado", 1, "pc"]],
    }).lower()
    assert "heart-shaped eggs" in query
    assert "avocado" in query
    assert "aesthetic food photography" in query


def test_image_url_filter():
    assert image_resolver._usable_url("https://images.example.com/meal.jpg")
    assert not image_resolver._usable_url("data:image/png;base64,abc")
    assert not image_resolver._usable_url("https://www.google.com/logo.png")
    assert not image_resolver._usable_url("http://images.example.com/meal.jpg")


def test_meal_photos_endpoint_contract():
    seen = []

    def fake_resolver(meals):
        seen.extend(meals)
        return [
            {
                "image": f"https://images.example.com/{meal['name'].replace(' ', '-')}.jpg",
                "image_page": "https://example.com/recipe",
                "photographer": "",
                "search_query": f"{meal['name']} aesthetic food photography",
            }
            for meal in meals
        ]

    assert server.app is main_module.app, "server entrypoint must reuse the shared app"
    with patch.object(main_module, "resolve_meal_images", fake_resolver):
        client = TestClient(main_module.app)
        response = client.post("/api/meal-photos", json={
        "meals": [
            {"name": "Heart-shaped eggs", "ingredients": [["eggs", 2, "pcs"]]},
            {"name": "Strawberry pancakes", "ingredients": [["strawberries", 100, "g"]]},
        ]
        })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert len(payload["photos"]) == 2
        assert payload["photos"][0]["image"].endswith("/Heart-shaped-eggs.jpg")
        assert payload["photos"][1]["image"].endswith("/Strawberry-pancakes.jpg")
        assert len(seen) == 2


def test_meal_photos_rejects_non_list_payload():
    with patch.object(main_module, "resolve_meal_images", lambda meals: []):
        client = TestClient(main_module.app)
        response = client.post("/api/meal-photos", json={"meals": "not-a-list"})
        assert response.status_code == 422


if __name__ == "__main__":
    test_query_is_specific_and_aesthetic()
    test_image_url_filter()
    test_meal_photos_endpoint_contract()
    test_meal_photos_rejects_non_list_payload()
    print("IMAGE QA PASS: query, URL filtering, endpoint contract and validation")
