import json
import subprocess
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
QA_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-qa-smoke-")
DB = Path(QA_TEMP.name) / "grocery.db"
AI_DATA = Path(QA_TEMP.name) / "ai_meals.json"
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
    if DB.exists(): DB.unlink()
    if AI_DATA.exists(): AI_DATA.unlink()
    AI_DATA.parent.mkdir(parents=True, exist_ok=True)
    AI_DATA.write_text(json.dumps([{
        "id": "ai-qa-taco-bowl",
        "name": "QA Taco Bowl",
        "description": "Persistent AI meal used only by automated QA.",
        "time": 20,
        "difficulty": "Easy",
        "cost": 2.5,
        "cuisine": "Mexican",
        "tags": ["AI Generated", "Quick"],
        "ingredients": [["rice", 160, "g"], ["chicken breast", 250, "g"]],
        "image": "https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=1200&q=85",
        "source": "gemini"
    }]), encoding="utf-8")

    env = os.environ.copy()
    env["BITEWISE_LOCAL_DB_PATH"] = str(DB)
    env["BITEWISE_AI_MEALS_PATH"] = str(AI_DATA)
    env["DATABASE_URL"] = ""  # Never let a local .env redirect QA writes to hosted Postgres.
    env["AUTO_RESTORE_LOCAL_REWE"] = "false"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8011"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        wait_for_api()
        assert call("GET", "/api/health")["ok"] is True

        meals = call("GET", "/api/meals")["meals"]
        assert len(meals) >= 10
        assert "teriyaki-chicken" in {meal["id"] for meal in meals}
        mexican_meals = call("GET", "/api/meals?mode=mexican")["meals"]
        assert "ai-qa-taco-bowl" in {meal["id"] for meal in mexican_meals}, "Persisted AI meal was not loaded into Discover catalog"

        settings = call("GET", "/api/settings")
        assert settings["postcode"] == "13353"
        call("PATCH", "/api/settings", {"postcode": "abc"}, expected=422)
        call("PATCH", "/api/settings", {"postcode": "13353", "shopping_strategy": "best-value"})

        # Pantry quantities must convert safely across kg/g and never go negative.
        call("POST", "/api/pantry", {"ingredient": "rice", "quantity": 0.5, "unit": "kg"})
        call("POST", "/api/pantry", {"ingredient": "chicken breast", "quantity": 0.1, "unit": "kg"})
        rice = next(row for row in call("GET", "/api/pantry") if row["ingredient"] == "rice")
        assert rice["quantity"] == 0.5 and rice["unit"] == "kg"

        call("POST", "/api/events", {"meal_id": "arrabbiata", "action": "dislike"})
        assert any(row["id"] == "arrabbiata" for row in call("GET", "/api/events/dislikes")["meals"])
        call("POST", "/api/events", {"meal_id": "arrabbiata", "action": "undo-dislike"})
        assert not any(row["id"] == "arrabbiata" for row in call("GET", "/api/events/dislikes")["meals"])

        brain = call("POST", "/api/brain-dump", {"prompt": "cheap Mexican dinner, not spicy"})
        assert brain["constraints"]["max_cost"] == 5 and brain["constraints"]["spicy"] is False and brain["mode"] == "mexican"

        plan = call("POST", "/api/plans", {
            "weeks": 1, "servings": 2, "strategy": "best-value", "budget": 40,
            "meal_ids": ["ai-qa-taco-bowl", "teriyaki-chicken", "lentil-dal"]
        })
        assert plan["weeks"] == 1 and plan["budget"] == 40 and len(plan["meals"]) == 7
        assert any(row["meal_id"] == "ai-qa-taco-bowl" for row in plan["meals"]), "AI meal did not integrate into planning"
        planned = plan["meals"][0]
        assert call("PATCH", f"/api/plans/{plan['id']}/meals/{planned['id']}", {"day_index": 3})["day_index"] == 3

        ai_basket = call("POST", "/api/shopping", {
            "meal_ids": ["ai-qa-taco-bowl"], "servings": {"ai-qa-taco-bowl": 2}, "owned": [], "mode": "best-value"
        })
        assert ai_basket["servings"] == 2 and ai_basket["total"] >= 0, "AI meal did not integrate into shopping"

        fractional_basket = call("POST", "/api/shopping", {
            "meal_ids": ["ai-qa-taco-bowl"], "servings": {"ai-qa-taco-bowl": 0.85}, "owned": [], "mode": "best-value"
        })
        assert abs(fractional_basket["servings"] - 0.85) < 0.001, "Fractional portion factor was not preserved for basket quantities"

        basket = call("POST", "/api/shopping", {
            "meal_ids": ["teriyaki-chicken"], "servings": {"teriyaki-chicken": 2}, "owned": [], "mode": "best-value"
        })
        assert basket["servings"] == 2 and basket["pantry_savings_items"] >= 1

        eaten = call("POST", "/api/meals/teriyaki-chicken/eaten?servings=2")
        rice_used = next(row for row in eaten["consumed"] if row["ingredient"] == "rice")
        assert rice_used["unit"] == "g" and rice_used["quantity"] == 160
        rice_after = next(row for row in call("GET", "/api/pantry") if row["ingredient"] == "rice")
        assert rice_after["unit"] == "kg" and abs(rice_after["quantity"] - 0.34) < 0.001
        chicken_after = next(row for row in call("GET", "/api/pantry") if row["ingredient"] == "chicken breast")
        assert chicken_after["quantity"] == 0, "Insufficient pantry stock must clamp to zero, never become negative"
        chicken_used = next(row for row in eaten["consumed"] if row["ingredient"] == "chicken breast")
        assert chicken_used["quantity"] == 100 and chicken_used["unit"] == "g"

        # A planned meal may be toggled cooked -> planned -> eaten, but its
        # pantry deduction must be recorded only once for that planned_meal_id.
        call("POST", "/api/pantry", {"ingredient": "rice", "quantity": 0.5, "unit": "kg"})
        call("POST", "/api/pantry", {"ingredient": "chicken breast", "quantity": 0.1, "unit": "kg"})
        ledger_plan = call("POST", "/api/plans", {
            "weeks": 1, "servings": 2, "strategy": "best-value",
            "meal_ids": ["teriyaki-chicken"]
        })
        ledger_meal = ledger_plan["meals"][0]
        first_status = call("POST", f"/api/plans/{ledger_plan['id']}/meals/{ledger_meal['id']}/status", {"status": "cooked"})
        assert first_status["consumed"], "First cooked transition should consume available pantry stock"
        call("POST", f"/api/plans/{ledger_plan['id']}/meals/{ledger_meal['id']}/status", {"status": "planned"})
        repeated_status = call("POST", f"/api/plans/{ledger_plan['id']}/meals/{ledger_meal['id']}/status", {"status": "eaten"})
        assert repeated_status["already_consumed"] is True and repeated_status["consumed"] == []
        rice_after_repeat = next(row for row in call("GET", "/api/pantry") if row["ingredient"] == "rice")
        assert abs(rice_after_repeat["quantity"] - 0.34) < 0.001, "Toggling meal status deducted pantry stock more than once"

        rewe_status = call("GET", "/api/rewe/status")
        assert rewe_status["live_data"] is False and rewe_status["data_freshness"] == "catalog_snapshot"

        print("QA PASS: core loop + unit-safe/idempotent pantry consumption + persistent AI meal Discover/Plan/Shopping integration + REWE status")
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        if AI_DATA.exists(): AI_DATA.unlink()
        if proc.returncode not in (0, -15, None) and proc.stdout: print(proc.stdout.read())


if __name__ == "__main__":
    main()
