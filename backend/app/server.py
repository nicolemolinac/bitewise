from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_

# Load backend/.env before database.py is imported so DATABASE_URL and auth settings
# are available both locally and in the deployed cloud entrypoint.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from .cloud_sync import auth_enabled, authenticate_request, router as cloud_router
from . import main as main_module
from .ai.gemini_efficient import GeminiService as EfficientGeminiService
from .ai.image_resolver import resolve_meal_image
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


@app.get("/api/meal-image")
def meal_image(name: str, description: str = "", tags: str = ""):
    """Resolve a Google Images result and stream the bytes from Bitewise itself.

    The frontend points <img> at this endpoint. That avoids publisher hotlink/referrer issues and
    means Google CDN thumbnails can be used even when the browser would otherwise refuse them.
    """
    meal = {
        "name": name,
        "description": description,
        "tags": [x.strip() for x in tags.split(",") if x.strip()],
        "ingredients": [],
    }
    url = resolve_meal_image(meal)
    if not url:
        raise HTTPException(404, "No matching meal image found")
    try:
        upstream = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/144 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://www.google.com/",
            },
            timeout=10,
            allow_redirects=True,
        )
        upstream.raise_for_status()
        ctype = (upstream.headers.get("content-type") or "").lower()
        if not ctype.startswith("image/"):
            raise ValueError("Upstream response was not an image")
    except Exception as exc:
        raise HTTPException(502, f"Image fetch failed: {str(exc)[:160]}")
    return Response(
        content=upstream.content,
        media_type=ctype.split(";")[0],
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
