"""Transparent hybrid recommender with reusable preference features.

Feedback is learned from existing events; no LLM call or model training is needed
for each request. The ranking remains explainable and has a deterministic fallback.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import exp, sqrt

CUISINE_MODES = {"asian", "mexican", "italian", "mediterranean", "latin-american", "german"}

def _event_weight(event, now):
    created = getattr(event, "created_at", None)
    if not created:
        return 0.65
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created).total_seconds() / 86400)
    # Half-life ~45 days: recent choices matter more, old ones fade gradually.
    return max(0.12, exp(-age_days / 65.0))

def build_preference_profile(events, meal_pool=None):
    """Derive cuisine/tag preferences from the user's actual feedback history."""
    if meal_pool is None:
        from ..recipes.seed import MEALS
        meal_pool = MEALS
    by_id = {str(m.get("id")): m for m in meal_pool}
    tags, cuisines = defaultdict(float), defaultdict(float)
    direct = defaultdict(float)
    recent_cooked = Counter()
    now = datetime.now(timezone.utc)
    signal = {"like": 1.0, "cooked": 1.35, "eaten": 1.5, "skip": -0.3, "dislike": -1.4}
    for event in events:
        action = getattr(event, "action", "")
        meal_id = str(getattr(event, "meal_id", ""))
        if action not in signal:
            continue
        weight = _event_weight(event, now)
        value = signal[action] * weight
        direct[meal_id] += value
        meal = by_id.get(meal_id)
        if meal is None:
            continue
        cuisine = str(meal.get("cuisine") or "").strip().lower()
        if cuisine:
            cuisines[cuisine] += value
        for tag in meal.get("tags") or []:
            key = str(tag).strip().lower()
            if key:
                tags[key] += value
        if action in {"cooked", "eaten"} and weight > 0.72:
            recent_cooked[meal_id] += weight
    # Normalize learned feature weights so a long history does not swamp request intent.
    tag_scale = max(1.0, sqrt(sum(abs(v) for v in tags.values())))
    cuisine_scale = max(1.0, sqrt(sum(abs(v) for v in cuisines.values())))
    return {
        "tags": {k: v / tag_scale for k, v in tags.items()},
        "cuisines": {k: v / cuisine_scale for k, v in cuisines.items()},
        "direct": dict(direct),
        "recent_cooked": recent_cooked,
    }

def score_meal(meal, events, pantry, mode=None, profile=None):
    profile = profile or build_preference_profile(events)
    meal_id = str(meal.get("id") or "")
    score = profile["direct"].get(meal_id, 0.0) * 2.0
    score += profile["cuisines"].get(str(meal.get("cuisine") or "").lower(), 0.0) * 2.4
    score += sum(profile["tags"].get(str(tag).lower(), 0.0) * 1.8 for tag in meal.get("tags") or [])
    score -= min(4.0, profile["recent_cooked"].get(meal_id, 0.0) * 3.0)

    minutes = float(meal.get("time") or 30)
    cost = float(meal.get("cost") or 5)
    tags = {str(tag).lower() for tag in meal.get("tags") or []}
    if mode == "quick":
        score += max(0.0, 45.0 - minutes) * 0.16
        score += 1.0 if {"easy", "low effort", "minimal cleanup"} & tags else 0.0
    elif mode == "cheap":
        score += max(0.0, 7.0 - cost) * 1.5
    elif mode == "high-protein":
        score += 4.0 if "high protein" in tags else -0.4
    elif mode == "healthy":
        score += 2.5 if "healthy" in tags else 0.0
    elif mode == "one-pot":
        score += 3.0 if "one-pot" in tags else 0.0
    elif mode == "meal-prep":
        score += 3.0 if "meal prep" in tags else 0.0
    elif mode in CUISINE_MODES:
        cuisine = str(meal.get("cuisine") or "").lower().replace(" ", "-")
        score += 7.0 if cuisine == mode else -2.0

    pantry_names = {str(p.ingredient).lower() for p in pantry if getattr(p, "quantity", 0) > 0}
    ingredients = meal.get("ingredients") or []
    covered = sum(1 for row in ingredients if isinstance(row, (list, tuple)) and row and str(row[0]).lower() in pantry_names)
    score += min(3.0, covered * 0.65)
    # Prefer realistic, low-friction meals, but don't let convenience override the user's request.
    if minutes > 60:
        score -= min(2.0, (minutes - 60) / 60)
    return score

def rank_meals(meals, events, pantry, mode=None, limit=None):
    """Build user features once, then rank with light diversity across the result set."""
    pool = list(meals)
    profile = build_preference_profile(events, pool)
    scored = [(score_meal(meal, events, pantry, mode, profile), meal) for meal in pool]
    remaining = sorted(scored, key=lambda row: row[0], reverse=True)
    ranked, cuisine_counts, signature_counts = [], Counter(), Counter()
    while remaining and (limit is None or len(ranked) < limit):
        best_index, best_value = 0, float("-inf")
        for index, (base, meal) in enumerate(remaining):
            cuisine = str(meal.get("cuisine") or "").lower()
            tags = sorted(str(t).lower() for t in (meal.get("tags") or []))
            signature = tags[0] if tags else ""
            adjusted = base - cuisine_counts[cuisine] * 0.9 - signature_counts[signature] * 0.45
            if adjusted > best_value:
                best_index, best_value = index, adjusted
        _, chosen = remaining.pop(best_index)
        ranked.append(chosen)
        cuisine_counts[str(chosen.get("cuisine") or "").lower()] += 1
        chosen_tags = sorted(str(t).lower() for t in (chosen.get("tags") or []))
        if chosen_tags:
            signature_counts[chosen_tags[0]] += 1
    return ranked
