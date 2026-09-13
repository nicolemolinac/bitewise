from app.ai.image_resolver import _source_page_image


def test_source_page_image_qa_cases(monkeypatch):
    cases = [
        ({"name": "Heart-Shaped Fried Egg", "description": "romantic simple breakfast", "tags": ["romantic"], "ingredients": [["egg", 2, "unit"], ["butter", 5, "g"]]}, "https://img.test/heart-egg.jpg"),
        ({"name": "Strawberry Rose Toast", "description": "romantic breakfast", "tags": ["romantic", "cute"], "ingredients": [["strawberry", 100, "g"], ["bread", 2, "unit"]]}, "https://img.test/strawberry-rose-toast.jpg"),
        ({"name": "Avocado Toast with Poached Egg", "description": "healthy quick breakfast", "tags": ["healthy"], "ingredients": [["avocado", 1, "unit"], ["egg", 1, "unit"]]}, "https://img.test/avocado-toast.jpg"),
        ({"name": "Chicken Teriyaki Rice Bowl", "description": "quick asian dinner", "tags": ["asian"], "ingredients": [["chicken", 150, "g"], ["rice", 100, "g"]]}, "https://img.test/teriyaki-bowl.jpg"),
        ({"name": "Tiramisu Cup", "description": "easy dessert", "tags": ["dessert"], "ingredients": [["mascarpone", 100, "g"], ["coffee", 50, "ml"]]}, "https://img.test/tiramisu.jpg"),
        ({"name": "Greek Yogurt Berry Bowl", "description": "simple breakfast", "tags": ["healthy"], "ingredients": [["yogurt", 200, "g"], ["berries", 100, "g"]]}, "https://img.test/yogurt-bowl.jpg"),
    ]

    seen_queries = []

    def fake_search(query):
        seen_queries.append(query)
        return ["https://recipe.test/page"]

    current = {"url": ""}

    def fake_page_image(_page):
        return current["url"]

    monkeypatch.setattr("app.ai.image_resolver._search_result_pages", fake_search)
    monkeypatch.setattr("app.ai.image_resolver._page_image", fake_page_image)

    for meal, expected in cases:
        current["url"] = expected
        assert _source_page_image(meal) == expected

    assert any("heart shaped fried egg" in q.lower() for q in seen_queries)
    assert any("romantic" in q.lower() for q in seen_queries)
    assert any("chicken teriyaki rice bowl" in q.lower() for q in seen_queries)


def test_source_page_image_returns_blank_if_no_valid_source(monkeypatch):
    monkeypatch.setattr("app.ai.image_resolver._search_result_pages", lambda _query: [])
    meal = {"name": "Nonexistent Dish", "description": "", "tags": [], "ingredients": [["egg", 1, "unit"]]}
    assert _source_page_image(meal) == ""
