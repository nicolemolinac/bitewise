"""Offline regression QA for the product-intelligence taxonomy."""
from app.catalog.intelligence import classify_product

def profile(name, category=""):
    return classify_product({"name_original": name, "category": category})

def run():
    lasagne = profile("ja! Lasagne Bolognese 1 kg", "fertiggerichte-konserven")
    assert lasagne.is_complete_meal and lasagne.product_type == "ready_meal"
    assert "lasagna" in lasagne.dish_families

    passata = profile("REWE Bio Passata 700 g", "oele-sossen-gewuerze")
    assert not passata.is_complete_meal
    assert passata.product_type == "prepared_component" and passata.culinary_role == "sauce"
    canned_tomatoes = profile("REWE gehackte Tomaten 400 g", "fertiggerichte-konserven")
    assert not canned_tomatoes.is_complete_meal, "Canned aisle membership must not imply a ready meal"
    lasagne_sheets = profile("ja! Lasagneplatten 500 g", "kochen-backen")
    assert not lasagne_sheets.is_complete_meal and lasagne_sheets.culinary_role == "starch"

    pasta = profile("Barilla Penne Rigate 500 g", "kochen-backen")
    assert not pasta.is_complete_meal and pasta.culinary_role == "starch"
    assert pasta.preparation_state == "dry"

    chicken = profile("Hähnchen-Filetstreifen gebraten 125 g", "fleisch-wurst-fisch")
    assert not chicken.is_complete_meal
    assert chicken.product_type == "prepared_component" and chicken.culinary_role == "protein"

    frozen = profile("REWE Bio Brokkoli 750 g", "tiefkuehlkost")
    assert frozen.storage_type == "frozen" and frozen.culinary_role == "vegetable"

    # Beverage and confectionery aisles must not leak flavor claims into ingredient matching.
    soda = profile("7UP Zero Zucker 440ml", "getraenke-genussmittel")
    assert soda.product_type == "beverage" and soda.culinary_role == "beverage"
    juice = profile("Active O2 Apfel-Kiwi 0,75l", "getraenke-genussmittel")
    assert juice.product_type == "beverage"
    wine = profile("1112 Weißwein Blanc de Noirs trocken 0,75l", "getraenke-genussmittel")
    assert wine.product_type == "ingredient", "Cooking wine remains eligible as a recipe ingredient"
    candy = profile("ahead Low Sugar Gummies Sweet Cherries 50g", "suesses-salziges")
    assert candy.product_type == "snack" and candy.culinary_role == "snack"
    protein_bar = profile("Premier Protein Riegel Chocolate Caramel 40g", "kaese-eier-molkerei")
    assert protein_bar.product_type == "snack" and protein_bar.culinary_role == "snack"
    protein_dessert = profile("Ehrmann High Protein Chocolate & Topping 200g", "kaese-eier-molkerei")
    assert protein_dessert.product_type == "prepared_component" and protein_dessert.culinary_role == "dessert"
    chia = profile("Alnatura Bio Chia Samen 200g", "suesses-salziges")
    assert chia.product_type == "ingredient", "Plain seeds remain eligible as recipe ingredients"

    # Full-catalog audit found canned soups, stews, salads and frozen composed
    # dishes that had been left as generic ingredients.
    dessert = profile("Dr. Oetker High Protein Milchreis 400g", "kaese-eier-molkerei")
    assert dessert.product_type == "prepared_component" and dessert.culinary_role == "dessert"
    frozen_torte = profile("Almondy Daim Schokoladen-Torte 400g", "tiefkuehlkost")
    assert frozen_torte.product_type == "prepared_component" and frozen_torte.culinary_role == "dessert"
    frozen_ice_cream = profile("Ben & Jerry's Chocolate Chip Cookie Dough 170g", "tiefkuehlkost")
    assert frozen_ice_cream.product_type == "prepared_component" and frozen_ice_cream.culinary_role == "dessert"
    protein_chocolate = profile("Ehrmann High Protein Chocolate & Topping 200g", "kaese-eier-molkerei")
    assert protein_chocolate.product_type == "prepared_component" and protein_chocolate.culinary_role == "dessert"
    soup = profile("Erasco Tomaten-Cremesuppe 390ml", "fertiggerichte-konserven")
    assert soup.product_type == "prepared_component" and soup.culinary_role == "soup"
    salad = profile("Golßener Spreewälder Nudelsalat 700g", "fertiggerichte-konserven")
    assert salad.product_type == "prepared_component" and salad.culinary_role == "salad"
    stew = profile("Erasco Erbsen-Eintopf 400g", "fertiggerichte-konserven")
    assert stew.product_type == "ready_meal" and stew.is_complete_meal
    frikassee = profile("Frosta Hühnerfrikassee 500g", "tiefkuehlkost")
    assert frikassee.product_type == "ready_meal" and frikassee.is_complete_meal
    bami = profile("Frosta Bami Goreng 500g", "tiefkuehlkost")
    assert bami.product_type == "ready_meal" and bami.is_complete_meal
    gulasch = profile("Erasco Rindergulasch 480g", "fertiggerichte-konserven")
    assert gulasch.product_type == "ready_meal" and gulasch.is_complete_meal
    gulaschtopf = profile("Maggi 5 Minuten Terrine Gulaschtopf 57g", "fertiggerichte-konserven")
    assert gulaschtopf.product_type == "ready_meal" and gulaschtopf.is_complete_meal
    ravioli_meal = profile("Maggi Ravioli Bolognese 800g", "fertiggerichte-konserven")
    assert ravioli_meal.product_type == "ready_meal" and ravioli_meal.is_complete_meal
    rouladen = profile("Dreistern Gourmet Rinderrouladen 500g", "fertiggerichte-konserven")
    assert rouladen.product_type == "ready_meal" and rouladen.is_complete_meal
    maultaschen = profile("Bürger Gemüse-Maultaschen 360g", "fertiggerichte-konserven")
    assert maultaschen.product_type == "prepared_component" and maultaschen.culinary_role == "filled_pasta"
    frozen_skillet = profile("Frosta Bratkartoffel-Hähnchenpfanne 500g", "tiefkuehlkost")
    vegetable_pan = profile("Frosta Gemüse Pfanne All' Italiana 480g", "tiefkuehlkost")
    assert not vegetable_pan.is_complete_meal, "A plain vegetable pan must not be promoted to a full meal"
    assert frozen_skillet.product_type == "ready_meal" and frozen_skillet.is_complete_meal
    frozen_curry = profile("Every Red Curry 450g", "tiefkuehlkost")
    assert frozen_curry.product_type == "ready_meal" and frozen_curry.is_complete_meal
    frozen_pasta = profile("Frosta Tortellini Käse-Sahne 500g", "tiefkuehlkost")
    assert frozen_pasta.product_type == "ready_meal" and frozen_pasta.is_complete_meal
    nuggets = profile("ja! Chicken Nuggets 500g", "tiefkuehlkost")
    assert nuggets.product_type == "prepared_component" and nuggets.culinary_role == "protein"
    burger_patties = profile("Beyond Meat Beyond Burger vegan 226g", "tiefkuehlkost")
    assert burger_patties.product_type == "prepared_component" and burger_patties.culinary_role == "protein"
    potato_wedges = profile("ja! Kartoffel Wedges 750g", "tiefkuehlkost")
    assert potato_wedges.product_type == "prepared_component" and potato_wedges.culinary_role == "potato_side"
    potato_casserole = profile("Pahmeyer Kartoffelauflauf Klassik 300g", "fertiggerichte-konserven")
    assert potato_casserole.product_type == "ready_meal" and potato_casserole.is_complete_meal
    knorr_mix = profile("Knorr Fix Spaghetti Bolognese 40g", "fertiggerichte-konserven")
    assert knorr_mix.product_type == "prepared_component" and knorr_mix.culinary_role == "seasoning_mix"
    assert not knorr_mix.is_complete_meal, "A recipe-mix sachet is not a complete meal"
    ostmann_mix = profile("Ostmann Lets do Airfryer Chicken 70g", "oele-sossen-gewuerze")
    assert ostmann_mix.product_type == "prepared_component" and ostmann_mix.culinary_role == "seasoning_mix"
    spice_mix = profile("Maggi Würzmischung für Air Fryer Hähnchen 60g", "oele-sossen-gewuerze")
    assert spice_mix.product_type == "prepared_component" and spice_mix.culinary_role == "seasoning_mix"

    # Products from household, hygiene, pet and baby aisles must never become
    # culinary ingredients, even when their names contain ingredient words.
    for title, category in (
        ("Babywell Windeln Gr. 4", "baby-kind"),
        ("Bübchen Baby Shampoo Sensitiv", "baby-kind"),
        ("Purina Felix Huhn", "tierbedarf"),
        ("REWE Lemon WC Reiniger", "drogerie-gesundheit"),
        ("REWE Küchenrolle", "kueche-haushalt"),
    ):
        excluded = profile(title, category)
        assert excluded.product_type == "non_food"
        assert excluded.culinary_role == "non_food"
    print("Product intelligence taxonomy QA passed.")

if __name__ == "__main__":
    run()
