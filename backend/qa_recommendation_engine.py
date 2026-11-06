"""Offline tests for adaptive meal ranking; no API, network or database required."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.recommendations.engine import build_preference_profile, rank_meals, score_meal

def event(meal_id, action, days_ago=0):
    return SimpleNamespace(meal_id=meal_id, action=action,
                           created_at=datetime.utcnow() - timedelta(days=days_ago))

def run():
    meals = [
        {"id": "pasta-like", "name": "Pasta", "cuisine": "Italian", "tags": ["Pasta", "Comfort Food"], "time": 20, "cost": 3.5, "ingredients": [["tomato", 100, "g"]]},
        {"id": "pasta-new", "name": "Tomato gnocchi", "cuisine": "Italian", "tags": ["Pasta", "Easy"], "time": 15, "cost": 4, "ingredients": [["tomato", 100, "g"]]},
        {"id": "fish", "name": "Fish", "cuisine": "Nordic", "tags": ["Seafood"], "time": 50, "cost": 8, "ingredients": [["fish", 100, "g"]]},
        {"id": "disliked", "name": "Bad meal", "cuisine": "Italian", "tags": ["Pasta"], "time": 10, "cost": 2, "ingredients": []},
    ]
    events = [event("pasta-like", "like"), event("pasta-like", "cooked", 1),
              event("disliked", "dislike"), event("fish", "skip", 2)]
    profile = build_preference_profile(events, meals)
    assert profile["cuisines"]["italian"] > profile["cuisines"]["nordic"]
    scores = {m["id"]: score_meal(m, events, [], profile=profile) for m in meals}
    assert scores["pasta-new"] > scores["fish"], scores
    assert scores["disliked"] < scores["pasta-new"], scores

    # Old feedback fades instead of permanently dominating.
    old_only = build_preference_profile([event("fish", "like", 365)], meals)
    recent = build_preference_profile([event("fish", "like", 0)], meals)
    assert recent["cuisines"]["nordic"] > old_only["cuisines"]["nordic"]

    ranked = rank_meals(meals, events, [], limit=3)
    assert len(ranked) == 3
    assert len({m["id"] for m in ranked}) == 3
    quick = rank_meals(meals, [], [], mode="quick", limit=3)
    assert quick[0]["time"] <= 20
    print("Recommendation engine QA passed: preference learning, negative feedback, recency decay, quick intent and diversity.")

if __name__ == "__main__":
    run()
