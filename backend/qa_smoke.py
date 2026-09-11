import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "grocery.db"
BASE = "http://127.0.0.1:8011"


def call(method, path, payload=None, expected=200):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as response:
            body = response.read().decode()
            status = response.status
    except HTTPError as exc:
        status = exc.code
        body = exc.read().decode()
    assert status == expected, f"{method} {path}: expected {expected}, got {status}: {body[:500]}"
    return json.loads(body) if body else None


def wait_for_api():
    for _ in range(40):
        try:
            call("GET", "/api/health")
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("API did not start")


def main():
    if DB.exists():
        DB.unlink()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8011"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_api()

        health = call("GET", "/api/health")
        assert health["ok"] is True

        meals = call("GET", "/api/meals")["meals"]
        assert len(meals) >= 10
        meal_ids = {meal["id"] for meal in meals}
        assert "teriyaki-chicken" in meal_ids

        settings = call("GET", "/api/settings")
        assert settings["postcode"] == "13353"
        call("PATCH", "/api/settings", {"postcode": "abc"}, expected=422)
        call("PATCH", "/api/settings", {"postcode": "13353", "shopping_strategy": "best-value"})

        call("POST", "/api/pantry", {"ingredient": "rice", "quantity": 500, "unit": "g"})
        pantry = call("GET", "/api/pantry")
        rice = next(row for row in pantry if row["ingredient"] == "rice")
        assert rice["quantity"] == 500

        call("POST", "/api/events", {"meal_id": "arrabbiata", "action": "dislike"})
        dislikes = call("GET", "/api/events/dislikes")["meals"]
        assert any(row["id"] == "arrabbiata" for row in dislikes)
        call("POST", "/api/events", {"meal_id": "arrabbiata", "action": "undo-dislike"})
        dislikes = call("GET", "/api/events/dislikes")["meals"]
        assert not any(row["id"] == "arrabbiata" for row in dislikes)

        brain = call("POST", "/api/brain-dump", {"prompt": "cheap Mexican dinner, not spicy"})
        assert brain["constraints"]["max_cost"] == 5
        assert brain["constraints"]["spicy"] is False
        assert brain["mode"] == "mexican"

        plan = call(
            "POST",
            "/api/plans",
            {"weeks": 1, "servings": 2, "strategy": "best-value", "budget": 40, "meal_ids": ["teriyaki-chicken", "arrabbiata", "lentil-dal"]},
        )
        assert plan["weeks"] == 1 and plan["budget"] == 40
        assert len(plan["meals"]) == 7
        planned = plan["meals"][0]
        moved = call("PATCH", f"/api/plans/{plan['id']}/meals/{planned['id']}", {"day_index": 3})
        assert moved["day_index"] == 3

        basket = call(
            "POST",
            "/api/shopping",
            {"meal_ids": ["teriyaki-chicken"], "servings": {"teriyaki-chicken": 2}, "owned": [], "mode": "best-value"},
        )
        assert basket["servings"] == 2
        assert basket["total"] >= 0
        assert basket["pantry_savings_items"] >= 1

        eaten = call("POST", "/api/meals/teriyaki-chicken/eaten?servings=2")
        assert any(row["ingredient"] == "rice" for row in eaten["consumed"])
        pantry = call("GET", "/api/pantry")
        rice_after = next(row for row in pantry if row["ingredient"] == "rice")
        assert rice_after["quantity"] == 340

        rewe_status = call("GET", "/api/rewe/status")
        assert rewe_status["live_data"] is False
        assert rewe_status["data_freshness"] == "catalog_snapshot"

        print("QA PASS: health, meals, settings, pantry, dislike/undo, brain dump, plan/move, shopping, eat/deduct, REWE status")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if proc.returncode not in (0, -15, None) and proc.stdout:
            print(proc.stdout.read())


if __name__ == "__main__":
    main()
