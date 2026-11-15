"""Deterministic QA for recipe ingredient validation. Run from backend/."""
from app.ai.gemini import _sanitize_meal


def main():
    meal = _sanitize_meal({
        "id": "ingredient-validation",
        "name": "Ingredient validation test",
        "ingredients": [
            ["rice", 100, "g"],
            ["milk", 0, "ml"],
            ["salt", -2, "g"],
            ["pepper", "nan", "g"],
            ["water", "inf", "ml"],
            ["garlic", 2, ""],
            ["butter", "not-a-number", "g"],
            ["onion", 1, "unit"],
            ["salt", True, "g"],
        ],
    })
    assert meal is not None
    assert meal["ingredients"] == [
        ["rice", 100.0, "g"],
        ["onion", 1.0, "unit"],
    ], meal["ingredients"]

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

    print("POSITIVE FINITE INGREDIENT AMOUNTS: PASS")
    print("ZERO / NEGATIVE / NAN / INFINITE AMOUNTS REJECTED: PASS")
    print("MISSING UNITS REJECTED INSTEAD OF ASSUMING PIECES: PASS")


if __name__ == "__main__":
    main()
