import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "recipe_history_qa.sqlite"
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
            "id": "ai-persistent-qa-pasta",
            "name": "Persistent QA Pasta",
            "meal_type": "dinner",
            "ingredients": [["rice", 100, "g"]],
            "steps": [{"text": "Cook rice.", "minutes": 10}],
        }
        saved = call("POST", "/api/recipe-history", {"records": [
            {"record_key": concept["id"], "record_type": "concept", "status": "expanded", "meal": concept},
            {"record_key": "recipe:" + concept["id"], "record_type": "recipe", "status": "saved", "meal": recipe},
        ]})
        assert saved["saved"] == 2
        call("PATCH", "/api/recipe-history/" + concept["id"], {"status": "expanded"})
    finally:
        stop_api(proc)

    # Seed one real catalog row, then verify the restarted app matches the recipe to it.
    with sqlite3.connect(DB) as conn:
        conn.execute("""INSERT INTO products (
            supermarket, external_id, ingredient, name_original, name_normalized,
            brand, category, package_size, package_unit, price, price_per_unit,
            currency, product_url, availability, postcode_context, first_seen_at,
            last_seen_at, last_checked_at, last_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)""",
        ("REWE", "qa-rice-500g", "rice", "REWE Beste Wahl Langkornreis 500g", "langkornreis",
         "REWE Beste Wahl", "Rice", 500, "g", 1.49, 0.00298, "EUR",
         "https://www.rewe.de/shop/p/rewe-beste-wahl-langkornreis-500g/123456", "available", "13353", 1.49))
        conn.commit()

    # A fresh server process must see the same durable history and REWE product row.
    proc = start_api()
    try:
        history = call("GET", "/api/recipe-history")
        assert history["count"] == 2
        assert any(row["meal"].get("id") == "ai-persistent-qa-pasta" for row in history["records"])
        basket = call("POST", "/api/shopping", {
            "meal_ids": ["ai-persistent-qa-pasta"],
            "servings": {"ai-persistent-qa-pasta": 2},
            "owned": [],
            "mode": "best-value",
        })
        assert basket["meals"] == 1 and basket["servings"] == 2
        rice_item = next(row for row in basket["items"] if row["ingredient"] == "rice")
        assert rice_item["product"]["name_original"] == "REWE Beste Wahl Langkornreis 500g"
        assert rice_item["total"] == 1.49
        print("QA PASS: recipe history survives restart and shopping resolves real REWE catalog products")
    finally:
        stop_api(proc)
        if DB.exists():
            DB.unlink()


if __name__ == "__main__":
    main()
