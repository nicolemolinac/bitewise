from pathlib import Path

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
from .ai.pexels_images import search_pexels_image
from .ingredient_aliases import ingredient_aliases
from .rewe_refresh import router as rewe_refresh_router

# main.py's /api/ai/meals handler resolves GeminiService from its module globals at request time.
# Swap in the token-efficient implementation without duplicating the route.
main_module.GeminiService = EfficientGeminiService


def _multilingual_catalog_search(self, ingredient):
    """Match English recipe ingredients against the German REWE catalog without LLM calls."""
    aliases = ingredient_aliases(ingredient)
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

    rows = self.db.query(Product).filter(or_(*clauses)).limit(120).all()
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
            if row.price is not None:
                best += 10
            if str(row.availability or "").lower() == "available":
                best += 5
            return best

        rows.sort(key=score, reverse=True)
        return [main_module.product_dict(row) for row in rows[:40]]

    needle = main_module.normalize_ingredient(ingredient)
    exact = [p for p in main_module.PRODUCTS if p["ingredient"] == needle]
    fallback = exact or [
        p for p in main_module.PRODUCTS
        if needle in p["ingredient"].lower() or p["ingredient"].lower() in needle
    ][:5]
    return [
        {
            "id": None,
            "supermarket": "REWE",
            "ingredient": p["ingredient"],
            "name_original": p.get("name", p["ingredient"]),
            "name_normalized": p.get("name", p["ingredient"]).lower(),
            "brand": p.get("brand"),
            "package_size": p.get("pack_qty", 1),
            "package_unit": p.get("unit", "unit"),
            "price": p.get("price"),
            "price_per_unit": p.get("unit_price"),
            "product_url": p.get("url"),
            "availability": "fixture",
        }
        for p in fallback
    ]


main_module.CatalogAdapter.search = _multilingual_catalog_search
app = main_module.app


@app.post("/api/ai/recipe")
async def expand_ai_recipe(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    concept = payload.get("concept") if isinstance(payload, dict) else None
    context = payload.get("context", "") if isinstance(payload, dict) else ""
    if not isinstance(concept, dict) or not str(concept.get("name") or "").strip():
        raise HTTPException(422, "A meal concept with a name is required")
    try:
        recipe = EfficientGeminiService().expand_concept(concept, str(context or ""))
        return {"meal": recipe}
    except Exception as exc:
        raise HTTPException(502, f"Recipe expansion failed: {str(exc)[:300]}")


@app.get("/api/meal-photo")
def meal_photo(name: str, meal_type: str = "", tags: str = ""):
    """Return one free Pexels photo for a meal concept.

    This endpoint is deliberately separate from Gemini so discovery stays one LLM call and
    image lookup remains free-first. If PEXELS_API_KEY is missing, return an empty result.
    """
    result = search_pexels_image(
        {
            "name": name,
            "meal_type": meal_type,
            "tags": [x.strip() for x in tags.split(",") if x.strip()],
        }
    )
    return result


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


@app.middleware("http")
async def private_bitewise(request: Request, call_next):
    path = request.url.path
    if auth_enabled() and path.startswith("/api/") and path != "/api/health" and request.method != "OPTIONS":
        try:
            request.state.bitewise_user = authenticate_request(request)
        except Exception as exc:
            status = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "Unauthorized")
            return JSONResponse(status_code=status, content={"detail": detail})
    return await call_next(request)
