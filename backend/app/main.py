import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import or_

from .ai.gemini import GeminiService
from .database import (
    AppSetting,
    CatalogRun,
    PantryItem,
    Plan,
    PlannedMeal,
    Product,
    ProductOverride,
    SessionLocal,
    ShoppingState,
    UserEvent,
)
from .recommendations.engine import score_meal
from .recipes.seed import MEALS
from .rewe.scraper import ReweCatalogScraper
from .rewe.seed_products import PRODUCTS
from .shopping.optimizer import STRATEGIES, build_basket, consolidate

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = FastAPI(title="Bitewise API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def rows(model):
    db = SessionLocal()
    try:
        return db.query(model).all()
    finally:
        db.close()


def setting(db, key, default):
    item = db.get(AppSetting, key)
    return item.value if item else default


def normalize_ingredient(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().strip())


def product_dict(product):
    if product is None:
        return None
    return {
        "id": product.id,
        "supermarket": product.supermarket,
        "external_id": product.external_id,
        "ingredient": product.ingredient,
        "name_original": product.name_original,
        "name_normalized": product.name_normalized,
        "translated_name": product.translated_name,
        "brand": product.brand,
        "category": product.category,
        "package_size": product.package_size,
        "package_unit": product.package_unit,
        "price": product.price,
        "price_per_unit": product.price_per_unit,
        "currency": product.currency,
        "product_url": product.product_url,
        "availability": product.availability,
        "postcode_context": product.postcode_context,
        "last_checked_at": product.last_checked_at,
    }


def meal_by_id(meal_id: str):
    return next((m for m in MEALS if m["id"] == meal_id), None)


def pantry_snapshot(db):
    return {
        row.ingredient.lower(): {"quantity": row.quantity, "unit": row.unit, "confidence": row.confidence}
        for row in db.query(PantryItem).all()
    }


class CatalogAdapter:
    """Uses the persisted REWE catalog first, then seed fixtures as a safe offline fallback."""

    def __init__(self, db):
        self.db = db

    def search(self, ingredient):
        needle = normalize_ingredient(ingredient)
        direct = self.db.query(Product).filter(Product.ingredient == needle).limit(40).all()
        if not direct:
            direct = (
                self.db.query(Product)
                .filter(
                    or_(
                        Product.name_normalized.ilike(f"%{needle}%"),
                        Product.name_original.ilike(f"%{needle}%"),
                        Product.translated_name.ilike(f"%{needle}%"),
                        Product.brand.ilike(f"%{needle}%"),
                    )
                )
                .limit(40)
                .all()
            )
        if direct:
            return [product_dict(row) for row in direct]

        exact = [p for p in PRODUCTS if p["ingredient"] == needle]
        fallback = exact or [
            p for p in PRODUCTS if needle in p["ingredient"].lower() or p["ingredient"].lower() in needle
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


class EventIn(BaseModel):
    meal_id: str
    action: str | None = None
    event: str | None = None


class PantryIn(BaseModel):
    ingredient: str
    quantity: float = 1
    unit: str = "unit"
    confidence: str = "user_confirmed"
    source: str = "manual"
    notes: str | None = None
    expiry_date: str | None = None


class PantryPatch(BaseModel):
    ingredient: str | None = None
    quantity: float | None = None
    unit: str | None = None
    notes: str | None = None
    expiry_date: str | None = None


class BasketIn(BaseModel):
    meal_ids: list[str]
    servings: dict[str, int] = Field(default_factory=dict)
    owned: list[str] = Field(default_factory=list)
    mode: str = "best-value"


class SettingsIn(BaseModel):
    postcode: str | None = None
    shopping_strategy: str | None = None


class BrainDumpIn(BaseModel):
    prompt: str


class PurchaseIn(BaseModel):
    product_id: int
    packs: int = 1
    ingredient: str | None = None


class ProductOverrideIn(BaseModel):
    ingredient: str
    product_id: int


class ShoppingStateIn(BaseModel):
    ingredient: str
    state: str
    product_id: int | None = None
    purchased_quantity: float | None = None
    purchased_unit: str | None = None


class PlanCreateIn(BaseModel):
    weeks: int = 1
    servings: int = 2
    strategy: str = "best-value"
    budget: float | None = None
    start_date: str | None = None
    meal_ids: list[str] = Field(default_factory=list)


class PlannedMealPatch(BaseModel):
    day_index: int | None = None
    meal_type: str | None = None
    servings: int | None = None


class PlannedMealStatusIn(BaseModel):
    status: str


class SwapMealIn(BaseModel):
    meal_id: str | None = None


@app.get("/api/health")
def health():
    return {"ok": True, "version": "2.0"}


@app.get("/api/meals")
def get_meals(mode: str = "random"):
    events = rows(UserEvent)
    pantry = rows(PantryItem)
    meals = sorted(MEALS, key=lambda m: score_meal(m, events, pantry, mode), reverse=True)
    disliked = {e.meal_id for e in events if e.action == "dislike"}
    seen = {e.meal_id for e in events if e.action in ("like", "skip", "cooked", "eaten")}
    eligible = [m for m in meals if m["id"] not in disliked]
    fresh = [m for m in eligible if m["id"] not in seen]
    return {"meals": (fresh + eligible)[:12], "mode": mode}


@app.post("/api/events")
def add_event(payload: EventIn):
    action = payload.action or payload.event
    if action not in {"like", "skip", "dislike", "cooked", "eaten", "undo-dislike"}:
        raise HTTPException(422, "Unsupported event")
    if not meal_by_id(payload.meal_id):
        raise HTTPException(404, "Meal not found")
    db = SessionLocal()
    try:
        if action == "undo-dislike":
            db.query(UserEvent).filter(UserEvent.meal_id == payload.meal_id, UserEvent.action == "dislike").delete()
        else:
            db.add(UserEvent(meal_id=payload.meal_id, action=action))
        db.commit()
    finally:
        db.close()
    return {"ok": True, "action": action}


@app.get("/api/events/dislikes")
def dislikes():
    db = SessionLocal()
    try:
        ids = [x.meal_id for x in db.query(UserEvent).filter(UserEvent.action == "dislike").all()]
        return {"meals": [m for m in MEALS if m["id"] in ids]}
    finally:
        db.close()


def consume_meal_from_pantry(db, meal, servings=2):
    factor = servings / 2
    consumed = []
    for ingredient, amount, unit in meal["ingredients"]:
        item = db.query(PantryItem).filter(PantryItem.ingredient.ilike(ingredient)).first()
        if item and item.unit == unit:
            used = min(item.quantity, amount * factor)
            item.quantity = max(0, item.quantity - amount * factor)
            consumed.append({"ingredient": ingredient, "quantity": round(used, 2), "unit": unit})
    return consumed


@app.post("/api/meals/{meal_id}/eaten")
def eaten(meal_id: str, servings: int = 2):
    meal = meal_by_id(meal_id)
    if not meal:
        raise HTTPException(404, "Meal not found")
    db = SessionLocal()
    try:
        consumed = consume_meal_from_pantry(db, meal, servings)
        db.add(UserEvent(meal_id=meal_id, action="eaten"))
        db.commit()
        return {"ok": True, "consumed": consumed, "message": "Estimated pantry quantities updated."}
    finally:
        db.close()


@app.get("/api/pantry")
def get_pantry():
    db = SessionLocal()
    try:
        data = []
        for p in db.query(PantryItem).order_by(PantryItem.ingredient).all():
            status = "out" if p.quantity <= 0 else ("running-low" if p.quantity <= 1 else "available")
            data.append(
                {
                    "id": p.id,
                    "ingredient": p.ingredient,
                    "quantity": p.quantity,
                    "unit": p.unit,
                    "confidence": p.confidence,
                    "source": p.source,
                    "notes": p.notes,
                    "expiry_date": p.expiry_date,
                    "status": status,
                }
            )
        return data
    finally:
        db.close()


@app.post("/api/pantry")
def add_pantry(payload: PantryIn):
    if payload.quantity < 0:
        raise HTTPException(422, "Quantity cannot be negative")
    ingredient = normalize_ingredient(payload.ingredient)
    if not ingredient:
        raise HTTPException(422, "Ingredient is required")
    db = SessionLocal()
    try:
        old = db.query(PantryItem).filter(PantryItem.ingredient.ilike(ingredient)).first()
        values = payload.model_dump()
        values["ingredient"] = ingredient
        if old:
            for key, value in values.items():
                setattr(old, key, value)
        else:
            db.add(PantryItem(**values))
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.patch("/api/pantry/{item_id}")
def update_pantry(item_id: int, payload: PantryPatch):
    db = SessionLocal()
    try:
        row = db.get(PantryItem, item_id)
        if not row:
            raise HTTPException(404, "Pantry item not found")
        values = payload.model_dump(exclude_unset=True)
        if "quantity" in values and values["quantity"] is not None and values["quantity"] < 0:
            raise HTTPException(422, "Quantity cannot be negative")
        if "ingredient" in values and values["ingredient"]:
            values["ingredient"] = normalize_ingredient(values["ingredient"])
        for key, value in values.items():
            setattr(row, key, value)
        row.confidence = "manually_corrected"
        row.source = "manual"
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.delete("/api/pantry/{item_id}")
def del_pantry(item_id: int):
    db = SessionLocal()
    try:
        row = db.get(PantryItem, item_id)
        if row:
            db.delete(row)
            db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/settings")
def get_settings():
    db = SessionLocal()
    try:
        return {
            "postcode": setting(db, "postcode", "13353"),
            "shopping_strategy": setting(db, "shopping_strategy", "best-value"),
        }
    finally:
        db.close()


@app.patch("/api/settings")
def update_settings(payload: SettingsIn):
    db = SessionLocal()
    try:
        values = payload.model_dump(exclude_none=True)
        if "postcode" in values and not re.fullmatch(r"\d{5}", values["postcode"]):
            raise HTTPException(422, "Postcode must be a 5-digit German postcode")
        if "shopping_strategy" in values and values["shopping_strategy"] not in STRATEGIES:
            raise HTTPException(422, "Unknown strategy")
        for key, value in values.items():
            item = db.get(AppSetting, key)
            if item:
                item.value = value
            else:
                db.add(AppSetting(key=key, value=value))
        db.commit()
        return {"ok": True, **values}
    finally:
        db.close()


@app.get("/api/products")
def products(q: str = "", ingredient: str | None = None):
    db = SessionLocal()
    try:
        query = db.query(Product)
        if ingredient:
            query = query.filter(Product.ingredient == normalize_ingredient(ingredient))
        if q:
            needle = q.lower().strip()
            query = query.filter(
                or_(
                    Product.name_normalized.ilike(f"%{needle}%"),
                    Product.name_original.ilike(f"%{needle}%"),
                    Product.translated_name.ilike(f"%{needle}%"),
                    Product.brand.ilike(f"%{needle}%"),
                    Product.ingredient.ilike(f"%{needle}%"),
                )
            )
        return {"products": [product_dict(p) for p in query.limit(80).all()]}
    finally:
        db.close()


@app.get("/api/products/search")
def search_products(q: str = "", ingredient: str | None = None):
    return products(q=q, ingredient=ingredient)


@app.get("/api/products/validate")
def validate_product(product_id: int):
    db = SessionLocal()
    try:
        product = db.get(Product, product_id)
        if not product:
            raise HTTPException(404, "Product not found")
        return {"valid": True, "product": product_dict(product)}
    finally:
        db.close()


@app.get("/api/products/{product_id}/alternatives")
def alternatives(product_id: int, needed_qty: float | None = None, unit: str | None = None):
    db = SessionLocal()
    try:
        current = db.get(Product, product_id)
        if not current:
            raise HTTPException(404, "Product not found")
        query = db.query(Product).filter(Product.id != product_id)
        query = query.filter(
            or_(
                Product.ingredient == current.ingredient,
                Product.category == current.category,
            )
        )
        products_rows = query.limit(40).all()
        if unit:
            products_rows = [p for p in products_rows if p.package_unit == unit]

        def estimate(row):
            quantity = needed_qty or row.package_size
            packs = max(1, int((quantity + row.package_size - 1) // row.package_size)) if row.package_size else 1
            total = packs * (row.price or 9999)
            waste = max(0, packs * row.package_size - quantity)
            return total + waste / max(quantity, 1)

        products_rows.sort(key=estimate)
        return {"current": product_dict(current), "alternatives": [product_dict(x) for x in products_rows[:20]]}
    finally:
        db.close()


@app.post("/api/products/replace")
def replace_product(payload: ProductOverrideIn):
    ingredient = normalize_ingredient(payload.ingredient)
    db = SessionLocal()
    try:
        product = db.get(Product, payload.product_id)
        if not product:
            raise HTTPException(404, "Product not found")
        row = db.query(ProductOverride).filter_by(ingredient=ingredient).first()
        if row:
            row.product_id = product.id
        else:
            db.add(ProductOverride(ingredient=ingredient, product_id=product.id))
        db.commit()
        return {"ok": True, "product": product_dict(product), "ingredient": ingredient}
    finally:
        db.close()


@app.delete("/api/products/replace/{ingredient}")
def restore_product(ingredient: str):
    db = SessionLocal()
    try:
        row = db.query(ProductOverride).filter_by(ingredient=normalize_ingredient(ingredient)).first()
        if row:
            db.delete(row)
            db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/rewe/status")
def rewe_status():
    db = SessionLocal()
    try:
        last = db.query(CatalogRun).order_by(CatalogRun.id.desc()).first()
        count = db.query(Product).filter(Product.supermarket == "REWE").count()
        return {
            "provider": "REWE",
            "postcode": setting(db, "postcode", "13353"),
            "products": count,
            "status": last.status if last else "not-refreshed",
            "last_updated": last.finished_at if last else None,
            "errors": last.errors if last else 0,
            "categories_processed": last.categories_processed if last else 0,
            "categories_successful": last.categories_successful if last else 0,
            "categories_failed": last.categories_failed if last else 0,
            "live_data": False,
            "data_freshness": "catalog_snapshot",
        }
    finally:
        db.close()


@app.post("/api/rewe/refresh")
def rewe_refresh():
    db = SessionLocal()
    postcode = setting(db, "postcode", "13353")
    run = CatalogRun(status="running")
    db.add(run)
    db.commit()
    try:
        def upsert(data, current_postcode):
            existing = (
                db.query(Product)
                .filter_by(supermarket="REWE", external_id=data["external_id"])
                .first()
            )
            now = datetime.utcnow()
            if existing:
                if existing.price != data.get("price"):
                    existing.last_price = existing.price
                for key, value in data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                existing.postcode_context = current_postcode
                existing.last_seen_at = now
                existing.last_checked_at = now
                db.flush()
                return False
            db.add(Product(supermarket="REWE", postcode_context=current_postcode, **data))
            db.flush()
            return True

        report = ReweCatalogScraper().run(upsert, postcode)
        run.status = report["status"]
        run.products_seen = report["products_found"]
        run.errors = len(report["errors"])
        run.categories_processed = report["categories_processed"]
        run.categories_successful = report["categories_successful"]
        run.categories_failed = report["categories_failed"]
        run.finished_at = datetime.utcnow()
        db.commit()
        return {
            "ok": report["status"] != "failed",
            **report,
            "message": "Manual public-category refresh. Prices are a catalog snapshot, not real-time checkout data.",
        }
    except Exception as exc:
        run.status = "failed"
        run.errors = max(1, run.errors or 0)
        run.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(502, f"REWE refresh failed: {str(exc)[:180]}")
    finally:
        db.close()


@app.get("/api/shopping/state")
def get_shopping_state():
    db = SessionLocal()
    try:
        return {
            "items": [
                {
                    "ingredient": row.ingredient,
                    "state": row.state,
                    "product_id": row.product_id,
                    "purchased_quantity": row.purchased_quantity,
                    "purchased_unit": row.purchased_unit,
                }
                for row in db.query(ShoppingState).all()
            ]
        }
    finally:
        db.close()


@app.put("/api/shopping/state")
def set_shopping_state(payload: ShoppingStateIn):
    if payload.state not in {"needed", "partial", "purchased", "owned"}:
        raise HTTPException(422, "Unsupported shopping state")
    ingredient = normalize_ingredient(payload.ingredient)
    db = SessionLocal()
    try:
        row = db.query(ShoppingState).filter_by(ingredient=ingredient).first()
        if not row:
            row = ShoppingState(ingredient=ingredient)
            db.add(row)
        row.state = payload.state
        row.product_id = payload.product_id
        row.purchased_quantity = payload.purchased_quantity if payload.state == "partial" else None
        row.purchased_unit = payload.purchased_unit if payload.state == "partial" else None
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.post("/api/shopping/purchase")
def purchase(payload: PurchaseIn):
    if payload.packs < 1:
        raise HTTPException(422, "Packs must be at least 1")
    db = SessionLocal()
    try:
        product = db.get(Product, payload.product_id)
        if not product:
            raise HTTPException(404, "Product not found")
        ingredient = normalize_ingredient(payload.ingredient or product.ingredient)
        amount = product.package_size * payload.packs
        item = db.query(PantryItem).filter(PantryItem.ingredient.ilike(ingredient)).first()
        if item and item.unit != product.package_unit:
            raise HTTPException(409, f"Pantry already tracks {ingredient} in {item.unit}; cannot safely merge {product.package_unit}.")
        if item:
            item.quantity += amount
            item.confidence = "estimated"
            item.source = "purchase"
        else:
            db.add(
                PantryItem(
                    ingredient=ingredient,
                    quantity=amount,
                    unit=product.package_unit,
                    confidence="estimated",
                    source="purchase",
                )
            )
        state = db.query(ShoppingState).filter_by(ingredient=ingredient).first()
        if not state:
            state = ShoppingState(ingredient=ingredient)
            db.add(state)
        state.state = "purchased"
        state.product_id = product.id
        state.purchased_quantity = amount
        state.purchased_unit = product.package_unit
        db.commit()
        return {"ok": True, "ingredient": ingredient, "added": amount, "unit": product.package_unit}
    finally:
        db.close()


@app.post("/api/brain-dump")
def brain_dump(payload: BrainDumpIn):
    prompt = payload.prompt.strip()
    text = prompt.lower()
    mode = "random"
    constraints = {
        "prompt": prompt,
        "mode": mode,
        "max_time": None,
        "max_cost": None,
        "spicy": None,
        "effort": None,
        "occasion": None,
        "use_pantry": False,
    }

    cuisine_map = {
        "asian": ("asian", "asiático", "asiatica", "asiática"),
        "mexican": ("mexican", "mexicano", "mexicana"),
        "italian": ("italian", "italiano", "italiana"),
        "mediterranean": ("mediterranean", "mediterráneo", "mediterranea", "mediterránea"),
        "german": ("german", "alemán", "alemana"),
        "latin-american": ("latin", "latino", "latina"),
    }
    if any(x in text for x in ("cheap", "budget", "barato", "barata", "económico", "economico")):
        mode = "cheap"
        constraints["max_cost"] = 5
    if any(x in text for x in ("quick", "easy", "don't want to cook", "dont want to cook", "rápido", "rapido", "fácil", "facil", "no quiero cocinar")):
        mode = "quick"
        constraints["max_time"] = 30
        constraints["effort"] = "low"
    if any(x in text for x in ("protein", "proteína", "proteina")):
        mode = "high-protein"
    if any(x in text for x in ("healthy", "saludable")):
        mode = "healthy"
    if any(x in text for x in ("fancy", "guests", "invitados", "elegante")):
        constraints["occasion"] = "fancy"
    if any(x in text for x in ("not spicy", "no spicy", "sin picante", "no picante")):
        constraints["spicy"] = False
    if any(x in text for x in ("at home", "pantry", "en casa", "despensa")):
        constraints["use_pantry"] = True
    for cuisine, aliases in cuisine_map.items():
        if any(alias in text for alias in aliases):
            mode = cuisine
            break
    constraints["mode"] = mode
    return {"mode": mode, "constraints": constraints}


@app.post("/api/shopping")
def shopping(payload: BasketIn):
    if payload.mode not in STRATEGIES:
        raise HTTPException(422, "Unknown shopping strategy")
    selected = [m for m in MEALS if m["id"] in payload.meal_ids]
    if not selected:
        raise HTTPException(422, "Select at least one valid meal")
    servings_map = {meal["id"]: max(1, payload.servings.get(meal["id"], 2)) for meal in selected}
    requirements = consolidate(selected, servings_map)
    db = SessionLocal()
    try:
        overrides = {
            row.ingredient: row.product_id
            for row in db.query(ProductOverride).all()
        }
        basket = build_basket(
            requirements,
            CatalogAdapter(db),
            payload.mode,
            payload.owned,
            overrides=overrides,
            pantry=pantry_snapshot(db),
        )
        total = round(sum(x["total"] for x in basket), 2)
        total_servings = sum(servings_map.values())
        waste = round(sum(x["waste"] for x in basket), 2)
        return {
            "requirements": requirements,
            "basket": basket,
            "items": basket,
            "total": total,
            "meals": len(selected),
            "servings": total_servings,
            "cost_per_serving": round(total / total_servings, 2) if total_servings else 0,
            "waste": waste,
            "strategy": payload.mode,
            "pantry_savings_items": sum(1 for x in basket if x.get("pantry_used", 0) > 0),
        }
    finally:
        db.close()


def serialize_planned_meal(row):
    meal = meal_by_id(row.meal_id)
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "meal_id": row.meal_id,
        "day_index": row.day_index,
        "meal_type": row.meal_type,
        "servings": row.servings,
        "status": row.status,
        "meal": meal,
    }


def serialize_plan(db, plan):
    meals = (
        db.query(PlannedMeal)
        .filter(PlannedMeal.plan_id == plan.id)
        .order_by(PlannedMeal.day_index, PlannedMeal.meal_type)
        .all()
    )
    return {
        "id": plan.id,
        "weeks": plan.weeks,
        "servings": plan.servings,
        "strategy": plan.strategy,
        "budget": plan.budget,
        "start_date": plan.start_date,
        "status": plan.status,
        "meals": [serialize_planned_meal(row) for row in meals],
    }


def ranked_plan_candidates(db, requested_ids=None):
    events = db.query(UserEvent).all()
    pantry = db.query(PantryItem).all()
    pool = [m for m in MEALS if not requested_ids or m["id"] in requested_ids]
    disliked = {e.meal_id for e in events if e.action == "dislike"}
    pool = [m for m in pool if m["id"] not in disliked]
    return sorted(pool, key=lambda m: score_meal(m, events, pantry, "random"), reverse=True)


@app.post("/api/plans")
def create_plan(payload: PlanCreateIn):
    if payload.weeks not in (1, 2, 4):
        raise HTTPException(422, "Weeks must be 1, 2, or 4")
    if payload.strategy not in STRATEGIES:
        raise HTTPException(422, "Unknown shopping strategy")
    if payload.budget is not None and payload.budget < 0:
        raise HTTPException(422, "Budget cannot be negative")
    if payload.servings < 1 or payload.servings > 12:
        raise HTTPException(422, "Servings must be between 1 and 12")
    try:
        start = date.fromisoformat(payload.start_date) if payload.start_date else date.today()
    except ValueError:
        raise HTTPException(422, "start_date must be YYYY-MM-DD")

    db = SessionLocal()
    try:
        candidates = ranked_plan_candidates(db, payload.meal_ids or None)
        if not candidates:
            raise HTTPException(422, "No eligible meals available")
        plan = Plan(
            weeks=payload.weeks,
            servings=payload.servings,
            strategy=payload.strategy,
            budget=payload.budget,
            start_date=start.isoformat(),
        )
        db.add(plan)
        db.flush()
        total_days = payload.weeks * 7
        for day_index in range(total_days):
            # rotate through the candidate pool to enforce variety before repeating
            meal = candidates[day_index % len(candidates)]
            db.add(
                PlannedMeal(
                    plan_id=plan.id,
                    meal_id=meal["id"],
                    day_index=day_index,
                    meal_type="dinner",
                    servings=payload.servings,
                )
            )
        db.commit()
        return serialize_plan(db, plan)
    finally:
        db.close()


@app.get("/api/plans")
def list_plans():
    db = SessionLocal()
    try:
        plans = db.query(Plan).order_by(Plan.id.desc()).all()
        return {"plans": [serialize_plan(db, plan) for plan in plans]}
    finally:
        db.close()


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: int):
    db = SessionLocal()
    try:
        plan = db.get(Plan, plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")
        return serialize_plan(db, plan)
    finally:
        db.close()


@app.patch("/api/plans/{plan_id}/meals/{planned_meal_id}")
def move_planned_meal(plan_id: int, planned_meal_id: int, payload: PlannedMealPatch):
    db = SessionLocal()
    try:
        row = db.get(PlannedMeal, planned_meal_id)
        plan = db.get(Plan, plan_id)
        if not plan or not row or row.plan_id != plan_id:
            raise HTTPException(404, "Planned meal not found")
        values = payload.model_dump(exclude_none=True)
        if "day_index" in values and not (0 <= values["day_index"] < plan.weeks * 7):
            raise HTTPException(422, "day_index outside plan range")
        if "servings" in values and values["servings"] < 1:
            raise HTTPException(422, "servings must be positive")
        for key, value in values.items():
            setattr(row, key, value)
        db.commit()
        return serialize_planned_meal(row)
    finally:
        db.close()


@app.delete("/api/plans/{plan_id}/meals/{planned_meal_id}")
def remove_planned_meal(plan_id: int, planned_meal_id: int):
    db = SessionLocal()
    try:
        row = db.get(PlannedMeal, planned_meal_id)
        if not row or row.plan_id != plan_id:
            raise HTTPException(404, "Planned meal not found")
        db.delete(row)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.post("/api/plans/{plan_id}/meals/{planned_meal_id}/swap")
def swap_planned_meal(plan_id: int, planned_meal_id: int, payload: SwapMealIn):
    db = SessionLocal()
    try:
        row = db.get(PlannedMeal, planned_meal_id)
        if not row or row.plan_id != plan_id:
            raise HTTPException(404, "Planned meal not found")
        plan_meal_ids = {
            x.meal_id for x in db.query(PlannedMeal).filter(PlannedMeal.plan_id == plan_id).all()
        }
        if payload.meal_id:
            replacement = meal_by_id(payload.meal_id)
            if not replacement:
                raise HTTPException(404, "Replacement meal not found")
        else:
            candidates = ranked_plan_candidates(db)
            replacement = next((m for m in candidates if m["id"] != row.meal_id and m["id"] not in plan_meal_ids), None)
            replacement = replacement or next((m for m in candidates if m["id"] != row.meal_id), None)
        if not replacement:
            raise HTTPException(409, "No replacement available")
        row.meal_id = replacement["id"]
        row.status = "planned"
        db.commit()
        return serialize_planned_meal(row)
    finally:
        db.close()


@app.post("/api/plans/{plan_id}/regenerate")
def regenerate_plan(plan_id: int):
    db = SessionLocal()
    try:
        plan = db.get(Plan, plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")
        candidates = ranked_plan_candidates(db)
        rows_to_update = (
            db.query(PlannedMeal)
            .filter(PlannedMeal.plan_id == plan_id, PlannedMeal.status == "planned")
            .order_by(PlannedMeal.day_index)
            .all()
        )
        for index, row in enumerate(rows_to_update):
            row.meal_id = candidates[index % len(candidates)]["id"]
        db.commit()
        return serialize_plan(db, plan)
    finally:
        db.close()


@app.post("/api/plans/{plan_id}/meals/{planned_meal_id}/status")
def planned_meal_status(plan_id: int, planned_meal_id: int, payload: PlannedMealStatusIn):
    if payload.status not in {"planned", "cooked", "eaten", "skipped"}:
        raise HTTPException(422, "Unsupported meal status")
    db = SessionLocal()
    try:
        row = db.get(PlannedMeal, planned_meal_id)
        if not row or row.plan_id != plan_id:
            raise HTTPException(404, "Planned meal not found")
        previous_status = row.status
        row.status = payload.status
        should_consume = payload.status in ("cooked", "eaten") and previous_status not in ("cooked", "eaten")
        consumed = []
        if should_consume:
            meal = meal_by_id(row.meal_id)
            consumed = consume_meal_from_pantry(db, meal, row.servings)
            db.add(UserEvent(meal_id=row.meal_id, action=payload.status))
        db.commit()
        return {**serialize_planned_meal(row), "consumed": consumed}
    finally:
        db.close()


@app.get("/api/today")
def today(plan_id: int | None = Query(default=None)):
    db = SessionLocal()
    try:
        if plan_id:
            plan = db.get(Plan, plan_id)
        else:
            plan = db.query(Plan).filter(Plan.status == "active").order_by(Plan.id.desc()).first()
        if not plan:
            return {"plan": None, "date": date.today().isoformat(), "meals": []}
        start = date.fromisoformat(plan.start_date)
        day_index = (date.today() - start).days
        if day_index < 0 or day_index >= plan.weeks * 7:
            return {"plan": serialize_plan(db, plan), "date": date.today().isoformat(), "day_index": day_index, "meals": []}
        day_meals = (
            db.query(PlannedMeal)
            .filter(PlannedMeal.plan_id == plan.id, PlannedMeal.day_index == day_index)
            .all()
        )
        pantry_names = {p.ingredient.lower() for p in db.query(PantryItem).filter(PantryItem.quantity > 0).all()}
        serialized = []
        for row in day_meals:
            item = serialize_planned_meal(row)
            ingredients = item["meal"]["ingredients"] if item["meal"] else []
            covered = sum(1 for name, _, _ in ingredients if name.lower() in pantry_names)
            item["pantry_coverage_pct"] = round(covered / len(ingredients) * 100) if ingredients else 0
            serialized.append(item)
        return {
            "plan": {"id": plan.id, "strategy": plan.strategy, "budget": plan.budget},
            "date": date.today().isoformat(),
            "day_index": day_index,
            "meals": serialized,
        }
    finally:
        db.close()


@app.post("/api/ai/meals")
def ai_meals(payload: BrainDumpIn):
    return {"meals": GeminiService().generate_meals(payload.prompt) or []}
