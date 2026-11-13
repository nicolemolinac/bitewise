"""Real-catalog benchmark: 20 representative recipes against the local REWE database.

Run from backend/: python qa_recipe_match_benchmark.py
Read-only: no Gemini calls, no scraping, no DB writes, no pantry assumptions.
Requires the local REWE catalog; semantic suggestions are included only if its local
embedding index has already been built.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from collections import Counter

# CI can benchmark the committed REWE snapshot in a disposable database.
# Normal local runs continue to inspect the user's existing local REWE catalog
# (including its already-built semantic vectors) without changing that database.
_BENCHMARK_DB = None
if os.getenv("BITEWISE_BENCHMARK_ISOLATED", "").strip().lower() in {"1", "true", "yes", "on"}:
    _BENCHMARK_DB = tempfile.TemporaryDirectory(prefix="bitewise-recipe-match-benchmark-")
    os.environ["DATABASE_URL"] = ""
    os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_BENCHMARK_DB.name) / "benchmark.sqlite")
    os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
    os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

from app import server  # installs the multilingual CatalogAdapter.search override
from app.database import Product, ProductSemanticEmbedding, SessionLocal
from app.ingredient_intelligence import (
    _category_compatible, _form_compatible,
    ingredient_candidate_search_terms, ingredient_product_match_type,
    ingredient_search_terms, normalize_recipe_intelligence,
    normalize_text,
)
from app.shopping.optimizer import _convert_ingredient_quantity, build_basket, consolidate


# Each ingredient carries the same kind of cached multilingual retail metadata that
# recipe generation is expected to save. This benchmark deliberately makes no LLM calls.
def I(name, de, aliases=(), form="unspecified", role=""):
    return {
        "canonical": name,
        "name_en": name,
        "name_de": de,
        "name_es": "",
        "aliases": list(aliases),
        "form": form,
        "culinary_role": role,
        "unit_dimension": "",
        "suggested_substitutions": [],
        "preparation": "",
    }


def R(recipe_id, name, rows):
    ingredients = [[row[0], row[1], row[2]] for row in rows]
    intelligence = {
        row[0]: I(row[0], row[3], row[4], row[5], row[6] if len(row) > 6 else "")
        for row in rows
    }
    recipe = {
        "id": recipe_id,
        "name": name,
        "base_servings": 2,
        "ingredients": ingredients,
        "ingredient_intelligence": intelligence,
    }
    recipe["ingredient_intelligence"] = normalize_recipe_intelligence(recipe)
    return recipe


RECIPES = [
    R("b01", "Chicken fajita bowls", [
        ("chicken breast", 300, "g", "Hähnchenbrust", ["Hähnchen Brustfilet"], "fresh"),
        ("bell pepper", 1, "piece", "Paprika", ["rote Paprika"], "fresh"),
        ("red onion", 1, "piece", "rote Zwiebel", ["rote Speisezwiebel"], "fresh"),
        ("rice", 150, "g", "Reis", ["Langkornreis"], "unspecified"),
        ("black beans", 150, "g", "schwarze Bohnen", ["schwarze Bohnen Dose"], "canned"),
        ("lime", 1, "piece", "Limette", ["Limetten"], "fresh"),
        ("vegetable oil", 15, "ml", "Pflanzenöl", ["Rapsöl", "Sonnenblumenöl"], "liquid"),
    ]),
    R("b02", "Spaghetti bolognese", [
        ("spaghetti", 180, "g", "Spaghetti", ["Hartweizengrieß Spaghetti"], "unspecified"),
        ("ground beef", 250, "g", "Rinderhackfleisch", ["Hackfleisch vom Rind"], "fresh"),
        ("tomato passata", 250, "g", "passierte Tomaten", ["Passata", "Tomaten passiert"], "liquid"),
        ("onion", 1, "piece", "Speisezwiebel", ["Zwiebeln"], "fresh"),
        ("garlic", 2, "cloves", "Knoblauch", ["Knoblauchzehen"], "fresh"),
        ("parmesan cheese", 30, "g", "Parmesan gerieben", ["Parmigiano Reggiano", "Parmesan"], "grated"),
    ]),
    R("b03", "Salmon and potato tray bake", [
        ("salmon fillet", 250, "g", "Lachsfilet", ["Lachs Filet"], "fresh"),
        ("potatoes", 350, "g", "Speisekartoffeln", ["Kartoffeln"], "fresh"),
        ("broccoli", 200, "g", "Brokkoli", ["Broccoli"], "fresh"),
        ("lemon", 1, "piece", "Zitrone", ["Zitronen"], "fresh"),
        ("olive oil", 15, "ml", "Olivenöl", ["natives Olivenöl"], "liquid"),
    ]),
    R("b04", "Greek salad", [
        ("cucumber", 1, "piece", "Salatgurke", ["Gurke"], "fresh"),
        ("tomatoes", 200, "g", "Tomaten", ["Strauchtomaten"], "fresh"),
        ("feta cheese", 100, "g", "Feta", ["Hirtenkäse"], "unspecified"),
        ("black olives", 50, "g", "schwarze Oliven", ["Oliven schwarz"], "unspecified"),
        ("red onion", 0.5, "piece", "rote Zwiebel", ["rote Speisezwiebel"], "fresh"),
        ("olive oil", 15, "ml", "Olivenöl", ["natives Olivenöl"], "liquid"),
    ]),
    R("b05", "Beef tacos", [
        ("soft tortillas", 4, "piece", "Weizentortillas", ["Tortilla Wraps", "Weizen Wraps", "Weizentortillas", "Weizentortilla"], "soft"),
        ("ground beef", 250, "g", "Rinderhackfleisch", ["Hackfleisch vom Rind"], "fresh"),
        ("lettuce", 100, "g", "Eisbergsalat", ["Salatherzen", "Salat"], "fresh"),
        ("tomatoes", 150, "g", "Tomaten", ["Strauchtomaten"], "fresh"),
        ("grated cheddar cheese", 80, "g", "Cheddar gerieben", ["geriebener Cheddar"], "grated"),
        ("sour cream", 80, "g", "saure Sahne", ["Schmand", "Sauerrahm"], "unspecified"),
    ]),
    R("b06", "Chicken coconut curry", [
        ("chicken breast", 250, "g", "Hähnchenbrust", ["Hähnchen Brustfilet"], "fresh"),
        ("coconut milk", 200, "ml", "Kokosmilch", ["Kokosnussmilch"], "liquid"),
        ("curry powder", 2, "tsp", "Currypulver", ["Curry Gewürz"], "powder"),
        ("rice", 150, "g", "Reis", ["Langkornreis"], "unspecified"),
        ("onion", 1, "piece", "Speisezwiebel", ["Zwiebeln"], "fresh"),
        ("garlic", 2, "cloves", "Knoblauch", ["Knoblauchzehen"], "fresh"),
    ]),
    R("b07", "Banana pancakes", [
        ("wheat flour", 120, "g", "Weizenmehl", ["Mehl Type 405"], "unspecified"),
        ("milk", 150, "ml", "Milch", ["Frischmilch"], "liquid"),
        ("eggs", 2, "piece", "Eier", ["Freilandeier"], "unspecified"),
        ("baking powder", 1, "tsp", "Backpulver", ["Backpulver"], "powder"),
        ("banana", 1, "piece", "Bananen", ["Banane"], "fresh"),
        ("butter", 20, "g", "Butter", ["Deutsche Markenbutter"], "unspecified"),
    ]),
    R("b08", "Tuna sweetcorn pasta", [
        ("pasta", 180, "g", "Nudeln", ["Penne", "Fusilli"], "unspecified"),
        ("canned tuna", 120, "g", "Thunfisch in eigenem Saft", ["Thunfisch Dose"], "canned"),
        ("canned corn", 100, "g", "Mais aus der Dose", ["Dosenmais", "Zuckermais Konserve"], "canned"),
        ("mayonnaise", 30, "g", "Mayonnaise", ["Salatmayonnaise"], "unspecified"),
        ("frozen peas", 100, "g", "Erbsen tiefgekühlt", ["TK Erbsen"], "frozen"),
        ("lemon", 0.5, "piece", "Zitrone", ["Zitronen"], "fresh"),
    ]),
    R("b09", "Tofu vegetable stir-fry", [
        ("firm tofu", 200, "g", "Naturtofu", ["Tofu Natur"], "unspecified"),
        ("broccoli", 150, "g", "Brokkoli", ["Broccoli"], "fresh"),
        ("carrot", 1, "piece", "Möhre", ["Karotten"], "fresh"),
        ("soy sauce", 20, "ml", "Sojasauce", ["Soja Sauce"], "liquid"),
        ("rice", 150, "g", "Reis", ["Langkornreis"], "unspecified"),
        ("sesame oil", 10, "ml", "Sesamöl", ["geröstetes Sesamöl"], "liquid"),
    ]),
    R("b10", "Creamy potato soup", [
        ("potatoes", 350, "g", "Speisekartoffeln", ["Kartoffeln"], "fresh"),
        ("carrot", 1, "piece", "Möhre", ["Karotten"], "fresh"),
        ("onion", 1, "piece", "Speisezwiebel", ["Zwiebeln"], "fresh"),
        ("vegetable stock", 500, "ml", "Gemüsebrühe", ["Gemüse Bouillon"], "liquid"),
        ("cooking cream", 100, "ml", "Kochsahne", ["Sahne zum Kochen"], "liquid"),
        ("parsley", 10, "g", "Petersilie", ["Petersilienkraut"], "fresh"),
    ]),
    R("b11", "Cheeseburgers", [
        ("burger buns", 2, "piece", "Hamburger Brötchen", ["Burger Brötchen"], "unspecified"),
        ("ground beef", 250, "g", "Rinderhackfleisch", ["Hackfleisch vom Rind"], "fresh"),
        ("lettuce", 50, "g", "Eisbergsalat", ["Salatherzen", "Salat"], "fresh"),
        ("tomatoes", 100, "g", "Tomaten", ["Strauchtomaten"], "fresh"),
        ("cheese slices", 2, "piece", "Schmelzkäsescheiben", ["Burger Käse Scheiben"], "unspecified"),
        ("pickles", 30, "g", "Gewürzgurken", ["Cornichons", "Saure Gurken"], "unspecified"),
    ]),
    R("b12", "Chicken Caesar salad", [
        ("chicken breast", 200, "g", "Hähnchenbrust", ["Hähnchen Brustfilet"], "fresh"),
        ("romaine lettuce", 150, "g", "Romanasalat", ["Römersalat"], "fresh"),
        ("parmesan cheese", 25, "g", "Parmesan gerieben", ["Parmigiano Reggiano", "Parmesan"], "grated"),
        ("croutons", 30, "g", "Croûtons", ["Brotwürfel geröstet"], "unspecified"),
        ("caesar dressing", 40, "g", "Caesar Dressing", ["Salatdressing Caesar"], "liquid"),
    ]),
    R("b13", "Shakshuka", [
        ("eggs", 3, "piece", "Eier", ["Freilandeier"], "unspecified"),
        ("canned chopped tomatoes", 200, "g", "stückige Tomaten Dose", ["Tomatenstücke", "stückige Tomaten"], "canned"),
        ("bell pepper", 1, "piece", "Paprika", ["rote Paprika"], "fresh"),
        ("onion", 1, "piece", "Speisezwiebel", ["Zwiebeln"], "fresh"),
        ("cumin", 1, "tsp", "Kreuzkümmel gemahlen", ["Cumin", "Kreuzkümmel"], "powder"),
        ("paprika powder", 1, "tsp", "Paprikapulver edelsüß", ["Paprika edelsüß"], "powder"),
    ]),
    R("b14", "Black bean burritos", [
        ("soft tortillas", 2, "piece", "Weizentortillas", ["Tortilla Wraps", "Weizen Wraps"], "soft"),
        ("rice", 100, "g", "Reis", ["Langkornreis"], "unspecified"),
        ("black beans", 150, "g", "schwarze Bohnen", ["schwarze Bohnen Dose"], "canned"),
        ("canned corn", 80, "g", "Mais aus der Dose", ["Dosenmais", "Zuckermais Konserve"], "canned"),
        ("avocado", 1, "piece", "Avocado", ["Hass Avocado"], "fresh"),
        ("salsa", 50, "g", "Salsa Sauce", ["Tomatensalsa"], "liquid"),
    ]),
    R("b15", "Sausage and vegetable tray", [
        ("bratwurst", 250, "g", "Bratwurst", ["Rostbratwurst"], "fresh"),
        ("potatoes", 300, "g", "Speisekartoffeln", ["Kartoffeln"], "fresh"),
        ("carrot", 2, "piece", "Möhre", ["Karotten"], "fresh"),
        ("zucchini", 1, "piece", "Zucchini", ["Zucchini"], "fresh"),
        ("vegetable oil", 15, "ml", "Pflanzenöl", ["Rapsöl", "Sonnenblumenöl"], "liquid"),
    ]),
    R("b16", "Mushroom risotto", [
        ("risotto rice", 150, "g", "Risottoreis", ["Arborio Reis", "Rundkornreis"], "unspecified"),
        ("mushrooms", 150, "g", "Champignons", ["Weiße Champignons"], "fresh"),
        ("vegetable stock", 450, "ml", "Gemüsebrühe", ["Gemüse Bouillon"], "liquid"),
        ("parmesan cheese", 30, "g", "Parmesan gerieben", ["Parmigiano Reggiano", "Parmesan"], "grated"),
        ("butter", 15, "g", "Butter", ["Deutsche Markenbutter"], "unspecified"),
        ("onion", 1, "piece", "Speisezwiebel", ["Zwiebeln"], "fresh"),
    ]),
    R("b17", "Loaded baked potatoes", [
        ("potatoes", 350, "g", "Speisekartoffeln", ["Kartoffeln"], "fresh"),
        ("sour cream", 80, "g", "saure Sahne", ["Schmand", "Sauerrahm"], "unspecified"),
        ("spring onion", 1, "piece", "Frühlingszwiebel", ["Lauchzwiebel"], "fresh"),
        ("grated cheddar cheese", 50, "g", "Cheddar gerieben", ["geriebener Cheddar"], "grated"),
        ("bacon", 50, "g", "Bacon", ["Frühstücksspeck", "Bauchspeck"], "unspecified"),
        ("butter", 10, "g", "Butter", ["Deutsche Markenbutter"], "unspecified"),
    ]),
    R("b18", "Fish tacos", [
        ("white fish fillet", 200, "g", "Seelachsfilet", ["Kabeljaufilet", "Alaska Seelachs"], "fresh"),
        ("soft tortillas", 4, "piece", "Weizentortillas", ["Tortilla Wraps", "Weizen Wraps"], "soft"),
        ("red cabbage", 100, "g", "Rotkohl", ["Rotkraut"], "fresh"),
        ("lime", 1, "piece", "Limette", ["Limetten"], "fresh"),
        ("plain yogurt", 60, "g", "Naturjoghurt", ["Joghurt natur"], "unspecified"),
        ("fresh cilantro", 10, "g", "frischer Koriander", ["Koriandergrün", "Korianderkraut"], "fresh"),
    ]),
    R("b19", "Berry yogurt bowl", [
        ("greek yogurt", 200, "g", "griechischer Joghurt", ["Joghurt griechischer Art"], "unspecified"),
        ("strawberries", 100, "g", "Erdbeeren", ["frische Erdbeeren"], "fresh"),
        ("blueberries", 80, "g", "Heidelbeeren", ["Blaubeeren", "Kulturheidelbeeren"], "fresh"),
        ("rolled oats", 40, "g", "Haferflocken", ["zarte Haferflocken"], "unspecified"),
        ("honey", 15, "g", "Honig", ["Blütenhonig"], "liquid"),
        ("banana", 1, "piece", "Banane", ["Bananen"], "fresh"),
    ]),
    R("b20", "Vegetable pizza", [
        ("pizza dough", 250, "g", "Pizzateig", ["Frischer Pizzateig", "Pizzaboden"], "fresh"),
        ("mozzarella", 125, "g", "Mozzarella", ["Mozzarella Käse"], "unspecified"),
        ("tomato passata", 100, "g", "passierte Tomaten", ["Passata", "Tomaten passiert"], "liquid"),
        ("mushrooms", 100, "g", "Champignons", ["Weiße Champignons"], "fresh"),
        ("bell pepper", 0.5, "piece", "Paprika", ["rote Paprika"], "fresh"),
        ("oregano", 1, "tsp", "Oregano gerebelt", ["Oregano getrocknet"], "dried"),
    ]),
    R("b21", "Chorrillana chilena", [
        ("potatoes", 500, "g", "Speisekartoffeln", ["Kartoffeln"], "fresh"),
        ("beef steak", 250, "g", "Rinder-Minutensteaks", ["Rindersteak", "Rindergeschnetzeltes"], "fresh"),
        ("onion", 2, "piece", "Speisezwiebel", ["Zwiebeln"], "fresh"),
        ("eggs", 2, "piece", "Eier", ["Freilandeier"], "unspecified"),
        ("vegetable oil", 30, "ml", "Pflanzenöl", ["Rapsöl", "Sonnenblumenöl"], "liquid"),
    ]),
    R("b22", "Simple tomato pasta", [
        ("pasta", 180, "g", "Nudeln", ["Penne", "Fusilli", "Spaghetti"], "unspecified"),
        ("tomato passata", 250, "g", "passierte Tomaten", ["Passata", "Tomaten passiert"], "liquid"),
        ("garlic", 2, "cloves", "Knoblauch", ["Knoblauchzehen"], "fresh"),
        ("onion", 1, "piece", "Speisezwiebel", ["Zwiebeln"], "fresh"),
        ("olive oil", 15, "ml", "Olivenöl", ["natives Olivenöl"], "liquid"),
        ("parmesan cheese", 30, "g", "Parmesan gerieben", ["Parmigiano Reggiano", "Parmesan"], "grated"),
    ])
]


def main():
    db = SessionLocal()
    try:
        product_count = db.query(server.main_module.Product).filter(
            server.main_module.Product.supermarket == "REWE"
        ).count()
        embedding_count = db.query(ProductSemanticEmbedding).count()
        print("BITEWISE 20-RECIPE / REAL REWE CATALOG BENCHMARK")
        print(f"REWE products in local DB: {product_count}")
        print(f"Local semantic vectors: {embedding_count}")
        if product_count == 0:
            raise SystemExit("No REWE catalog rows found. Refresh/import the local catalog first.")
        if product_count < 1000:
            raise SystemExit(f"REWE catalog is incomplete for a representative benchmark: {product_count} products (expected at least 1,000).")

        adapter = server.main_module.CatalogAdapter(db)
        # Keep the complete local snapshot in memory for diagnostics only.
        # This lets us inspect titles even when SQL alias matching is what
        # failed (especially German umlaut/transliteration edge cases).
        catalog_products = db.query(Product).filter(
            Product.supermarket == "REWE"
        ).all()
        totals = Counter()
        per_recipe = []
        semantic_review_count = 0
        invalid_unit_count = 0
        for recipe in RECIPES:
            requirements = consolidate([recipe], {recipe["id"]: 2})
            basket = build_basket(requirements, adapter, "best-value", pantry={})
            counts = Counter(row["match_status"] for row in basket)
            resolved = counts["matched"] + counts["substituted"] + counts["covered"]
            per_recipe.append((recipe["name"], resolved, len(basket)))
            totals.update(counts)
            print(f"\n{recipe['name']}: {resolved}/{len(basket)} resolved ({resolved / max(1, len(basket)):.0%})")
            for row in basket:
                product = row.get("product") or {}
                title = product.get("name_original") or product.get("name_normalized") or "—"
                match_type = product.get("ingredient_match_type") or "—"
                suggestions = row.get("semantic_suggestions") or []
                semantic_review_count += len(suggestions)
                if not (row.get("unit_validation") or {}).get("valid", True):
                    invalid_unit_count += 1
                if row["match_status"] == "unmatched":
                    ingredient = row.get("ingredient") or ""
                    profile = recipe.get("ingredient_intelligence", {}).get(ingredient, {})
                    search_terms = ingredient_candidate_search_terms(ingredient, profile)
                    adapter_hits = adapter.search(ingredient, intelligence=profile) or []
                    print(
                        f"  MATCH DIAGNOSTIC {ingredient}: reason={row.get('match_reason')}, "
                        f"unit={row.get('unit')} quantity={row.get('needed_quantity')}, "
                        f"validation={row.get('unit_validation')}, adapter_hits={len(adapter_hits)}"
                    )
                    for hit in adapter_hits[:5]:
                        print(
                            f"    ADAPTER HIT {hit.get('name_original')} "
                            f"(type={hit.get('ingredient_match_type')}, price={hit.get('price')}, "
                            f"pack={hit.get('package_size')} {hit.get('package_unit')})"
                        )
                    ranked_candidates = []
                    for candidate in catalog_products:
                        candidate_title = normalize_text(" ".join(str(value or "") for value in (
                            candidate.name_original, candidate.name_normalized, candidate.translated_name
                        )))
                        matched_terms = [term for term in search_terms if term and term in candidate_title]
                        if matched_terms:
                            ranked_candidates.append((
                                max(len(term) for term in matched_terms),
                                candidate,
                                matched_terms,
                            ))
                    ranked_candidates.sort(key=lambda item: (-item[0], item[1].id or 0))
                    if ranked_candidates:
                        print(f"  CATALOG CANDIDATES FOR {ingredient}:")
                        for _, candidate, matched_terms in ranked_candidates[:8]:
                            candidate_title = normalize_text(" ".join(str(value or "") for value in (
                                candidate.name_original, candidate.name_normalized, candidate.translated_name
                            )))
                            candidate_match = ingredient_product_match_type(
                                ingredient,
                                " ".join(str(value or "") for value in (
                                    candidate.name_original, candidate.name_normalized, candidate.translated_name
                                )),
                                profile,
                                candidate.category or "",
                            )
                            converted, conversion_note = _convert_ingredient_quantity(
                                row.get("needed_quantity", row.get("quantity", 0)),
                                row.get("unit"), candidate.package_unit, ingredient,
                            )
                            print(
                                f"    {candidate.name_original} "
                                f"(category={candidate.category}, price={candidate.price}, "
                                f"pack={candidate.package_size} {candidate.package_unit}, "
                                f"match_type={candidate_match}, "
                                f"form_ok={_form_compatible(str(profile.get('form') or ''), candidate_title, ingredient)}, "
                                f"category_ok={_category_compatible(ingredient, candidate.category or '', candidate_title, str(profile.get('form') or ''))}, "
                                f"converted_needed={converted}, conversion_note={conversion_note}, "
                                f"aliases={matched_terms[:3]}, terms={ingredient_search_terms(ingredient, profile)[:8]})"
                            )
                    else:
                        print(f"  NO CATALOG TITLE CANDIDATES FOR {ingredient}; terms={search_terms[:10]}")
                        # Distinguish missing REWE assortment from a narrow alias list.
                        broad_tokens = {
                            "burger buns": ("brioche", "burger", "hamburger", "broetchen", "brotchen", "toastbrot", "toast"),
                            "rolled oats": ("hafer", "oat", "porridge", "muesli", "musli"),
                            "curry powder": ("curry",),
                        }.get(normalize_text(ingredient), ())
                        if broad_tokens:
                            broad_rows = []
                            for candidate in catalog_products:
                                candidate_title = normalize_text(" ".join(str(value or "") for value in (
                                    candidate.name_original, candidate.name_normalized, candidate.translated_name
                                )))
                                if any(token in candidate_title for token in broad_tokens):
                                    broad_rows.append(candidate)
                            print(f"  BROAD CATALOG DIAGNOSTICS FOR {ingredient}: {len(broad_rows)} rows")
                            for candidate in broad_rows[:20]:
                                print(f"    {candidate.name_original} (category={candidate.category}, price={candidate.price}, pack={candidate.package_size} {candidate.package_unit})")
                suggestion_text = ""
                if suggestions:
                    suggestion_text = " | REVIEW: " + "; ".join(
                        f"{s.get('name_original')} [{s.get('semantic_similarity', 0):.2f}]"
                        for s in suggestions[:3]
                    )
                category = product.get("category") or "—"
                price = product.get("price")
                price_text = f"€{float(price):.2f}" if price is not None else "no price"
                unit_note = ""
                validation = row.get("unit_validation") or {}
                if not validation.get("valid", True):
                    unit_note = f" | INVALID UNIT: {validation.get('reason')}"
                print(
                    f"  {'OK' if row['match_status'] in {'matched', 'substituted', 'covered'} else 'MISS'} "
                    f"{row['ingredient']} -> {title} "
                    f"(status={row['match_status']}, type={match_type}, category={category}, price={price_text})"
                    f"{unit_note}{suggestion_text}"
                )

        total = sum(totals.values())
        resolved = totals["matched"] + totals["substituted"] + totals["covered"]
        print("\n=== AGGREGATE ===")
        print(f"Recipes: {len(RECIPES)}")
        print(f"Ingredient rows: {total}")
        print(f"Exact/user-confirmed matches: {totals['matched']}")
        print(f"Curated substitutions: {totals['substituted']}")
        print(f"Pantry-covered: {totals['covered']}")
        print(f"Unmatched: {totals['unmatched']}")
        print(f"Ingredients with invalid recipe units: {invalid_unit_count}")
        assert invalid_unit_count == 0, (
            f"Recipe benchmark found {invalid_unit_count} invalid ingredient units; "
            "check ingredient-family inference before selecting REWE products."
        )
        print(f"Review-only semantic product suggestions: {semantic_review_count} (NOT counted as resolved)")
        print(f"Resolved total: {resolved}/{total} ({resolved / max(1, total):.1%})")
        assert total > 0 and resolved / total >= 0.90, (
            f"REWE recipe benchmark resolution fell below 90%: {resolved}/{total}"
        )
        print("\n=== PER-RECIPE SUMMARY ===")
        for name, found, count in per_recipe:
            print(f"{found:>2}/{count:<2}  {found / max(1, count):>6.1%}  {name}")
        print("\nNOTE: This benchmark reports the actual selected REWE product title for manual relevance review.")
        print("A resolved count is not proof of semantic correctness; inspect every printed product title.")
    finally:
        db.close()


if __name__ == "__main__":
    main()