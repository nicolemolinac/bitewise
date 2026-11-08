"""Deterministic QA for the Google Images meal-photo API contract.

This suite stubs browser/network access so CI verifies the route and payload contract
without depending on Google rate limits, cookies, or image-result changes. It uses
an isolated SQLite file and never touches a developer catalog or hosted database.
"""
import os
from pathlib import Path
import tempfile

QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-image-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(QA_TEMP.name) / "qa.sqlite")
os.environ["BITEWISE_AI_MEALS_PATH"] = str(Path(QA_TEMP.name) / "ai_meals.json")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
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


def test_recipe_photo_is_downloaded_into_repo_and_reused():
    from io import BytesIO
    from PIL import Image

    original_dir = image_resolver.IMAGE_DIR
    with tempfile.TemporaryDirectory(prefix="bitewise-photo-store-") as temp:
        image_resolver.IMAGE_DIR = Path(temp)
        image_bytes = BytesIO()
        Image.new("RGB", (1800, 1200), (210, 120, 90)).save(image_bytes, format="JPEG", quality=92)
        jpeg = image_bytes.getvalue()

        class FakeResponse:
            headers = {"content-type": "image/jpeg"}
            def raise_for_status(self):
                return None
            def iter_content(self, chunk_size):
                yield jpeg

        try:
            with patch.object(image_resolver.requests, "get", return_value=FakeResponse()) as download:
                saved = image_resolver._persist_image("https://images.example.com/recipe.jpg", "qa-recipe-key")
                assert saved.startswith("/api/meal-photos/files/")
                filename = saved.rsplit("/", 1)[-1]
                stored = Path(temp) / filename
                assert stored.is_file()
                assert stored.suffix == ".webp"
                data = stored.read_bytes()
                assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
                with Image.open(stored) as optimized:
                    assert optimized.format == "WEBP"
                    assert optimized.width <= 1200 and optimized.height <= 1200
                assert image_resolver._persist_image(saved, "qa-recipe-key") == saved
                assert download.call_count == 1
        finally:
            image_resolver.IMAGE_DIR = original_dir


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
    test_recipe_photo_is_downloaded_into_repo_and_reused()
    test_meal_photos_endpoint_contract()
    test_meal_photos_rejects_non_list_payload()
    print("IMAGE QA PASS: query, URL filtering, endpoint contract and validation")
