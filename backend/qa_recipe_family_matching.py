"""Recipe-family coverage QA for common REWE ingredients and seasonings.

Offline deterministic checks only. Uses real EN/DE aliases and title matching;
does not call Gemini, REWE, or any scraper.
"""
from app.ingredient_aliases import ingredient_product_match_type, ingredient_search_terms
from app.catalog.intelligence import classify_product

# Each recipe is a realistic ingredient list rather than only its headline protein.
RECIPES = {
    "Creamy mushroom tagliatelle": {
        "tagliatelle": "REWE Tagliatelle 500 g",
        "mushrooms": "REWE Champignons 250 g",
        "cream": "REWE Schlagsahne 200 ml",
        "garlic": "REWE Knoblauch",
        "parmesan": "Parmigiano Reggiano gerieben",
        "thyme": "REWE Thymian",
        "parsley": "REWE Petersilie",
        "butter": "Deutsche Markenbutter",
        "black pepper": "Schwarzer Pfeffer gemahlen",
        "salt": "Jodsalz",
    },
    "Pasta arrabbiata": {
        "penne": "REWE Penne 500 g",
        "tomato passata": "REWE Bio Passata 700 g",
        "garlic": "REWE Knoblauch",
        "chili flakes": "Chiliflocken 30 g",
        "oregano": "REWE Oregano gerebelt",
        "parsley": "REWE Petersilie",
        "olive oil": "REWE Natives Olivenöl extra",
        "parmesan": "Parmigiano Reggiano",
    },
    "Spinach ricotta tortellini": {
        "tortellini": "REWE Tortellini Ricotta Spinat",
        "spinach": "REWE Blattspinat",
        "ricotta": "REWE Ricotta 250 g",
        "garlic": "REWE Knoblauch",
        "cream": "REWE Kochsahne",
        "nutmeg": "Muskatnuss gemahlen",
        "parmesan": "Grana Padano gerieben",
    },
    "Creamy carbonara": {
        "spaghetti": "REWE Spaghetti 500 g",
        "eggs": "REWE Eier 10 Stück",
        "parmesan": "Parmigiano Reggiano",
        "bacon": "REWE Bacon Würfel",
        "black pepper": "Schwarzer Pfeffer",
        "olive oil": "REWE Olivenöl",
    },
    "Lasagna": {
        "lasagne sheets": "REWE Lasagneplatten",
        "ground beef": "Rinderhackfleisch 500 g",
        "onion": "REWE Zwiebeln",
        "garlic": "REWE Knoblauch",
        "tomato passata": "REWE Passierte Tomaten",
        "tomato paste": "REWE Tomatenmark",
        "vegetable broth": "REWE Gemüsebrühe",
        "milk": "REWE H-Milch",
        "butter": "REWE Butter",
        "flour": "REWE Weizenmehl Type 405",
        "parmesan": "Parmigiano Reggiano",
        "oregano": "REWE Oregano",
        "nutmeg": "Muskat",
    },
    "Pizza": {
        "pizza dough": "REWE Pizzateig",
        "mozzarella": "REWE Mozzarella",
        "tomato sauce": "REWE Tomatensauce",
        "basil": "REWE Basilikum",
        "oregano": "REWE Oregano",
        "mushrooms": "REWE Champignons",
        "olive oil": "REWE Olivenöl",
    },
    "Garlic shrimp pasta": {
        "shrimp": "REWE Garnelen roh 200 g",
        "tagliatelle": "REWE Tagliatelle",
        "garlic": "REWE Knoblauch",
        "lemon": "REWE Zitronen",
        "parsley": "REWE Petersilie",
        "chili flakes": "REWE Chiliflocken",
        "butter": "REWE Butter",
        "olive oil": "REWE Olivenöl",
    },
    "Creamy salmon spinach rice": {
        "salmon": "REWE Lachsfilet",
        "spinach": "REWE Blattspinat",
        "rice": "REWE Basmatireis",
        "cream": "REWE Sahne",
        "dill": "REWE Dill",
        "lemon": "REWE Zitronen",
        "garlic": "REWE Knoblauch",
        "black pepper": "REWE Schwarzer Pfeffer",
    },
}

def main():
    total = 0
    failures = []
    for recipe, ingredients in RECIPES.items():
        for ingredient, title in ingredients.items():
            total += 1
            match = ingredient_product_match_type(ingredient, title)
            if match != "exact":
                failures.append((recipe, ingredient, title, match))
    assert not failures, f"Recipe ingredient coverage failures: {failures}"

    # Specific pantry seasonings and German spellings must be discoverable.
    for ingredient, german_title in [
        ("chili flakes", "Chiliflocken"),
        ("oregano", "Oregano gerebelt"),
        ("thyme", "Thymian"),
        ("nutmeg", "Muskat gemahlen"),
        ("vegetable broth", "Gemüsebrühe"),
        ("chicken broth", "Hühnerbrühe"),
        ("ricotta", "Ricotta"),
        ("basil", "Basilikum"),
        ("tagliatelle", "Bandnudeln"),
    ]:
        assert ingredient_product_match_type(ingredient, german_title) == "exact", (
            ingredient, german_title, ingredient_search_terms(ingredient)
        )

    # Classification must distinguish recipe components from complete prepared meals.
    assert classify_product({"name_original": "REWE Bio Passata 700 g", "category": "fertiggerichte-konserven"}).product_type == "prepared_component"
    assert classify_product({"name_original": "REWE Lasagneplatten 500 g"}).is_complete_meal is False
    assert classify_product({"name_original": "REWE Garnelen Curry Fertiggericht 400 g"}).is_complete_meal is True
    assert classify_product({"name_original": "REWE Pizza Margherita 350 g"}).is_complete_meal is True
    assert classify_product({"name_original": "REWE Basilikum"}).is_complete_meal is False

    print(f"PASS: {len(RECIPES)} recipe families, {total} ingredient titles, German herbs/spices/broths, and meal-vs-component classification")

if __name__ == "__main__":
    main()
