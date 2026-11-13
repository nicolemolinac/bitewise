"""QA for supermarket-first convenience discovery; run from backend/."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Product, ProductSemanticEmbedding, SessionLocal
from app.catalog_intelligence import search_catalog_opportunities
from app import semantic_catalog


def product(external_id, name, category, ingredient="meal", price=2.0, package_size=400, package_unit="g"):
    return Product(
        supermarket="REWE",
        external_id=external_id,
        ingredient=ingredient,
        name_original=name,
        name_normalized=name.casefold(),
        translated_name=None,
        brand=None,
        category=category,
        package_size=package_size,
        package_unit=package_unit,
        price=price,
        price_per_unit=price / (package_size / 1000 if package_unit == "g" else package_size),
        availability="unknown",
        postcode_context="13353",
    )


def run():
    # Smoke-test the currently imported REWE snapshot as well as isolated fixtures.
    real_session = SessionLocal()
    try:
        real_count = real_session.query(Product).filter(Product.supermarket == "REWE").count()
        if real_count:
            print(f"REAL REWE SNAPSHOT: {real_count} products")
            for term in ("bistro baguette", "flammkuchen", "pizza baguette", "pizza teig"):
                rows = real_session.query(Product).filter(
                    Product.supermarket == "REWE",
                    Product.name_original.ilike(f"%{term}%")
                ).all()
                print("REAL CATALOG TERM", term, [
                    (row.name_original, row.category, row.price) for row in rows[:12]
                ])
            for real_query in ("pizza", "pizza baguette", "chili con carne", "french fries"):
                real_result = search_catalog_opportunities(real_session, real_query, limit=12)
                assert real_result["catalog_count"] == real_count, (
                    real_query, real_result["catalog_count"], real_count
                )
                names = [row["name_original"] for row in real_result["products"]]
                print(f"REAL REWE SEARCH [{real_query}] ({real_result.get('retrieval')}): {[(row['name_original'], row['category'], row['convenience_type'], row['relevance_score']) for row in real_result['products']]}")
                if real_query == "pizza":
                    assert any("Bistro Baguette" in name for name in names), names
                    assert any("Flammkuchen" in name for name in names), names
                    assert not any("Taco Kit" in name or "FruchtBar" in name or "Hipp" in name or "Mogli" in name for name in names), names
                if real_query == "chili con carne":
                    assert any("Chili con Carne" in name for name in names), names
                if real_query == "french fries":
                    assert not any("Sauce" in name or "Haribo" in name for name in names), names
    finally:
        real_session.close()

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Product.__table__, ProductSemanticEmbedding.__table__])
    session = sessionmaker(bind=engine)()
    try:
        session.add_all([
            product("pizza-1", "ja! Pizza Baguette Salami 250g", "Tiefkühlkost"),
            product("pizza-2", "REWE Beste Wahl Steinofen Pizza Margherita", "Tiefkühlkost"),
            product("pizza-3", "Frischer Pizzateig mit Tomatensauce", "Fertiggerichte-Konserven"),
            product("pizza-4", "Knack & Back Pizza-Kit 600g", "Fertiggerichte-Konserven"),
            product("pizza-5", "Tante Fanny Frischer Flammkuchenteig 260g", "Fertiggerichte-Konserven"),
            product("pizza-snack-1", "FruchtBar Bio-Pizza-Flieger Tomate Käse 30g", "Baby & Kind", package_size=30),
            product("pizza-snack-2", "Mogli Bio Demeter Pizza Stangen 75g", "Süßes-Salziges", package_size=75),
            product("chili-1", "Chili con Carne 400g", "Konserven", price=2.49),
            product("chili-2", "Mexikanischer Chili Eintopf mit Rind", "Fertiggerichte", price=2.99),
            product("chili-3", "Kidney Bohnen rot", "Konserven", ingredient="kidney beans"),
            product("chili-4", "Maggi Fix Chili Con Carne 33g", "Fertiggerichte-Konserven", ingredient="seasoning mix"),
            product("chili-noise-1", "Maggi Magic Asia Saucy Noodles Sweet Chili 75g", "Nudeln", ingredient="noodles"),
            product("chili-noise-2", "REWE Marinierte Oliven mit Chili 150g", "Antipasti", ingredient="olives"),
            product("fries-1", "REWE Beste Wahl Pommes Frites 750g", "Tiefkühlkost", ingredient="frozen fries"),
            product("fries-noise-1", "Haribo Fruchtgummi Pommes Sauer", "Süßwaren", ingredient="candy"),
            product("fries-noise-2", "REWE Pommes Gewürzsalz 70g", "Gewürze", ingredient="seasoning"),
            product("fries-noise-3", "Bautzner Pommes Sauce 429ml", "Saucen", ingredient="sauce"),
            product("semantic-1", "REWE Kartoffelgratin Fertiggericht 400g", "Fertiggerichte"),
            product("pizza-noise-1", "Fuego Taco Kit 320g", "Kits", ingredient="taco kit"),
            product("noise-1", "Hundefutter Chili Geschmack", "Tierbedarf", ingredient="pet food"),
        ])
        # Ensure discovery is backed by the whole catalog rather than a tiny curated list.
        session.add_all([
            product(f"bulk-noise-{index}", f"Unrelated household product {index}", "Haushalt", ingredient="household")
            for index in range(1000)
        ])
        session.commit()

        pizza = search_catalog_opportunities(session, "pizza", limit=10)
        pizza_names = [row["name_original"] for row in pizza["products"]]
        assert pizza["catalog_count"] == 1020
        assert any("Pizza Baguette" in name for name in pizza_names), pizza_names
        assert any("Steinofen Pizza" in name for name in pizza_names), pizza_names
        assert any("Pizzateig" in name for name in pizza_names), pizza_names
        pizza_kit = next(row for row in pizza["products"] if row["name_original"] == "Knack & Back Pizza-Kit 600g")
        pizza_dough = next(row for row in pizza["products"] if row["name_original"] == "Frischer Pizzateig mit Tomatensauce")
        assert pizza_kit["convenience_type"] == "meal_kit", pizza_kit
        assert pizza_dough["convenience_type"] == "ready_to_cook", pizza_dough
        flammkuchen = next(row for row in pizza["products"] if "Flammkuchen" in row["name_original"])
        assert flammkuchen["convenience_type"] == "ready_to_cook", flammkuchen
        steinofen = next(row for row in pizza["products"] if "Steinofen Pizza" in row["name_original"])
        assert steinofen["convenience_type"] == "ready_meal", steinofen
        assert not any("Hundefutter" in name or "Taco Kit" in name or "FruchtBar" in name or "Mogli" in name for name in pizza_names), pizza_names
        assert all(row["convenience_type"] in {"ready_meal", "meal_kit", "ready_to_cook", "prepared_component", "catalog_product"} for row in pizza["products"])
        pizza_types = {row["convenience_type"] for row in pizza["products"]}
        assert {"meal_kit", "ready_to_cook"}.issubset(pizza_types), pizza_types

        chili = search_catalog_opportunities(session, "chili con carne", limit=10)
        chili_names = [row["name_original"] for row in chili["products"]]
        natural_language_chili = search_catalog_opportunities(session, "quick air-fryer chili con carne tonight", limit=10)
        natural_chili_names = [row["name_original"] for row in natural_language_chili["products"]]
        assert any(name == "Chili con Carne 400g" for name in natural_chili_names), natural_chili_names
        natural_language_pizza = search_catalog_opportunities(session, "easy pizza for two", limit=10)
        assert any("Pizza Baguette" in row["name_original"] for row in natural_language_pizza["products"])
        assert any(name == "Chili con Carne 400g" for name in chili_names), chili_names
        assert any("Chili Eintopf" in name for name in chili_names), chili_names
        assert not any("Sweet Chili" in name or "Oliven" in name for name in chili_names), chili_names
        fix_kit = next(row for row in chili["products"] if row["name_original"] == "Maggi Fix Chili Con Carne 33g")
        assert fix_kit["convenience_type"] == "prepared_component", fix_kit
        assert next(row for row in chili["products"] if row["name_original"] == "Chili con Carne 400g")["convenience_type"] == "ready_meal"
        canned_beans = search_catalog_opportunities(session, "bohnen", limit=10)
        bean_row = next(row for row in canned_beans["products"] if row["name_original"] == "Kidney Bohnen rot")
        assert bean_row["convenience_type"] == "prepared_component", bean_row
        fries = search_catalog_opportunities(session, "french fries", limit=10)
        fries_names = [row["name_original"] for row in fries["products"]]
        assert any("Pommes Frites" in name for name in fries_names), fries_names
        assert not any("Haribo" in name or "Gewürzsalz" in name or "Pommes Sauce" in name for name in fries_names), fries_names
        # A semantic-only candidate can recover a concept with no shared retail words.
        semantic_product = session.query(Product).filter_by(external_id="semantic-1").one()
        original_semantic_search = semantic_catalog.semantic_catalog_candidates
        semantic_catalog.semantic_catalog_candidates = lambda db, query, limit=120: [
            {"id": semantic_product.id, "semantic_similarity": 0.77}
        ]
        try:
            semantic_result = search_catalog_opportunities(session, "creamy potato gratin dinner", limit=5)
            semantic_match = next(row for row in semantic_result["products"] if row["id"] == semantic_product.id)
            assert semantic_result["retrieval"] == "hybrid_local"
            assert semantic_match["semantic_similarity"] == 0.77
            assert semantic_match["convenience_type"] == "ready_meal"
        finally:
            semantic_catalog.semantic_catalog_candidates = original_semantic_search

        empty = search_catalog_opportunities(session, "x", limit=10)
        assert empty["products"] == []
        print("PASS: supermarket discovery surfaces Pizza Baguette, pizza kits and canned chili from the full catalog without LLM calls")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    run()
