"""Full-row offline QA of every product in the committed REWE snapshot.

Run from backend/: python qa_catalog_full_audit.py
Imports the committed CSV into a disposable SQLite DB. No network, REWE scraper,
image scraper, product-detail scraper, Gemini call, or user DB is touched.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-full-catalog-audit-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "catalog-audit.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["BITEWISE_IMPORT_CATALOG_SNAPSHOT"] = "true"

from app.database import Product, SessionLocal
from app.catalog.intelligence import classify_product
from app.ingredient_aliases import (
    _ALIAS_GROUPS,
    canonical_ingredient_terms,
    ingredient_product_match_type,
)


MULTIPACK = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", re.I)
NON_CULINARY_MARKERS = (
    "waschmittel", "spülmittel", "spuelmittel", "reiniger", "wc-reiniger",
    "toilettenpapier", "shampoo", "zahnpasta", "windeln", "katzenstreu",
    "hundefutter", "katzenfutter", "vogelfutter", "waschpulver",
)
COMPONENTS_NEVER_COMPLETE_MEALS = (
    "pizzateig", "pizza teig", "pizzagewürz", "pizzagewuerz",
    "pizza gewürz", "pizza gewuerz", "pizzasauce", "pizza sauce",
    "pizza soße", "pizza sosse", "pizzakäse", "pizzakaese",
    "ramen nudeln", "ramen noodles", "ramen noodle",
    "lasagneplatten", "lasagne platten", "lasagne blätter", "lasagneblaetter",
    "bowl topping", "topping bowl",
)
UNIT_FACTORS = {"g": 1.0, "ml": 1.0, "kg": 1000.0, "l": 1000.0, "unit": 1.0, "stk": 1.0, "stück": 1.0, "pcs": 1.0}


def _row_name(row):
    return str(row.name_original or row.name_normalized or "").strip()


def _multipack_expected(name):
    match = MULTIPACK.search(name or "")
    if not match:
        return None
    count = int(match.group(1))
    amount = float(match.group(2).replace(",", "."))
    unit = match.group(3).lower()
    if unit in {"kg", "l"}:
        amount *= 1000
    return count * amount, "g" if unit in {"g", "kg"} else "ml"


def main():
    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.supermarket == "REWE").order_by(Product.id.asc()).all()
        total = len(products)
        assert total >= 10000, f"Expected the complete ~12k snapshot, got only {total} products"

        counters = Counter()
        categories = Counter()
        units = Counter()
        types = Counter()
        roles = Counter()
        availability = Counter()
        duplicate_names = defaultdict(list)
        duplicate_external_ids = defaultdict(list)
        issues = defaultdict(list)
        canonical_hits = 0
        no_canonical_by_category = Counter()
        no_canonical_examples = defaultdict(list)
        ingredient_label_duplicates = 0
        low_confidence_profiles = []
        row_profiles = []
        source_details_by_id = {}

        for row in products:
            name = _row_name(row)
            lower = name.lower()
            categories[str(row.category or "uncategorized")] += 1
            units[str(row.package_unit or "missing").lower()] += 1
            availability[str(row.availability or "unknown").lower()] += 1
            duplicate_names[(row.name_normalized or name).strip().lower()].append(row.id)
            duplicate_external_ids[str(row.external_id or "").strip()].append(row.id)

            if not name:
                issues["empty_name"].append(row.id)
            if row.package_size is None or float(row.package_size or 0) <= 0:
                issues["invalid_package_size"].append((row.id, name, row.package_size, row.package_unit))
            unit = str(row.package_unit or "").strip().lower()
            if unit not in UNIT_FACTORS:
                issues["unrecognized_package_unit"].append((row.id, name, row.package_size, unit))
            if row.price is None or float(row.price or 0) <= 0:
                issues["missing_or_nonpositive_price"].append((row.id, name, row.price))
            if str(row.currency or "").upper() != "EUR":
                issues["non_eur_currency"].append((row.id, name, row.currency))

            # price_per_unit in this catalog is normalized to €/g, €/ml or €/item.
            if row.price is not None and row.price_per_unit is not None and row.package_size:
                factor = UNIT_FACTORS.get(unit)
                if factor:
                    # Checkout price can include German bottle deposits; unit
                    # prices intentionally exclude Pfand.
                    deposit_match = re.search(
                        r"zzgl\.?\s*(\d+[,.]\d{2})\s*€\s*Pfand",
                        _row_name(row), re.I,
                    )
                    deposit = float(deposit_match.group(1).replace(",", ".")) if deposit_match else 0.0
                    item_price = max(0.0, float(row.price) - deposit)
                    expected = item_price / (float(row.package_size) * factor)
                    actual = float(row.price_per_unit)
                    if expected > 0 and abs(actual - expected) / expected > 0.15:
                        issues["price_per_unit_mismatch"].append(
                            (row.id, name, round(float(row.price), 3), row.package_size, unit,
                             round(actual, 6), round(expected, 6))
                        )

            expected_pack = _multipack_expected(name)
            if expected_pack:
                expected_size, expected_unit = expected_pack
                if unit == expected_unit and row.package_size is not None:
                    actual_size = float(row.package_size)
                    if abs(actual_size - expected_size) > max(1.0, expected_size * 0.02):
                        issues["multipack_size_mismatch"].append(
                            (row.id, name, actual_size, unit, expected_size, expected_unit)
                        )

            profile = classify_product({
                "name_original": row.name_original,
                "name_normalized": row.name_normalized,
                "translated_name": row.translated_name,
                "brand": row.brand,
                "category": row.category,
            })
            types[profile.product_type] += 1
            roles[profile.culinary_role] += 1
            counters[f"confidence:{profile.confidence:.2f}"] += 1
            # Measure ingredient vocabulary only on products that can enter
            # recipe matching. Drinks, snacks, full meals and prepared soups,
            # salads and desserts are edible but not raw recipe ingredients.
            culinary_candidate = (
                profile.product_type in {"ingredient", "prepared_component"}
                and profile.culinary_role not in {"soup", "salad", "dessert", "complete_meal", "potato_side", "seasoning_mix", "topping", "filled_pasta"}
            )
            canonical_terms = canonical_ingredient_terms(name) if culinary_candidate else []
            if culinary_candidate:
                if canonical_terms:
                    canonical_hits += 1
                else:
                    category = str(row.category or "uncategorized")
                    no_canonical_by_category[category] += 1
                    no_canonical_examples[category].append({
                        "id": row.id,
                        "external_id": row.external_id,
                        "title": name,
                        "package_size": row.package_size,
                        "package_unit": row.package_unit,
                    })
            if str(row.ingredient or "").strip().lower() == str(row.name_normalized or "").strip().lower():
                ingredient_label_duplicates += 1

            row_profile = {
                "id": row.id,
                "external_id": row.external_id,
                "title": name,
                "category": row.category,
                "product_type": profile.product_type,
                "culinary_role": profile.culinary_role,
                "is_complete_meal": profile.is_complete_meal,
                "confidence": profile.confidence,
                "evidence": list(profile.evidence),
                "canonical_ingredient_terms": canonical_terms,
                "package_size": row.package_size,
                "package_unit": row.package_unit,
                "price": row.price,
                "price_per_unit": row.price_per_unit,
                "availability": row.availability,
            }
            row_profiles.append(row_profile)
            source_details_by_id[row.id] = {
                "product_url": row.product_url,
                "image_url": row.image_url,
                "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
                "last_price": row.last_price,
            }
            if profile.confidence < 0.75:
                low_confidence_profiles.append(row_profile)

            if profile.is_complete_meal and any(marker in lower for marker in COMPONENTS_NEVER_COMPLETE_MEALS):
                issues["component_misclassified_as_complete_meal"].append(
                    (row.id, name, row.category, profile.evidence)
                )
            if any(marker in lower for marker in NON_CULINARY_MARKERS):
                issues["non_culinary_catalog_candidates"].append((row.id, name, row.category, profile.product_type))

        for key, ids in duplicate_names.items():
            if key and len(ids) > 1:
                issues["duplicate_normalized_names"].append((key, ids[:8], len(ids)))
        for key, ids in duplicate_external_ids.items():
            if key and len(ids) > 1:
                issues["duplicate_external_ids"].append((key, ids[:8], len(ids)))

        print(f"FULL REWE CATALOG AUDIT: {total} / ~12,000 rows analyzed")
        print(f"Categories ({len(categories)}): {dict(categories)}")
        print(f"Package units: {dict(units)}")
        print(f"Availability values: {dict(availability)}")
        print(f"Product types: {dict(types)}")
        print(f"Culinary roles: {dict(roles)}")
        semantic_candidates = canonical_hits + sum(no_canonical_by_category.values())
        semantic_coverage = canonical_hits / max(semantic_candidates, 1)
        print(
            f"Semantic vocabulary coverage: {canonical_hits}/{semantic_candidates} "
            f"eligible ingredient/component products ({semantic_coverage:.1%})"
        )
        assert semantic_coverage >= 0.66, (
            f"Semantic vocabulary coverage regressed below 66%: {semantic_coverage:.1%}"
        )
        # Alias ontology must be one-to-one: ambiguous German terms can silently
        # map a product to multiple unrelated recipe ingredients.
        alias_owners = defaultdict(set)
        canonical_names = []
        for group in _ALIAS_GROUPS:
            canonical = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9äöüß]+", " ", group[0].lower())).strip()
            canonical_names.append(canonical)
            for term in group:
                normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9äöüß]+", " ", term.lower())).strip()
                alias_owners[normalized].add(canonical)
        duplicate_canonicals = sorted(
            name for name, count in Counter(canonical_names).items() if count > 1
        )
        ambiguous_aliases = {
            term: sorted(owners) for term, owners in alias_owners.items() if len(owners) > 1
        }
        assert not duplicate_canonicals, f"Duplicate canonical ingredient groups: {duplicate_canonicals}"
        assert not ambiguous_aliases, f"Ambiguous ingredient aliases: {ambiguous_aliases}"
        assert ingredient_product_match_type(
            "chicken", "Hühneraufstrich", "fleisch-wurst-fisch"
        ) is None, "Chicken spread must not be matched as chicken meat"
        assert ingredient_product_match_type(
            "celery", "REWE Knollensellerie", "obst-gemuese"
        ) == "substitute", "Celeriac must be labeled as a substitute for celery stalk"
        assert ingredient_product_match_type(
            "red cabbage", "REWE Apfelrotkohl 450g", "fertiggerichte-konserven"
        ) == "substitute", "Prepared apple red cabbage must not be an exact raw-vegetable match"
        assert ingredient_product_match_type(
            "red cabbage", "Kühne Rotkohl 335g", "fertiggerichte-konserven"
        ) == "substitute", "Canned plain red cabbage must be a prepared shortcut"
        assert ingredient_product_match_type(
            "red cabbage", "REWE Rotkohl frisch", "obst-gemuese"
        ) == "exact", "Fresh red cabbage should remain an exact match"
        assert ingredient_product_match_type("milk", "REWE Bio Haferdrink 1l") == "substitute"
        assert ingredient_product_match_type(
            "milk", "Alnatura Bio Hafer Drink ohne Zucker 1l", "kaese-eier-molkerei"
        ) == "substitute", "Plant milk with spaced product naming must remain a milk substitute"
        assert classify_product({
            "name_original": "7 Guen Ayran Mango 250ml",
            "category": "kaese-eier-molkerei",
        }).product_type == "beverage"
        assert ingredient_product_match_type(
            "peach", "Activia Kefir mild Pfirsich & Maracuja 345g", "kaese-eier-molkerei"
        ) is None, "Kefir fruit flavor must not match fresh peach"
        assert ingredient_product_match_type(
            "mango", "Alpro Haferdrink Mango 1l", "kaese-eier-molkerei"
        ) is None, "Fruit flavor in a plant drink must not match fresh fruit"
        assert classify_product({
            "name_original": "Alnatura Bio Haferdrink 1l",
            "category": "kaese-eier-molkerei",
        }).product_type == "beverage"
        assert ingredient_product_match_type(
            "chicken breast", "Bernard Matthews Hähnchenbrust gebraten 125g", "fleisch-wurst-fisch"
        ) == "substitute", "Cooked chicken must be labeled as a shortcut, not raw chicken"
        assert ingredient_product_match_type(
            "duck", "Berschneider Entenbrust gepökelt geräuchert 80g", "fleisch-wurst-fisch"
        ) == "substitute", "Smoked cured duck must be a shortcut substitute"
        assert classify_product({
            "name_original": "Activia Kefir mild Pfirsich & Maracuja 345g",
            "category": "kaese-eier-molkerei",
        }).product_type == "beverage"
        assert ingredient_product_match_type("cream", "Rama Cremefine 15% 250ml") == "substitute"
        assert ingredient_product_match_type("butter", "Rama Margarine 400g") == "substitute"
        assert ingredient_product_match_type(
            "peanut butter", "Ben & Jerry's Eis Peanut Butter Cup 465ml", "tiefkuehlkost"
        ) is None, "Ice-cream flavor claims must not satisfy peanut butter ingredients"
        assert ingredient_product_match_type(
            "mango", "7 Guen Ayran Mango 250ml", "kaese-eier-molkerei"
        ) is None, "Fruit-flavored dairy drinks must not satisfy fresh fruit ingredients"
        # High-value catalog examples must remain discoverable as canonical terms.
        semantic_examples = {
            "tempeh": "Better Nature Tempeh geräuchert vegan 220g",
            "plant based mince": "Beyond Hack Original vegan 250g",
            "duck": "REWE Beste Wahl Barbarie Entenbrustfilet 400g",
            "cod": "REWE Beste Wahl Atlantisches Kabeljaufilet 475g",
            "red cabbage": "REWE Apfelrotkohl 450g",
            "kale": "REWE Beste Wahl Grünkohl 1kg",
            "oyster mushroom": "Bio Kräuterseitlinge 125g",
            "rice noodles": "Bamboo Garden Reisnudeln Guai-Thiau 250g",
            "arugula": "Florette Rucola 80g",
            "blueberry": "Kulturheidelbeeren 125g",
            "onion": "Bio Demeter Speisezwiebeln 500g im Netz",
            "pumpkin": "Bio Spaghettikürbis ca. 1kg",
            "pasta": "Barilla Al Bronzo Fusilloni Nr. 380 500g",
            "sugar snap peas": "REWE Beste Wahl Kaiserschoten 200g",
            "garden cress": "REWE Bio Gartenkresse 1 Stück",
            "skyr": "Milu Skyr Natur 450g",
        }
        for expected, title in semantic_examples.items():
            terms = canonical_ingredient_terms(title)
            assert expected in terms, (
                f"Expected semantic term {expected!r} from catalog title {title!r}; got {terms}"
            )
        print(f"Rows where Product.ingredient duplicates name_normalized: {ingredient_label_duplicates}/{total}")
        print(f"Titles without known canonical ingredient terms by category: {dict(no_canonical_by_category)}")
        for category in (
            "fleisch-wurst-fisch", "obst-gemuese", "kaese-eier-molkerei",
            "kochen-backen", "oele-sossen-gewuerze", "tiefkuehlkost",
        ):
            examples = no_canonical_examples.get(category, [])
            if examples:
                print(f"UNMAPPED CULINARY TITLES [{category}]: {examples}")
        print("\nISSUE COUNTS:")
        for key, values in sorted(issues.items()):
            print(f"  {key}: {len(values)}")
            for sample in values[:12]:
                print(f"    - {sample}")

        # These are data-integrity failures, not subjective classification gaps.
        blocking = (
            "empty_name", "invalid_package_size", "unrecognized_package_unit",
            "missing_or_nonpositive_price", "non_eur_currency",
            "price_per_unit_mismatch", "multipack_size_mismatch",
            "component_misclassified_as_complete_meal",
        )
        failures = {key: len(issues[key]) for key in blocking if issues[key]}
        assert not failures, f"Full-catalog data integrity/classification failures: {failures}"
        print(f"Low-confidence product profiles: {len(low_confidence_profiles)}")
        assert len(low_confidence_profiles) <= 100, (
            f"Low-confidence product profiles regressed above 100: {len(low_confidence_profiles)}"
        )

        profile_by_id = {profile["id"]: profile for profile in row_profiles}
        duplicate_name_details = [
            {
                "normalized_name": key,
                "products": [
                    {**profile_by_id[row_id], **source_details_by_id.get(row_id, {})}
                    for row_id in ids if row_id in profile_by_id
                ],
            }
            for key, ids, count in issues["duplicate_normalized_names"]
        ]

        report = {
            "catalog": "REWE",
            "rows_analyzed": total,
            "categories": dict(categories),
            "package_units": dict(units),
            "availability": dict(availability),
            "product_types": dict(types),
            "culinary_roles": dict(roles),
            "canonical_food_title_coverage": canonical_hits,
            "semantic_candidate_products": semantic_candidates,
            "semantic_coverage_rate": semantic_coverage,
            "ingredient_label_duplicates": ingredient_label_duplicates,
            "issues": {key: values for key, values in issues.items()},
            "duplicate_name_details": duplicate_name_details,
            "duplicate_normalized_names": [
                {"normalized_name": key, "row_ids": ids, "count": count}
                for key, ids, count in issues["duplicate_normalized_names"]
            ],
            "duplicate_external_ids": [
                {"external_id": key, "row_ids": ids, "count": count}
                for key, ids, count in issues["duplicate_external_ids"]
            ],
            "unmapped_food_titles_by_category": dict(no_canonical_examples),
            "low_confidence_profiles": low_confidence_profiles,
            "all_product_profiles": row_profiles,
        }
        report_path = Path(os.environ.get("BITEWISE_CATALOG_AUDIT_REPORT", "catalog-audit-report.json"))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"Full audit review report written: {report_path} ({report_path.stat().st_size} bytes)")

        print("\nFull catalog audit PASS: every imported product row was inspected.")
        print("Duplicate names and non-culinary products are diagnostic review groups, not automatic deletions.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
