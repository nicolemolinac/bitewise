from collections import Counter


def score_meal(meal, events, pantry, mode=None):
    likes = Counter(e.meal_id for e in events if e.action == "like")
    skips = Counter(e.meal_id for e in events if e.action == "skip")
    dislikes = Counter(e.meal_id for e in events if e.action == "dislike")
    cooked = Counter(e.meal_id for e in events if e.action in ("cooked", "eaten"))

    score = 0.0
    score += likes[meal["id"]] * 3.0
    score -= skips[meal["id"]] * 2.0
    score -= dislikes[meal["id"]] * 50.0
    # Actually eating is a strong positive preference signal, but add a recency/variety penalty
    # so the same meal does not dominate recommendations immediately afterwards.
    score += cooked[meal["id"]] * 4.0
    if cooked[meal["id"]]:
        score -= 6.0

    if mode == "quick":
        score += max(0, 45 - meal["time"]) * 0.12
    if mode == "cheap":
        score += max(0, 6 - meal["cost"]) * 1.35
    if mode == "high-protein":
        score += 3.5 if "High Protein" in meal["tags"] else -0.5
    if mode == "healthy":
        score += 3.0 if "Healthy" in meal["tags"] else 0
    if mode == "one-pot":
        score += 3.0 if "One-Pot" in meal["tags"] else 0
    if mode == "meal-prep":
        score += 3.0 if "Meal Prep" in meal["tags"] else 0
    if mode in {"asian", "mexican", "italian", "mediterranean", "latin-american", "german"}:
        cuisine_key = meal["cuisine"].lower().replace(" ", "-")
        score += 7.0 if cuisine_key == mode else -2.0

    pantry_names = {p.ingredient.lower() for p in pantry if getattr(p, "quantity", 0) > 0}
    score += sum(0.8 for ingredient, _, _ in meal["ingredients"] if ingredient.lower() in pantry_names)
    return score
