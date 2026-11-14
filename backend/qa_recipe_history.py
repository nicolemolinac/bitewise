import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-recipe-history-qa-")
DB = Path(QA_TEMP.name) / "recipe_history_qa.sqlite"
AI_DATA = Path(QA_TEMP.name) / "ai_meals.json"
BASE = "http://127.0.0.1:8012"


def call(method, path, payload=None, expected=200):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as response:
            body, status = response.read().decode(), response.status
    except HTTPError as exc:
        body, status = exc.read().decode(), exc.code
    assert status == expected, f"{method} {path}: expected {expected}, got {status}: {body[:400]}"
    return json.loads(body) if body else None


def start_api():
    env = os.environ.copy()
    env["BITEWISE_LOCAL_DB_PATH"] = str(DB)
    env["BITEWISE_AI_MEALS_PATH"] = str(AI_DATA)
    env["DATABASE_URL"] = ""  # Force isolated SQLite even when hosted Postgres is configured.
    env["AUTO_RESTORE_LOCAL_REWE"] = "false"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", "8012"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    for _ in range(50):
        try:
            call("GET", "/api/health")
            return proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError(proc.stdout.read() if proc.stdout else "API exited during startup")
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("Recipe history API did not start")


def stop_api(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def main():
    os.environ["BITEWISE_LOCAL_DB_PATH"] = str(DB)
    os.environ["BITEWISE_AI_MEALS_PATH"] = str(AI_DATA)
    os.environ["DATABASE_URL"] = ""
    os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
    from app.server import _assign_expanded_recipe_identity, _inherit_concept_photo

    first = _assign_expanded_recipe_identity({"id": "gemini-generic-id"}, "concept-a")
    second = _assign_expanded_recipe_identity({"id": "gemini-generic-id"}, "concept-b")
    assert first["id"] != second["id"], "Two different ideas must never collapse into one Pick"
    assert first["source_concept_id"] == "concept-a"
    assert second["source_concept_id"] == "concept-b"

    photo_path = "/api/meal-photos/files/" + ("b" * 24) + ".webp"
    expanded_with_photo = _inherit_concept_photo(
        {"id": "expanded-photo-qa"},
        {"image": photo_path, "image_page": "https://example.com/photo"},
    )
    assert expanded_with_photo["image"] == photo_path
    assert expanded_with_photo["image_page"] == "https://example.com/photo"

    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    proc = start_api()
    try:
        concept = {
            "id": "concept-persistent-qa",
            "name": "Persistent QA Pasta",
            "meal_type": "dinner",
            "is_concept": True,
            "ingredients": [],
            "steps": [],
        }
        recipe = {
            "id": first["id"],
            "source_concept_id": concept["id"],
            "name": "Persistent QA Pasta",
            "meal_type": "dinner",
            "ingredients": [["rice", 100, "g"]],
            "ingredient_intelligence": {"rice": {"canonical": "rice", "name_en": "rice", "name_de": "Reis", "aliases": ["Langkornreis"], "form": "dry", "unit_dimension": "mass", "suggested_substitutions": []}},
            "steps": [{"text": "Cook rice.", "minutes": 10}],
        }
        concept_two = {
            "id": "concept-persistent-qa-curry",
            "name": "Persistent QA Curry",
            "meal_type": "dinner",
            "is_concept": True,
            "ingredients": [],
            "steps": [],
        }
        recipe_two = {
            "id": second["id"],
            "source_concept_id": concept_two["id"],
            "name": "Persistent QA Curry",
            "meal_type": "dinner",
            "base_servings": 2,
            "ingredients": [["frozen french fries", 300, "g"]],
            "ingredient_intelligence": {"frozen french fries": {
                "canonical": "potato fries", "name_en": "frozen french fries",
                "name_de": "Tiefkühl-Pommes", "aliases": ["Pommes Frites", "Tiefkühlpommes"],
                "form": "frozen", "unit_dimension": "mass",
                "suggested_substitutions": ["fresh potatoes"], "substitution_options": [{"name": "fresh potatoes", "reason": "Fresh potatoes are the closest whole-food equivalent.", "role_preserved": True, "safe_to_auto_apply": True, "quantity_ratio": 1, "preparation_adjustment": "Fresh potatoes need longer than frozen fries: cut them evenly and cook until tender and crisp."}],
            }},
            "steps": [{"text": "Add frozen french fries to the basket.", "minutes": 5}],
        }
        saved = call("POST", "/api/recipe-history", {"records": [
            {"record_key": concept["id"], "record_type": "concept", "status": "expanded", "meal": concept},
            {"record_key": "recipe:" + concept["id"], "record_type": "recipe", "status": "saved", "meal": recipe},
            {"record_key": concept_two["id"], "record_type": "concept", "status": "expanded", "meal": concept_two},
            {"record_key": "recipe:" + concept_two["id"], "record_type": "recipe", "status": "saved", "meal": recipe_two},
        ]})
        assert saved["saved"] == 4

        # Photo references are part of the persisted meal JSON, not browser-only state.
        photo_path = "/api/meal-photos/files/" + ("a" * 24) + ".webp"
        concept_with_photo = {**concept, "image": photo_path}
        photo_save = call("POST", "/api/recipe-history", {"records": [
            {"record_key": concept["id"], "record_type": "concept", "status": "expanded", "meal": concept_with_photo},
        ]})
        assert photo_save["saved"] == 1
        refreshed_history = call("GET", "/api/recipe-history")
        persisted_concept = next(row for row in refreshed_history["records"] if row["record_key"] == concept["id"])
        assert persisted_concept["meal"]["image"] == photo_path
        call("PATCH", "/api/recipe-history/" + concept["id"], {"status": "expanded"})
        call("PATCH", "/api/recipe-history/" + concept_two["id"], {"status": "expanded"})
    finally:
        stop_api(proc)

    # Seed one real catalog row, then verify the restarted app matches the recipe to it.
    with sqlite3.connect(DB) as conn:
        cursor = conn.execute("""INSERT INTO products (
            supermarket, external_id, ingredient, name_original, name_normalized,
            brand, category, package_size, package_unit, price, price_per_unit,
            currency, product_url, availability, postcode_context, first_seen_at,
            last_seen_at, last_checked_at, last_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)""",
        ("REWE", "qa-rice-500g", "rice", "REWE Beste Wahl Langkornreis 500g", "langkornreis",
         "REWE Beste Wahl", "Rice", 500, "g", 1.49, 0.00298, "EUR",
         "https://www.rewe.de/shop/p/rewe-beste-wahl-langkornreis-500g/123456", "available", "13353", 1.49))
        # Pin the test ingredient to its fixture product so a larger imported catalog
        # cannot make this assertion depend on whichever rice is cheapest today.
        conn.execute(
            "INSERT INTO product_overrides (ingredient, product_id, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            ("rice", cursor.lastrowid),
        )
        potato_cursor = conn.execute("""INSERT INTO products (
            supermarket, external_id, ingredient, name_original, name_normalized,
            brand, category, package_size, package_unit, price, price_per_unit,
            currency, product_url, availability, postcode_context, first_seen_at,
            last_seen_at, last_checked_at, last_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)""",
        ("REWE", "qa-potatoes-2kg", "potatoes", "REWE Speisekartoffeln 2kg", "speisekartoffeln",
         "REWE", "Obst & Gemüse", 2, "kg", 3.49, 1.745, "EUR",
         "https://www.rewe.de/shop/p/speisekartoffeln/654321", "available", "13353", 3.49))
        conn.execute(
            "INSERT INTO product_overrides (ingredient, product_id, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            ("frozen french fries", potato_cursor.lastrowid),
        )
        conn.commit()

    # A fresh server process must see the same durable history and REWE product row.
    proc = start_api()
    try:
        history = call("GET", "/api/recipe-history")
        assert history["count"] == 4
        saved_recipe_ids = {row["meal"].get("id") for row in history["records"] if row["record_type"] == "recipe"}
        assert saved_recipe_ids == {first["id"], second["id"]}, saved_recipe_ids
        persisted_recipe = next(row["meal"] for row in history["records"] if row["record_type"] == "recipe" and row["meal"].get("id") == first["id"])
        assert persisted_recipe["ingredient_intelligence"]["rice"]["name_de"] == "Reis"

        reconciled = call("POST", "/api/recipe-history/reconcile", {})
        assert reconciled["updated"] == 2
        refreshed = call("GET", "/api/recipe-history")
        adapted_recipe = next(row["meal"] for row in refreshed["records"] if row["record_key"] == "recipe:" + concept_two["id"])
        assert adapted_recipe["ingredients"][0][0] == "fresh potatoes"
        assert adapted_recipe["costing"]["substituted_ingredients"] == 1
        assert any("Fresh potatoes need longer than frozen fries" in step["text"] for step in adapted_recipe["steps"])
        # Reconciliation must restore the original ingredients first, then adapt once.
        call("POST", "/api/recipe-history/reconcile", {})
        refreshed_again = call("GET", "/api/recipe-history")
        adapted_again = next(row["meal"] for row in refreshed_again["records"] if row["record_key"] == "recipe:" + concept_two["id"])
        assert sum("Fresh potatoes need longer than frozen fries" in step["text"] for step in adapted_again["steps"]) == 1

        basket = call("POST", "/api/shopping", {
            "meal_ids": [first["id"]],
            "servings": {first["id"]: 2},
            "owned": [],
            "mode": "best-value",
        })
        assert basket["meals"] == 1 and basket["servings"] == 2
        rice_item = next(row for row in basket["items"] if row["ingredient"] == "rice")
        if not rice_item.get("product"):
            print("RICE ITEM DIAGNOSTIC:", rice_item)
            print("RICE REQUIREMENT DIAGNOSTIC:", next((row for row in basket.get("requirements", []) if row.get("ingredient") == "rice"), None))
        assert rice_item["product"]["name_original"] == "REWE Beste Wahl Langkornreis 500g"
        assert rice_item["total"] == 1.49
        print("QA PASS: recipe history survives restart and shopping resolves real REWE catalog products")
    finally:
        stop_api(proc)
        if DB.exists():
            DB.unlink()


if __name__ == "__main__":
    main()
