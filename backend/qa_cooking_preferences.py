from app.ai.gemini_efficient import cooking_preferences_instruction


def main():
    default = cooking_preferences_instruction(["air fryer", "microwave", "stovetop"])
    assert default.index("1. air fryer") < default.index("2. microwave") < default.index("3. stovetop")
    assert "frozen, pre-cut or ready-to-cook" in default
    assert "Do not assume convenience products are always cheaper" in default
    assert "Never recommend microwaving raw poultry" in default

    reordered = cooking_preferences_instruction(["stovetop", "air fryer", "microwave"])
    assert reordered.index("1. stovetop") < reordered.index("2. air fryer") < reordered.index("3. microwave")

    fallback = cooking_preferences_instruction([])
    assert fallback.index("1. air fryer") < fallback.index("2. microwave")
    print("Cooking preference instructions: priority, value, frozen convenience and safety OK")


if __name__ == "__main__":
    main()
