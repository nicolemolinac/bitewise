from pathlib import Path
import hmac
import json
import os
import uuid
from datetime import date, datetime
from decimal import Decimal

from dotenv import load_dotenv
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import or_

# Load backend/.env before database.py is imported so DATABASE_URL and auth settings
# are available both locally and in the deployed cloud entrypoint.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from .cloud_sync import auth_enabled, authenticate_request, router as cloud_router
from .migration_api import router as migration_router
from . import main as main_module
from .ai.gemini_efficient import GeminiService as EfficientGeminiService
from .database import RecipeHistory, SessionLocal
from .ingredient_aliases import ingredient_product_match_type, ingredient_search_terms, ingredient_substitution_name
from .rewe_refresh import router as rewe_refresh_router

# main.py's /api/ai/meals handler resolves GeminiService from its module globals at request time.
# Swap in the token-efficient implementation without duplicating the route.
main_module.GeminiService = EfficientGeminiService


def _multilingual_catalog_search(self, ingredient):
    """Match English recipe ingredients against the German REWE catalog without LLM calls."""
    aliases = ingredient_search_terms(ingredient)
    if not aliases:
        return []

    Product = main_module.Product
    clauses = []
    for term in aliases:
        pattern = f"%{term}%"
        clauses.extend(
            [
                Product.ingredient.ilike(pattern),
                Product.name_normalized.ilike(pattern),
                Product.name_original.ilike(pattern),
                Product.translated_name.ilike(pattern),
            ]
        )

    rows = self.db.query(Product).filter(or_(*clauses)).limit(240).all()
    if rows:
        # Search columns improve recall, but the actual product title must independently
        # confirm compatibility. Catalog ingredient labels can be broad or misclassified.
        match_types = {
            row.id: ingredient_product_match_type(
                ingredient,
                " ".join(str(value or "") for value in (
                    row.name_original, row.name_normalized, row.translated_name
                )),
            )
            for row in rows
        }
        rows = [row for row in rows if match_types.get(row.id)]
    if rows:
        alias_set = {x.lower() for x in aliases}

        def score(row):
            fields = [
                str(row.ingredient or "").lower(),
                str(row.translated_name or "").lower(),
                str(row.name_normalized or "").lower(),
                str(row.name_original or "").lower(),
            ]
            best = 0
            for alias in alias_set:
                for field in fields:
                    if field == alias:
                        best = max(best, 100)
                    elif field.startswith(alias + " ") or field.endswith(" " + alias):
                        best = max(best, 80)
                    elif alias in field:
                        best = max(best, 60 if len(alias) >= 4 else 40)
            if match_types.get(row.id) == "exact":
                best += 1000
            elif match_types.get(row.id) == "substitute":
                best -= 100
            if row.price is not None:
                best += 10
            if str(row.availability or "").lower() == "available":
                best += 5
            return best

        rows.sort(key=score, reverse=True)
        return [
            {
                **main_module.product_dict(row),
                "ingredient_match_type": match_types.get(row.id),
                "ingredient_substitute": ingredient_substitution_name(
                    ingredient,
                    " ".join(str(value or "") for value in (
                        row.name_original, row.name_normalized, row.translated_name
                    )),
                ) if match_types.get(row.id) == "substitute" else None,
            }
            for row in rows[:40]
        ]

    # Never substitute seed/demo products for a real REWE catalog match.
    # An empty result is more honest than displaying invented availability or prices.
    return []


main_module.CatalogAdapter.search = _multilingual_catalog_search
app = main_module.app


def _assign_expanded_recipe_identity(recipe: dict, concept_id: str) -> dict:
    """Make expanded recipe IDs unique even when Gemini reuses a generic ID."""
    if concept_id:
        recipe["source_concept_id"] = concept_id
        recipe["id"] = f"{recipe.get('id') or 'recipe'}-{concept_id}"
    return recipe


def _adapt_recipe_to_catalog(recipe: dict, basket: list[dict]) -> list[dict]:
    """Apply explicit catalog substitutions to ingredients and cooking steps."""
    import re

    adaptations = []
    replacements = []
    for row in basket:
        if row.get("match_status") != "substituted":
            continue
        product = row.get("product") or {}
        original = str(row.get("ingredient") or "").strip()
        replacement = str(product.get("ingredient_substitute") or product.get("ingredient") or product.get("name_normalized") or "").strip()
        if not original or not replacement:
            continue
        replacements.append((original, replacement))
        adaptations.append({
            "ingredient": original,
            "replacement": replacement,
            "product_name": product.get("name_original"),
            "reason": row.get("match_reason"),
        })

    if replacements:
        adapted_ingredients = []
        substitution_rows = {
            str(row.get("ingredient") or "").strip().lower(): row
            for row in basket if row.get("match_status") == "substituted"
        }
        for item in recipe.get("ingredients") or []:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                name, quantity, unit = item[0], item[1], item[2]
                row = substitution_rows.get(str(name).strip().lower())
                if row:
                    replacement = str((row.get("product") or {}).get("ingredient_substitute") or "")
                    pantry_used = float(row.get("pantry_used") or 0)
                    needed = float(row.get("needed_quantity") or 0)
                    if pantry_used > 0:
                        adapted_ingredients.append([name, pantry_used, unit])
                        if needed > 0:
                            adapted_ingredients.append([replacement, needed, unit])
                    else:
                        adapted_ingredients.append([replacement, quantity, unit])
                else:
                    adapted_ingredients.append([name, quantity, unit])
            else:
                adapted_ingredients.append(item)
        recipe["ingredients"] = adapted_ingredients

        for step in recipe.get("steps") or []:
            if not isinstance(step, dict):
                continue
            step_text = str(step.get("text") or "")
            for original, replacement in replacements:
                row = substitution_rows.get(original.lower(), {})
                pantry_used = float(row.get("pantry_used") or 0)
                step_replacement = original + " and " + replacement if pantry_used > 0 else replacement
                step_text = re.sub(r"(?<![\w])" + re.escape(original) + r"(?![\w])", step_replacement, step_text, flags=re.IGNORECASE)
            step["text"] = step_text

    recipe["adaptations"] = adaptations
    return adaptations

def _json_history_default(value):
    """Convert common Python values to stable JSON-safe history values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, set):
        return sorted(value, key=str)
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if hasattr(value, "dict") and callable(value.dict):
        return _json_safe(value.dict())
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json_safe(value):
    """Recursively remove non-JSON Python objects before persistence or API response.

    This is deliberately applied to the complete expanded recipe (including catalog
    product metadata) rather than relying on FastAPI or a single json.dumps call.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    raise TypeError(f"Unsupported value in recipe payload: {type(value).__name__}")


def _history_owner(request: Request) -> str:
    user = getattr(request.state, "bitewise_user", None) or {}
    return str(user.get("id") or user.get("email") or "local")[:160]


def _upsert_recipe_history(request: Request, record_key: str, record_type: str, status: str, meal: dict, prompt: str = ""):
    if record_type not in {"concept", "recipe"} or not isinstance(meal, dict):
        return
    key = str(record_key or meal.get("id") or "").strip()[:180]
    name = str(meal.get("name") or "").strip()[:180]
    if not key or not name:
        return
    owner = _history_owner(request)
    db = SessionLocal()
    try:
        row = db.query(RecipeHistory).filter_by(user_id=owner, record_key=key).first()
        if row is None:
            row = RecipeHistory(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"bitewise:{owner}:{key}")),
                user_id=owner,
                record_key=key,
                record_type=record_type,
                status=status,
                name=name,
                prompt=str(prompt or "")[:4000] or None,
                meal_json=json.dumps(_json_safe(meal), ensure_ascii=False, default=_json_history_default),
            )
            db.add(row)
        else:
            row.record_type = record_type
            row.status = status
            row.name = name
            row.prompt = str(prompt or row.prompt or "")[:4000] or None
            row.meal_json = json.dumps(_json_safe(meal), ensure_ascii=False, default=_json_history_default)
            row.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/api/recipe-history")
def get_recipe_history(request: Request, record_type: str | None = None, limit: int = 300):
    db = SessionLocal()
    try:
        query = db.query(RecipeHistory).filter_by(user_id=_history_owner(request))
        if record_type in {"concept", "recipe"}:
            query = query.filter_by(record_type=record_type)
        rows = query.order_by(RecipeHistory.created_at.desc()).limit(max(1, min(limit, 1000))).all()
        records = []
        for row in rows:
            try:
                meal = json.loads(row.meal_json)
            except Exception:
                meal = {}
            records.append({
                "record_key": row.record_key,
                "record_type": row.record_type,
                "status": row.status,
                "name": row.name,
                "prompt": row.prompt,
                "meal": meal,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            })
        return {"records": records, "count": len(records)}
    finally:
        db.close()


@app.post("/api/recipe-history")
async def save_recipe_history(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        raise HTTPException(422, "records must be a list")
    saved = 0
    for item in records[:100]:
        if not isinstance(item, dict):
            continue
        meal = item.get("meal")
        record_type = str(item.get("record_type") or "concept")
        status = str(item.get("status") or "discovered")
        if status not in {"discovered", "saved", "skipped", "disliked", "expanded", "removed", "cooked"}:
            status = "discovered"
        if isinstance(meal, dict) and meal.get("name"):
            _upsert_recipe_history(
                request,
                str(item.get("record_key") or meal.get("id") or ""),
                record_type,
                status,
                meal,
                str(item.get("prompt") or meal.get("discovery_prompt") or ""),
            )
            saved += 1
    return {"ok": True, "saved": saved}


@app.patch("/api/recipe-history/{record_key:path}")
async def update_recipe_history(record_key: str, request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    status = str(payload.get("status") or "") if isinstance(payload, dict) else ""
    allowed = {"discovered", "saved", "skipped", "disliked", "expanded", "removed", "cooked"}
    if status not in allowed:
        raise HTTPException(422, "Invalid recipe history status")
    db = SessionLocal()
    try:
        row = db.query(RecipeHistory).filter_by(
            user_id=_history_owner(request),
            record_key=record_key,
        ).first()
        if row is None:
            raise HTTPException(404, "Recipe history record not found")
        row.status = status
        row.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "record_key": row.record_key, "status": row.status}
    finally:
        db.close()


@app.post("/api/ai/recipe")
async def expand_ai_recipe(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    concept = payload.get("concept") if isinstance(payload, dict) else None
    context = payload.get("context", "") if isinstance(payload, dict) else ""
    appliances = payload.get("appliances", []) if isinstance(payload, dict) else []
    try:
        requested_servings = float(payload.get("servings", 2)) if isinstance(payload, dict) else 2.0
        people = int(payload.get("people", 1)) if isinstance(payload, dict) else 1
    except (TypeError, ValueError):
        raise HTTPException(422, "servings and people must be numeric")
    if not 0.1 <= requested_servings <= 12 or not 1 <= people <= 12:
        raise HTTPException(422, "servings must be 0.1–12 and people must be 1–12")
    if not isinstance(concept, dict) or not str(concept.get("name") or "").strip():
        raise HTTPException(422, "A meal concept with a name is required")
    concept_id = str(concept.get("id") or "").strip()
    # Idempotency guard: a rapid repeat tap or network retry must not spend another
    # Gemini call for a concept that already has a persisted recipe.
    if concept_id:
        existing_db = SessionLocal()
        try:
            existing_row = existing_db.query(RecipeHistory).filter_by(
                user_id=_history_owner(request),
                record_key=f"recipe:{concept_id}",
                record_type="recipe",
            ).first()
            if existing_row and existing_row.status in {"saved", "cooked"}:
                try:
                    existing_recipe = json.loads(existing_row.meal_json)
                except Exception:
                    existing_recipe = None
                if isinstance(existing_recipe, dict) and existing_recipe.get("id"):
                    return {"meal": existing_recipe, "reused": True}
        finally:
            existing_db.close()
    try:
        recipe = EfficientGeminiService().expand_concept(concept, str(context or ""), appliances)
        if concept_id:
            # Gemini may reuse a generic recipe ID across separate ideas. Give
            # each expansion a stable ID derived from its originating concept.
            _assign_expanded_recipe_identity(recipe, concept_id)
        # Generated quantities use a stable 2-serving baseline; scale locally for the requested people.
        recipe["base_servings"] = 2
        # Product matching and costing are deterministic backend work: no second Gemini call.
        db = SessionLocal()
        try:
            requirements = main_module.consolidate([recipe], {recipe["id"]: requested_servings})
            overrides = {row.ingredient: row.product_id for row in db.query(main_module.ProductOverride).all()}
            basket = main_module.build_basket(
                requirements,
                main_module.CatalogAdapter(db),
                "best-value",
                overrides=overrides,
                pantry=main_module.pantry_snapshot(db),
            )
            matched_rows = [row for row in basket if row.get("match_status") in {"matched", "substituted"}]
            exact_rows = [row for row in basket if row.get("match_status") == "matched"]
            substituted_rows = [row for row in basket if row.get("match_status") == "substituted"]
            covered_rows = [row for row in basket if row.get("match_status") == "covered"]
            checkout_total = round(sum(float(row.get("checkout_cost") or 0) for row in matched_rows), 2)
            consumed_total = round(sum(float(row.get("consumed_cost") or 0) for row in matched_rows), 2)
            unmatched = [
                {"ingredient": row.get("ingredient"), "quantity": row.get("needed_quantity"),
                 "unit": row.get("unit"), "reason": row.get("match_reason")}
                for row in basket if row.get("match_status") == "unmatched"
            ]
            recipe["product_matches"] = basket
            adaptations = _adapt_recipe_to_catalog(recipe, basket)
            recipe["costing"] = {
                "strategy": "best-value",
                "matched_ingredients": len(exact_rows),
                "substituted_ingredients": len(substituted_rows),
                "covered_ingredients": len(covered_rows),
                "unmatched_ingredients": len(unmatched),
                "total_ingredients": len(basket),
                "catalog_ready": db.query(main_module.Product).filter(main_module.Product.supermarket == "REWE").count() > 0,
                "checkout_total": checkout_total if matched_rows else None,
                "consumed_cost": consumed_total if matched_rows else None,
                "servings": requested_servings,
                "people": people,
                "cost_per_serving": round(consumed_total / requested_servings, 2) if matched_rows and requested_servings > 0 else None,
                "cost_scope": "matched_ingredients_only",
                "shopping_ready": len(unmatched) == 0,
                "catalog_coverage": round((len(matched_rows) + len(covered_rows)) / len(basket), 4) if basket else 1.0,
                "currency": "EUR",
            }
        finally:
            db.close()
        # Normalize every nested value (notably REWE last_checked_at datetimes) before
        # either database persistence or the FastAPI response encoder sees the payload.
        recipe = _json_safe(recipe)
        if concept_id:
            _upsert_recipe_history(request, concept_id, "concept", "expanded", _json_safe(concept), str(context or ""))
            _upsert_recipe_history(request, f"recipe:{concept_id}", "recipe", "saved", recipe, str(context or ""))
        return {"meal": recipe}
    except Exception as exc:
        raise HTTPException(502, f"Recipe expansion failed: {str(exc)[:300]}")


app.router.routes = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/api/rewe/refresh"
        and "POST" in (getattr(route, "methods", None) or set())
    )
]
app.include_router(rewe_refresh_router)
app.include_router(cloud_router)
app.include_router(migration_router)



@app.post("/api/rewe/cart/add")
async def add_rewe_products_to_cart(request: Request):
    """Add selected catalog products to the signed-in REWE cart; never checks out."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list) or not items:
        raise HTTPException(422, "At least one product is required")
    db = SessionLocal()
    try:
        products = []
        for item in items[:100]:
            if not isinstance(item, dict):
                continue
            try:
                product_id = int(item.get("product_id"))
                packs = max(1, min(99, int(item.get("packs") or 1)))
            except (TypeError, ValueError):
                continue
            product = db.get(main_module.Product, product_id)
            if product is None or str(product.supermarket or "").upper() != "REWE":
                continue
            products.append({
                "name": product.name_original,
                "product_url": product.product_url,
                "packs": packs,
            })
    finally:
        db.close()
    if not products:
        raise HTTPException(422, "No valid REWE catalog products were supplied")
    try:
        from .rewe.scraper import ReweCatalogScraper
        return ReweCatalogScraper().add_products_to_cart(products)
    except Exception as exc:
        raise HTTPException(502, f"REWE cart handoff failed: {str(exc)[:300]}")


def _trusted_service_request(request: Request) -> bool:
    expected = os.getenv("SERVICE_TOKEN", "").strip()
    supplied = request.headers.get("x-service-token", "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


@app.middleware("http")
async def private_bitewise(request: Request, call_next):
    path = request.url.path
    if _trusted_service_request(request):
        request.state.bitewise_user = {"id": "personal-ai-os", "email": "chief@bitewise.local"}
        return await call_next(request)
    if auth_enabled() and path.startswith("/api/") and path != "/api/health" and request.method != "OPTIONS":
        try:
            request.state.bitewise_user = authenticate_request(request)
        except Exception as exc:
            status = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "Unauthorized")
            return JSONResponse(status_code=status, content={"detail": detail})
    return await call_next(request)
