"""Model-authored prompt-to-recipe QA: 50 distinct prompts and plausible two-serving recipes.

These are authored by the assistant as a stand-in for an LLM response, not returned by Gemini.
The test then exercises Bitewise's real consolidation and basket optimizer.
"""
import math
from collections import defaultdict

from app.ingredient_aliases import canonical_ingredient
from app.rewe.seed_products import PRODUCTS
from app.shopping.optimizer import _convert_quantity, build_basket, consolidate


def I(name, qty, unit="g"):
    return [name, qty, unit]


# Each entry represents a distinct natural-language user prompt and a complete recipe
# that an LLM could reasonably return for two servings.
CASES = [
("Lemon chicken couscous", "Quick Mediterranean dinner for two, high protein, under 25 minutes.", [I("chicken breast",280),I("couscous",140),I("cherry tomatoes",160),I("cucumber",120),I("lemon",1,"piece"),I("olive oil",15,"ml"),I("greek yogurt",80)]),
("Creamy mushroom tagliatelle", "Vegetarian creamy pasta for two using mushrooms, no meat, comforting but not huge portions.", [I("tagliatelle",180),I("mushrooms",220),I("cream",100,"ml"),I("parmesan",30),I("garlic",2,"cloves"),I("butter",15)]),
("Salmon teriyaki rice bowls", "Japanese-inspired salmon bowls for two, balanced, with a homemade quick teriyaki glaze.", [I("salmon",280),I("rice",150),I("broccoli",180),I("soy sauce",30,"ml"),I("honey",15),I("ginger",10),I("sesame",8)]),
("Chickpea coconut curry", "Cheap vegan curry for two, pantry-friendly, serve with rice.", [I("chickpeas",240),I("coconut milk",200,"ml"),I("tomatoes",200),I("spinach",100),I("onion",1,"piece"),I("rice",140),I("curry powder",8)]),
("Spinach feta omelette", "Fast high-protein vegetarian dinner for two, use eggs and spinach, minimal washing-up.", [I("eggs",4,"piece"),I("spinach",100),I("feta",60),I("cherry tomatoes",100),I("olive oil",5,"ml"),I("bread",100)]),
("Turkey avocado wraps", "No-fuss lunch for two, high protein, no cooking if possible.", [I("tortillas",2,"piece"),I("turkey breast",160),I("avocado",1,"piece"),I("lettuce",40),I("tomato",1,"piece"),I("greek yogurt",40)]),
("Beef and broccoli stir-fry", "Takeaway-style beef broccoli stir-fry for two with rice, not too salty.", [I("beef",250),I("broccoli",200),I("rice",150),I("soy sauce",25,"ml"),I("cornstarch",8),I("garlic",2,"cloves"),I("sesame oil",5,"ml")]),
("Roasted tomato mozzarella gnocchi", "Easy vegetarian oven-style gnocchi for two with tomato and mozzarella.", [I("gnocchi",400),I("tomatoes",250),I("mozzarella",125),I("basil",10),I("olive oil",10,"ml"),I("garlic",1,"clove")]),
("Red lentil dal", "Low-cost vegan Indian-style dal for two, filling, with rice.", [I("red lentils",160),I("tomatoes",200),I("onion",1,"piece"),I("coconut milk",100,"ml"),I("rice",140),I("garlic",2,"cloves"),I("ginger",10)]),
("Tuna white bean salad", "High-protein no-cook lunch for two, use canned tuna and white beans.", [I("tuna",1,"can"),I("white beans",240),I("cucumber",120),I("red onion",40),I("lemon",0.5,"piece"),I("olive oil",15,"ml"),I("parsley",8)]),
("Pesto chicken pasta", "Simple high-protein pasta for two with pesto and chicken, 20 minutes.", [I("pasta",180),I("chicken breast",240),I("pesto",50),I("cherry tomatoes",120),I("parmesan",20)]),
("Sweet potato black bean tacos", "Vegetarian taco night for two, inexpensive, include a fresh topping.", [I("sweet potato",300),I("black beans",240),I("tortillas",4,"piece"),I("avocado",1,"piece"),I("lime",1,"piece"),I("red cabbage",100)]),
("Garlic shrimp noodles", "Quick Asian-inspired shrimp noodles for two, lots of vegetables, no deep frying.", [I("shrimp",220),I("noodles",160),I("carrot",100),I("spring onion",2,"piece"),I("soy sauce",25,"ml"),I("garlic",2,"cloves"),I("lime",0.5,"piece")]),
("Greek chicken tray bake", "Low-effort Mediterranean sheet-pan meal for two with chicken, potatoes and feta.", [I("chicken breast",260),I("potatoes",350),I("red onion",1,"piece"),I("bell pepper",1,"piece"),I("feta",50),I("olive oil",15,"ml"),I("oregano",2)]),
("Pumpkin sage risotto", "Vegetarian autumn risotto for two, creamy without adding lots of cream.", [I("arborio rice",160),I("pumpkin",250),I("onion",60),I("vegetable stock",500,"ml"),I("parmesan",30),I("butter",15),I("sage",5)]),
("Tofu peanut noodles", "Vegan high-protein noodle bowl for two with peanut sauce, mildly spicy.", [I("tofu",250),I("noodles",160),I("peanut butter",30),I("soy sauce",20,"ml"),I("lime",1,"piece"),I("cucumber",100),I("carrot",80)]),
("Baked cod with potatoes", "Light fish dinner for two, oven baked, simple lemon-herb flavour.", [I("cod",280),I("potatoes",350),I("green beans",160),I("lemon",1,"piece"),I("olive oil",12,"ml"),I("parsley",8)]),
("Caprese chickpea bowls", "Fast vegetarian Mediterranean lunch for two, no stove, satisfying.", [I("chickpeas",240),I("mozzarella",125),I("tomatoes",200),I("basil",10),I("olive oil",12,"ml"),I("bread",100)]),
("Pork tenderloin apple skillet", "Dinner for two with pork and apple, balanced, one-pan preparation.", [I("pork",260),I("apple",1,"piece"),I("potatoes",300),I("onion",60),I("mustard",15),I("cream",60,"ml")]),
("Breakfast overnight oats", "Prepare-ahead breakfast for two, high fibre, not overly sweet.", [I("oats",100),I("milk",200,"ml"),I("greek yogurt",100),I("blueberries",100),I("chia seeds",15),I("honey",10)]),
("Banana oat pancakes", "Weekend breakfast for two, fluffy pancakes without protein powder.", [I("banana",1,"piece"),I("eggs",2,"piece"),I("oats",90),I("milk",60,"ml"),I("baking powder",4),I("blueberries",60)]),
("Apple cinnamon baked oats", "Healthy warm breakfast for two, oven or air fryer friendly.", [I("oats",100),I("apple",1,"piece"),I("eggs",1,"piece"),I("milk",120,"ml"),I("cinnamon",2),I("maple syrup",15)]),
("Greek yogurt berry parfait", "Five-minute high-protein breakfast for two, no cooking.", [I("greek yogurt",300),I("berries",120),I("granola",60),I("honey",10),I("walnuts",15)]),
("Shakshuka", "Middle Eastern eggs in tomato-pepper sauce for two, serve with bread.", [I("eggs",4,"piece"),I("tomatoes",300),I("bell pepper",1,"piece"),I("onion",80),I("garlic",2,"cloves"),I("feta",40),I("bread",100)]),
("Smoked salmon bagels", "Quick brunch for two, no cooking, fresh and balanced.", [I("bagels",2,"piece"),I("smoked salmon",100),I("cream cheese",60),I("cucumber",80),I("dill",5),I("lemon",0.5,"piece")]),
("Chicken Caesar salad", "Restaurant-style chicken Caesar salad for two, lighter dressing, include croutons.", [I("chicken breast",240),I("lettuce",180),I("parmesan",25),I("greek yogurt",60),I("bread",60),I("lemon",0.5,"piece"),I("garlic",1,"clove")]),
("Roasted beetroot goat cheese salad", "Vegetarian warm salad for two with beetroot, goat cheese and walnuts.", [I("beetroot",250),I("goat cheese",80),I("walnuts",20),I("rocket",50),I("balsamic vinegar",15,"ml"),I("bread",80)]),
("Miso aubergine rice", "Japanese-inspired vegetarian dinner for two, umami-rich, easy ingredients.", [I("eggplant",1,"piece"),I("rice",150),I("miso",30),I("soy sauce",10,"ml"),I("honey",10),I("sesame",8),I("spring onion",1,"piece")]),
("Sausage white bean stew", "Hearty one-pot dinner for two, inexpensive, use sausages and canned beans.", [I("sausage",2,"piece"),I("white beans",240),I("tomatoes",200),I("carrot",100),I("onion",80),I("vegetable stock",250,"ml")]),
("Turkey meatballs tomato orzo", "Family-style but scaled for two, lean turkey meatballs with orzo.", [I("ground turkey",250),I("orzo",140),I("tomato sauce",200),I("parmesan",20),I("breadcrumbs",20),I("egg",1,"piece"),I("garlic",1,"clove")]),
("Halloumi couscous bowls", "Vegetarian high-protein lunch for two with grilled halloumi and vegetables.", [I("halloumi",180),I("couscous",140),I("zucchini",150),I("cherry tomatoes",120),I("cucumber",80),I("lemon",1,"piece"),I("mint",5)]),
("Thai green curry chicken", "Thai-inspired chicken curry for two, moderate heat, serve with jasmine rice.", [I("chicken breast",250),I("coconut milk",200,"ml"),I("green curry paste",25),I("bell pepper",1,"piece"),I("zucchini",100),I("rice",140),I("lime",1,"piece")]),
("Vegetable fried rice", "Use leftover cooked rice for a quick vegetarian dinner for two; include egg and peas.", [I("rice",300),I("eggs",2,"piece"),I("peas",80),I("carrot",80),I("spring onion",1,"piece"),I("soy sauce",20,"ml"),I("sesame oil",5,"ml")]),
("Lemon ricotta ravioli", "Fast vegetarian pasta dinner for two with a light lemon ricotta sauce.", [I("ravioli",300),I("ricotta",100),I("lemon",1,"piece"),I("spinach",80),I("parmesan",20),I("butter",10)]),
("Stuffed bell peppers", "Oven-baked vegetarian stuffed peppers for two with rice and beans.", [I("bell pepper",2,"piece"),I("rice",100),I("kidney beans",120),I("tomatoes",150),I("cheese",50),I("onion",50)]),
("Moroccan chickpea couscous", "Vegan budget dinner for two with chickpeas, raisins and warm spices.", [I("chickpeas",240),I("couscous",140),I("carrot",100),I("raisins",25),I("vegetable stock",180,"ml"),I("cumin",3),I("lemon",0.5,"piece")]),
("Steak chimichurri potatoes", "Higher-protein dinner for two, steak with potatoes and fresh herb sauce.", [I("beef steak",280),I("potatoes",350),I("parsley",15),I("garlic",2,"cloves"),I("red wine vinegar",10,"ml"),I("olive oil",20,"ml")]),
("Creamy chicken spinach soup", "Comforting one-pot soup for two, chicken, spinach and modest cream.", [I("chicken breast",180),I("spinach",100),I("potatoes",180),I("chicken stock",500,"ml"),I("cream",60,"ml"),I("onion",50)]),
("Prawn mango rice salad", "Fresh summery lunch for two with prawns, mango and lime dressing.", [I("shrimp",180),I("rice",120),I("mango",1,"piece"),I("cucumber",100),I("lime",1,"piece"),I("coriander",8)]),
("Broccoli cheddar baked potatoes", "Cheap vegetarian comfort food for two, baked potatoes topped with broccoli and cheese.", [I("potatoes",400),I("broccoli",180),I("cheddar",70),I("greek yogurt",40),I("spring onion",1,"piece")]),
("Lentil bolognese", "Vegetarian high-fibre pasta sauce for two, no meat, rich tomato flavour.", [I("pasta",180),I("red lentils",100),I("tomato passata",250),I("carrot",80),I("onion",60),I("parmesan",20)]),
("Crispy tofu rice paper rolls", "Fresh vegan rolls for two with tofu and crunchy vegetables, peanut dip.", [I("rice paper",6,"piece"),I("tofu",160),I("carrot",80),I("cucumber",80),I("lettuce",40),I("peanut butter",25),I("soy sauce",10,"ml")]),
("Air-fryer paprika chicken", "Air fryer dinner for two, minimal cleanup, chicken thighs with vegetables.", [I("chicken thighs",300),I("potatoes",300),I("bell pepper",1,"piece"),I("zucchini",120),I("olive oil",12,"ml"),I("paprika powder",4)]),
("Quick tomato lentil soup", "Very cheap vegan soup for two using canned lentils, one pot, under 20 minutes.", [I("lentils",240),I("tomatoes",200),I("carrot",80),I("onion",60),I("vegetable stock",400,"ml"),I("bread",80)]),
("Pesto mozzarella flatbreads", "Fast vegetarian dinner for two, use ready flatbreads and few ingredients.", [I("flatbread",2,"piece"),I("pesto",35),I("mozzarella",125),I("cherry tomatoes",120),I("rocket",30)]),
("Coconut chia pudding", "Make-ahead dairy-free dessert for two, lightly sweetened with fruit.", [I("chia seeds",35),I("coconut milk",180,"ml"),I("maple syrup",10),I("mango",0.5,"piece"),I("lime",0.5,"piece")]),
("Dark chocolate strawberries", "Simple romantic dessert for two, small portions, no baking.", [I("dark chocolate",80),I("strawberries",200),I("cream",20,"ml")]),
("Apple crumble", "Classic small-batch dessert for two, not too sweet, serve warm.", [I("apple",2,"piece"),I("flour",60),I("oats",30),I("butter",35),I("brown sugar",25),I("cinnamon",1)]),
("Banana peanut smoothie", "Quick filling breakfast smoothie for two, no protein powder.", [I("banana",2,"piece"),I("milk",250,"ml"),I("peanut butter",25),I("oats",30),I("greek yogurt",80)]),
("Carrot ginger soup", "Light vegan soup for two, smooth texture, use coconut milk sparingly.", [I("carrot",300),I("onion",60),I("ginger",12),I("vegetable stock",400,"ml"),I("coconut milk",60,"ml"),I("olive oil",8,"ml")]),
]


class Catalog:
    def __init__(self):
        self.rows = defaultdict(list)
        for index, p in enumerate(PRODUCTS, 1):
            self.rows[canonical_ingredient(p["ingredient"])].append({
                "id": index, "ingredient": p["ingredient"], "name_original": p["name"],
                "name": p["name"], "package_size": p["pack_qty"], "package_unit": p["unit"],
                "price": p["price"], "price_per_unit": p["unit_price"], "availability": "available",
            })

    def search(self, ingredient):
        return self.rows.get(canonical_ingredient(ingredient), [])


def main():
    assert len(CASES) == 50, f"Expected 50 generated recipes, got {len(CASES)}"
    assert len({x[0] for x in CASES}) == 50, "Recipe names must be distinct"
    assert len({x[1] for x in CASES}) == 50, "Prompts must be distinct"
    meals = [{"id": f"model-qa-{i:02d}", "name": name, "ingredients": ingredients}
             for i, (name, prompt, ingredients) in enumerate(CASES, 1)]

    # Semantic checks: ingredient/unit compatibility, realistic amounts for two servings,
    # coherent recipe size and no malformed/empty ingredients.
    count_units = {"piece", "clove", "can"}
    volume_units = {"ml"}
    mass_units = {"g"}
    for name, prompt, ingredients in CASES:
        assert len(ingredients) >= 3, name
        assert prompt and len(prompt) >= 25, name
        for ingredient, quantity, unit in ingredients:
            assert ingredient and isinstance(quantity, (int, float)) and math.isfinite(quantity) and quantity > 0, (name, ingredient)
            assert unit in mass_units | volume_units | count_units, (name, ingredient, unit)
            if unit == "g":
                assert 1 <= quantity <= 600, (name, ingredient, quantity, unit)
            elif unit == "ml":
                assert 1 <= quantity <= 600, (name, ingredient, quantity, unit)
            elif unit == "piece":
                assert quantity <= 6, (name, ingredient, quantity, unit)
            elif unit == "clove":
                assert quantity <= 6, (name, ingredient, quantity, unit)
            elif unit == "can":
                assert quantity <= 3, (name, ingredient, quantity, unit)

    # Validate scaling and aggregation against independently calculated totals.
    expected = defaultdict(float)
    sources = defaultdict(set)
    for meal in meals:
        for ingredient, quantity, unit in meal["ingredients"]:
            normalized_unit = {"cloves": "clove", "units": "piece", "pieces": "piece"}.get(unit, unit)
            key = (canonical_ingredient(ingredient), normalized_unit)
            expected[key] += quantity
            sources[key].add(meal["name"])
    requirements = consolidate(meals, {meal["id"]: 2 for meal in meals})
    actual = {(r["ingredient"], r["unit"]): r for r in requirements}
    assert set(actual) == set(expected), (set(expected)-set(actual), set(actual)-set(expected))
    for key, qty in expected.items():
        assert math.isclose(actual[key]["quantity"], qty, rel_tol=1e-6), (key, qty, actual[key])
        assert set(actual[key]["source_meals"]) == sources[key], key

    for servings in (1, 4):
        scaled = consolidate(meals, {meal["id"]: servings for meal in meals})
        scaled_map = {(r["ingredient"], r["unit"]): r["quantity"] for r in scaled}
        for key, qty in expected.items():
            assert math.isclose(scaled_map[key], qty * servings / 2, rel_tol=1e-6), (servings, key)

    basket = build_basket(requirements, Catalog(), mode="best-value")
    assert len(basket) == len(requirements)
    matched = [r for r in basket if r["match_status"] == "matched"]
    unmatched = [r for r in basket if r["match_status"] == "unmatched"]
    for row in matched:
        product = row["product"]
        needed_in_pack_unit = _convert_quantity(row["needed_quantity"], row["unit"], row["package_unit"])
        assert product and needed_in_pack_unit is not None and needed_in_pack_unit > 0, row
        assert row["packs"] == max(1, math.ceil(needed_in_pack_unit / product["package_size"])), row
        assert row["package_quantity"] >= needed_in_pack_unit - 1e-6, row
        assert math.isclose(row["checkout_cost"], row["packs"] * product["price"], abs_tol=.011), row
    for row in unmatched:
        assert row["product"] is None and row["packs"] == 0 and row["checkout_cost"] == 0, row

    # Dimensional safety and count semantics: cloves, cans and pieces must not be
    # silently converted into grams/ml or conflated with one another.
    assert _convert_quantity(2, "cloves", "g") is None
    assert _convert_quantity(1, "can", "g") is None
    assert _convert_quantity(1, "piece", "clove") is None
    print(
        f"MODEL-AUTHORED QA PASS: {len(CASES)} unique prompts and recipes; "
        f"{sum(len(x[2]) for x in CASES)} ingredient lines; {len(requirements)} "
        f"consolidated requirements; {len(matched)} catalog matches; "
        f"{len(unmatched)} safely unmatched. Prompt diversity, culinary quantity "
        "guardrails, unit semantics, scaling, aggregation and basket package math verified."
    )


if __name__ == "__main__":
    main()
