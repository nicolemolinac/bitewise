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
