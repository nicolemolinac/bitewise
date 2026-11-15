"""Deterministic QA for recipe ingredient validation. Run from backend/."""
from app.ai.gemini import _sanitize_meal


def main():
    valid = _sanitize_meal({
        "id": "valid-ingredient-validation",
        "name": "Valid ingredient validation test",
        "ingredients": [
            ["rice", 100, "g"],
            ["onion", 1, "unit"],
            {"ingredient": "milk", "quantity": 250, "unit": "ml"},
        ],
    })
    assert valid is not None
    assert valid["ingredients"] == [
        ["rice", 100.0, "g"],
        ["onion", 1.0, "unit"],
        ["milk", 250.0, "ml"],
    ]

    malformed_cases = [
        [["rice", 100, "g"], ["milk", 0, "ml"]],
        [["rice", 100, "g"], ["salt", -2, "g"]],
        [["rice", 100, "g"], ["pepper", "nan", "g"]],
        [["rice", 100, "g"], ["water", "inf", "ml"]],
        [["rice", 100, "g"], ["garlic", 2, ""]],
        [["rice", 100, "g"], ["butter", "not-a-number", "g"]],
        [["rice", 100, "g"], ["salt", True, "g"]],
        [["rice", 100, "g"], {"ingredient": "garlic", "quantity": 2}],
        [["rice", 100, "g"], None],
    ]
    for ingredients in malformed_cases:
        meal = _sanitize_meal({
            "id": "incomplete-recipe",
            "name": "Incomplete recipe",
            "ingredients": ingredients,
        })
        assert meal is None, ingredients

    invalid_only = _sanitize_meal({
        "id": "invalid-only",
        "name": "Invalid ingredients",
        "ingredients": [
            ["rice", 0, "g"],
            ["milk", -1, "ml"],
            ["salt", "nan", "g"],
            ["garlic", 2, ""],
        ],
    })
    assert invalid_only is None, invalid_only

    too_many = _sanitize_meal({
        "id": "too-many",
        "name": "Recipe with too many ingredient rows",
        "ingredients": [["ingredient " + str(i), 1, "g"] for i in range(21)],
    })
    assert too_many is None

    print("VALID RECIPE INGREDIENTS PRESERVED: PASS")
    print("MALFORMED INGREDIENTS REJECT THE WHOLE RECIPE: PASS (9 cases)")
    print("EMPTY / INVALID / OVER-LIMIT RECIPES REJECTED: PASS")


if __name__ == "__main__":
    main()
