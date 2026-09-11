from collections import Counter

def score_meal(meal, events, pantry, mode=None):
    likes = Counter(e.meal_id for e in events if e.action == "like")
    skips = Counter(e.meal_id for e in events if e.action == "skip")
    cooked = Counter(e.meal_id for e in events if e.action == "cooked")
    liked_cuisines = Counter()
    liked_tags = Counter()
    for e in events:
        if e.action == "like":
            liked_cuisines[e.meta.get("cuisine","")] += 1 if hasattr(e,'meta') else 0
    score = 0.0
    score += likes[meal["id"]] * 3 - skips[meal["id"]] * 6 - cooked[meal["id"]] * 5
    if mode == "quick": score += max(0, 45 - meal["time"]) * .12
    if mode == "cheap": score += max(0, 5 - meal["cost"]) * 1.4
    if mode == "high-protein": score += 2.5 if "High Protein" in meal["tags"] else 0
    if mode == "healthy": score += 2.5 if "Healthy" in meal["tags"] else 0
    if mode == "one-pot": score += 2.5 if "One-Pot" in meal["tags"] else 0
    if mode == "meal-prep": score += 2.5 if "Meal Prep" in meal["tags"] else 0
    if mode in {"asian","mexican","italian","mediterranean","latin-american","german"}:
        score += 6 if meal["cuisine"].lower().replace(" ","-") == mode else -2
    pantry_names = {p.ingredient.lower() for p in pantry}
    score += sum(0.6 for x,_,_ in meal["ingredients"] if x.lower() in pantry_names)
    return score
