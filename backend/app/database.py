import csv
import math
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
_configured_local_db = os.getenv("BITEWISE_LOCAL_DB_PATH", "").strip()
DB_PATH = Path(_configured_local_db or str(BACKEND_DIR / "data" / "grocery.db")).expanduser().resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_SQLITE = not DATABASE_URL
if IS_SQLITE:
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
else:
    # Supabase/managed Postgres connection string. pool_pre_ping recovers cleanly
    # after a free-tier database or network connection has been idle.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class UserEvent(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meal_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PantryItem(Base):
    __tablename__ = "pantry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingredient: Mapped[str] = mapped_column(String(100), unique=True)
    quantity: Mapped[float] = mapped_column(Float, default=1)
    unit: Mapped[str] = mapped_column(String(20), default="unit")
    confidence: Mapped[str] = mapped_column(String(30), default="user_confirmed")
    source: Mapped[str] = mapped_column(String(30), default="manual")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    expiry_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("supermarket", "external_id", name="uq_product_provider_external"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supermarket: Mapped[str] = mapped_column(String(40), default="REWE", index=True)
    external_id: Mapped[str] = mapped_column(String(140))
    ingredient: Mapped[str] = mapped_column(String(100), index=True)
    name_original: Mapped[str] = mapped_column(String(300))
    name_normalized: Mapped[str] = mapped_column(String(300), index=True)
    translated_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    package_size: Mapped[float] = mapped_column(Float)
    package_unit: Mapped[str] = mapped_column(String(20))
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(6), default="EUR")
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability: Mapped[str] = mapped_column(String(30), default="unknown")
    postcode_context: Mapped[str] = mapped_column(String(12), default="13353")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)


class ProductSemanticEmbedding(Base):
    __tablename__ = "product_semantic_embeddings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    model_name: Mapped[str] = mapped_column(String(120), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    vector_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProductOverride(Base):
    __tablename__ = "product_overrides"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingredient: Mapped[str] = mapped_column(String(100), unique=True)
    product_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class UserState(Base):
    __tablename__ = "user_state"
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CatalogRun(Base):
    __tablename__ = "catalog_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), default="REWE")
    status: Mapped[str] = mapped_column(String(20), default="healthy")
    products_seen: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    categories_processed: Mapped[int] = mapped_column(Integer, default=0)
    categories_successful: Mapped[int] = mapped_column(Integer, default=0)
    categories_failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ShoppingState(Base):
    __tablename__ = "shopping_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingredient: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(30), default="needed")
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purchased_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchased_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weeks: Mapped[int] = mapped_column(Integer, default=1)
    servings: Mapped[int] = mapped_column(Integer, default=2)
    strategy: Mapped[str] = mapped_column(String(40), default="best-value")
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_date: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlannedMeal(Base):
    __tablename__ = "planned_meals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    meal_id: Mapped[str] = mapped_column(String(80), index=True)
    day_index: Mapped[int] = mapped_column(Integer)
    meal_type: Mapped[str] = mapped_column(String(30), default="dinner")
    servings: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RecipeHistory(Base):
    __tablename__ = "recipe_history"
    __table_args__ = (UniqueConstraint("user_id", "record_key", name="uq_recipe_history_user_record"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(160), index=True)
    record_key: Mapped[str] = mapped_column(String(180))
    record_type: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(30), default="discovered", index=True)
    name: Mapped[str] = mapped_column(String(180))
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    meal_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Base.metadata.create_all(engine)


def _migrate_sqlite() -> None:
    if not IS_SQLITE:
        return
    wanted = {
        "catalog_runs": [
            ("categories_processed", "INTEGER DEFAULT 0"),
            ("categories_successful", "INTEGER DEFAULT 0"),
            ("categories_failed", "INTEGER DEFAULT 0"),
        ],
        "products": [("image_url", "TEXT")],
        "shopping_state": [
            ("product_id", "INTEGER"),
            ("purchased_quantity", "REAL"),
            ("purchased_unit", "TEXT"),
        ],
        "plans": [
            ("budget", "REAL"),
            ("strategy", "TEXT DEFAULT 'best-value'"),
        ],
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            table_exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
                {"name": table},
            ).first()
            if not table_exists:
                continue
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _parse_snapshot_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _auto_restore_local_rewe_snapshot() -> None:
    """Restore a previously-scraped local REWE catalog when cloud DB is empty.

    Bitewise historically stored the REWE snapshot in backend/data/grocery.db. When
    DATABASE_URL was later enabled, the app started reading Postgres instead, which
    can make a healthy local catalog look as if it vanished. This migration is
    deliberately conservative: it runs only when Postgres has zero REWE products,
    the local SQLite file exists, and AUTO_RESTORE_LOCAL_REWE is not disabled.
    """
    if IS_SQLITE or os.getenv("AUTO_RESTORE_LOCAL_REWE", "true").strip().lower() in {"0", "false", "no", "off"}:
        return
    if not DB_PATH.exists() or not DB_PATH.is_file() or DB_PATH.stat().st_size < 1024:
        return

    source = None
    target = None
    try:
        target = SessionLocal()
        cloud_count = target.query(Product).filter(Product.supermarket == "REWE").count()
        if cloud_count > 0:
            return

        source = sqlite3.connect(DB_PATH)
        source.row_factory = sqlite3.Row
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "products" not in tables:
            return
        rows = source.execute("SELECT * FROM products WHERE supermarket='REWE'").fetchall()
        if not rows:
            return
        source_columns = {row[1] for row in source.execute("PRAGMA table_info(products)")}
        fields = [
            "ingredient", "name_original", "name_normalized", "translated_name", "brand", "category",
            "package_size", "package_unit", "price", "price_per_unit", "currency", "product_url", "image_url",
            "availability", "postcode_context", "first_seen_at", "last_seen_at", "last_checked_at", "last_price",
        ]
        restored = 0
        for src in rows:
            external_id = str(src["external_id"] or "").strip() if "external_id" in source_columns else ""
            if not external_id:
                continue
            product = Product(
                supermarket="REWE",
                external_id=external_id,
                ingredient=str(src["ingredient"] or "") if "ingredient" in source_columns else "",
                name_original=str(src["name_original"] or "") if "name_original" in source_columns else "",
                name_normalized=str(src["name_normalized"] or "") if "name_normalized" in source_columns else "",
                package_size=float(src["package_size"] or 1) if "package_size" in source_columns else 1,
                package_unit=str(src["package_unit"] or "unit") if "package_unit" in source_columns else "unit",
            )
            for field in fields:
                if field not in source_columns or field in {"ingredient", "name_original", "name_normalized", "package_size", "package_unit"}:
                    continue
                value = src[field]
                if field in {"first_seen_at", "last_seen_at", "last_checked_at"}:
                    value = _parse_snapshot_dt(value)
                if value is not None:
                    setattr(product, field, value)
            target.add(product)
            restored += 1

        now = datetime.utcnow()
        target.add(CatalogRun(
            provider="REWE",
            status="healthy",
            products_seen=restored,
            errors=0,
            categories_processed=0,
            categories_successful=0,
            categories_failed=0,
            started_at=now,
            finished_at=now,
        ))
        settings = {
            "rewe_snapshot_persistent": "true",
            "rewe_snapshot_source": "auto-restored-local-sqlite",
            "rewe_snapshot_product_count": str(restored),
            "rewe_snapshot_last_success_at": now.isoformat(),
            "rewe_snapshot_auto_restored_at": now.isoformat(),
        }
        for key, value in settings.items():
            row = target.get(AppSetting, key)
            if row:
                row.value = value
            else:
                target.add(AppSetting(key=key, value=value))
        target.commit()
        print(f"Bitewise restored {restored} REWE products from {DB_PATH} into the cloud database.")
    except Exception as exc:
        if target:
            target.rollback()
        print(f"Bitewise could not auto-restore the local REWE snapshot: {exc}")
    finally:
        if source:
            source.close()
        if target:
            target.close()



def _snapshot_float(value, default=None):
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = float(str(value).strip().replace(",", "."))
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _snapshot_package_size(name: str, current_size: float, current_unit: str) -> float:
    """Correct multi-packs such as 2x200ml and 4x50g in older scraper exports."""
    match = re.search(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", name or "", re.I)
    if not match:
        return current_size
    count = int(match.group(1))
    amount = float(match.group(2).replace(",", "."))
    source_unit = match.group(3).lower()
    if source_unit == "kg":
        amount *= 1000
        source_unit = "g"
    elif source_unit == "l":
        amount *= 1000
        source_unit = "ml"
    return count * amount if source_unit == current_unit else current_size


def _snapshot_pack_pricing(name: str, package_size: float, package_unit: str, raw_price, raw_price_per_unit):
    """Convert displayed €/kg or €/l unit prices into actual package checkout prices."""
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml|stück|stk\.?|st\.)\s*=\s*(\d+[,.]\d{2})\s*€",
        name or "",
        re.I,
    )
    unit_price = _snapshot_float(match.group(3)) if match else None
    reference_quantity = _snapshot_float(match.group(1)) if match else None
    raw_unit = match.group(2).lower() if match else ""
    if raw_unit == "kg":
        reference_quantity = reference_quantity * 1000 if reference_quantity is not None else None
        reference_unit = "g"
    elif raw_unit == "l":
        reference_quantity = reference_quantity * 1000 if reference_quantity is not None else None
        reference_unit = "ml"
    elif raw_unit in {"g", "ml"}:
        reference_unit = raw_unit
    elif raw_unit:
        reference_unit = "unit"
    else:
        reference_unit = ""
    if (
        unit_price is not None and reference_quantity is not None
        and reference_quantity > 0 and package_size > 0
        and reference_unit == package_unit
    ):
        normalized_unit_price = unit_price / reference_quantity
        return round(normalized_unit_price * package_size, 2), normalized_unit_price
    fallback = _snapshot_float(raw_price)
    per_unit = _snapshot_float(raw_price_per_unit)
    if per_unit is None and fallback is not None and package_size > 0:
        per_unit = fallback / package_size
    return fallback, per_unit


def _auto_import_rewe_csv_snapshot() -> None:
    """Seed an empty product table from the committed REWE CSV snapshot exactly once.

    The CSV is a fallback baseline, not a live refresh. Never overwrite a non-empty
    catalog: postcode-specific live REWE data and existing user overrides take priority.
    """
    snapshot_path = BACKEND_DIR / "data" / "catalog" / "rewe_products.csv"
    explicit_db_path = bool(_configured_local_db)
    import_override = os.getenv("BITEWISE_IMPORT_CATALOG_SNAPSHOT", "").strip().lower()
    if explicit_db_path and import_override not in {"1", "true", "yes", "on"}:
        # Tests and isolated workspaces use BITEWISE_LOCAL_DB_PATH to guarantee
        # clean databases. They must opt in explicitly when testing this importer.
        return
    if not snapshot_path.is_file() or snapshot_path.stat().st_size < 100:
        return

    db = None
    try:
        db = SessionLocal()
        existing = db.query(Product).filter(Product.supermarket == "REWE").count()
        if existing:
            return

        setting_row = db.get(AppSetting, "postcode")
        postcode = setting_row.value if setting_row and setting_row.value else "13353"
        now = datetime.utcnow()
        products = []
        expected_columns = [
            "id", "supermarket", "external_id", "ingredient", "name_original",
            "name_normalized", "translated_name", "brand", "category", "package_size",
            "package_unit", "price", "price_per_unit", "currency", "product_url",
            "image_url", "availability", "postcode_context", "first_seen_at",
            "last_seen_at", "last_checked_at", "last_price",
        ]
        legacy_columns = [
            "id", "supermarket", "ingredient", "name_original", "name_normalized",
            "translated_name", "brand", "category", "package_size", "package_unit",
            "price", "price_per_unit", "currency", "availability", "last_seen_at",
            "last_checked_at",
        ]
        required = {"id", "supermarket", "ingredient", "name_original", "name_normalized"}
        with snapshot_path.open("r", encoding="utf-8-sig", newline="") as handle:
            first_row = next(csv.reader(handle), [])
            handle.seek(0)
            # Accept both proper headered CSV and the existing sqlite3 export,
            # which contains the selected columns but no header row.
            if required.issubset(set(first_row)):
                reader = csv.DictReader(handle)
            else:
                if len(first_row) == len(expected_columns):
                    fieldnames = expected_columns
                elif len(first_row) == len(legacy_columns):
                    fieldnames = legacy_columns
                else:
                    raise ValueError(
                        f"REWE CSV snapshot has {len(first_row)} columns; expected "
                        f"{len(legacy_columns)} (legacy) or {len(expected_columns)} (full)"
                    )
                reader = csv.DictReader(handle, fieldnames=fieldnames)

            for row in reader:
                supermarket = str(row.get("supermarket") or "REWE").strip().upper()
                name = str(row.get("name_original") or "").strip()
                if supermarket != "REWE" or not name:
                    continue
                source_id = str(row.get("id") or "").strip()
                if not source_id:
                    source_id = str(len(products) + 1)
                package_size = _snapshot_float(row.get("package_size"), 1.0)
                package_size = package_size if package_size and package_size > 0 else 1.0
                package_unit = str(row.get("package_unit") or "unit").strip()[:20]
                package_size = _snapshot_package_size(name, package_size, package_unit)
                pack_price, normalized_price_per_unit = _snapshot_pack_pricing(
                    name, package_size, package_unit, row.get("price"), row.get("price_per_unit")
                )
                products.append(Product(
                    supermarket="REWE",
                    external_id=(str(row.get("external_id") or "").strip() or f"csv-snapshot-{source_id}"),
                    ingredient=str(row.get("ingredient") or "").strip()[:100] or "unknown",
                    name_original=name[:300],
                    name_normalized=str(row.get("name_normalized") or name.lower()).strip()[:300],
                    translated_name=(str(row.get("translated_name") or "").strip()[:300] or None),
                    brand=(str(row.get("brand") or "").strip()[:120] or None),
                    category=(str(row.get("category") or "").strip()[:120] or None),
                    package_size=package_size,
                    package_unit=package_unit,
                    price=pack_price,
                    price_per_unit=normalized_price_per_unit,
                    currency=str(row.get("currency") or "EUR").strip()[:6],
                    product_url=(str(row.get("product_url") or "").strip() or None),
                    image_url=(str(row.get("image_url") or "").strip() or None),
                    availability=str(row.get("availability") or "unknown").strip()[:30],
                    postcode_context=(str(row.get("postcode_context") or postcode).strip()[:12]),
                    first_seen_at=_parse_snapshot_dt(row.get("first_seen_at")) or _parse_snapshot_dt(row.get("last_seen_at")) or now,
                    last_seen_at=_parse_snapshot_dt(row.get("last_seen_at")) or now,
                    last_checked_at=_parse_snapshot_dt(row.get("last_checked_at")) or now,
                    last_price=_snapshot_float(row.get("last_price")),
                ))

        if not products:
            return
        db.add_all(products)
        db.add(CatalogRun(
            provider="REWE",
            status="snapshot",
            products_seen=len(products),
            errors=0,
            categories_processed=0,
            categories_successful=0,
            categories_failed=0,
            started_at=now,
            finished_at=now,
        ))
        settings = {
            "rewe_snapshot_source": "committed-csv-snapshot",
            "rewe_snapshot_product_count": str(len(products)),
            "rewe_snapshot_last_imported_at": now.isoformat(),
            "rewe_snapshot_price_repair_v1": "normalized-on-import",
        }
        for key, value in settings.items():
            setting = db.get(AppSetting, key)
            if setting:
                setting.value = value
            else:
                db.add(AppSetting(key=key, value=value))
        db.commit()
        print(f"Bitewise imported {len(products)} REWE products from {snapshot_path}.")
    except Exception as exc:
        if db:
            db.rollback()
        print(f"Bitewise could not import the committed REWE CSV snapshot: {exc}")
    finally:
        if db:
            db.close()



def _repair_snapshot_unit_prices_once() -> None:
    """Repair legacy REWE unit-price rows using conservative snapshot identity checks.

    Older scraper runs stored a displayed €/kg or €/l reference price as the
    package checkout price. Prefer the old database ID, but fall back to an exact
    REWE product-name + ingredient match because IDs change between imports.
    Never overwrite a price that differs from both the raw snapshot and its
    normalized package price.
    """
    # Isolated QA runs set BITEWISE_LOCAL_DB_PATH to a temporary database.
    # Never compare that empty test database with the developer's committed catalog.
    repair_override = os.getenv("BITEWISE_REPAIR_CATALOG_SNAPSHOT", "").strip().lower()
    if _configured_local_db and repair_override not in {"1", "true", "yes", "on"}:
        return

    snapshot_path = BACKEND_DIR / "data" / "catalog" / "rewe_products.csv"
    if not snapshot_path.is_file():
        return
    db = None
    try:
        db = SessionLocal()
        if (
            db.get(AppSetting, "rewe_snapshot_price_repair_v1")
            or db.get(AppSetting, "rewe_snapshot_price_repair_attempt_v1")
        ):
            return
        rows = []
        expected_reference_rows = 0
        with snapshot_path.open("r", encoding="utf-8-sig", newline="") as handle:
            first_row = next(csv.reader(handle), [])
            handle.seek(0)
            expected_columns = [
                "id", "supermarket", "ingredient", "name_original", "name_normalized",
                "translated_name", "brand", "category", "package_size", "package_unit",
                "price", "price_per_unit", "currency", "availability", "last_seen_at",
                "last_checked_at",
            ]
            required = {"id", "supermarket", "ingredient", "name_original", "name_normalized"}
            reader = (
                csv.DictReader(handle)
                if required.issubset(set(first_row))
                else csv.DictReader(handle, fieldnames=expected_columns)
            )
            for row in reader:
                name = str(row.get("name_original") or "").strip()
                if str(row.get("supermarket") or "REWE").strip().upper() != "REWE":
                    continue
                if re.search(r"1\s*(?:kg|l)\s*=", name, re.I):
                    expected_reference_rows += 1
                    rows.append(row)
        if expected_reference_rows < 100:
            return

        repaired = 0
        already_normalized = 0
        changed_live_prices = 0
        unmatched = 0
        for row in rows:
            name = str(row.get("name_original") or "").strip()
            ingredient = str(row.get("ingredient") or "").strip()
            try:
                product_id = int(row.get("id") or 0)
            except (TypeError, ValueError):
                product_id = 0
            product = db.get(Product, product_id) if product_id else None
            if product and (
                product.supermarket != "REWE"
                or product.name_original != name
                or (ingredient and product.ingredient != ingredient)
            ):
                product = None

            # Internal product IDs are not stable across catalog imports. Fall back
            # to an exact title and ingredient match, never a fuzzy title match.
            if product is None and name:
                candidates = db.query(Product).filter(
                    Product.supermarket == "REWE",
                    Product.name_original == name,
                )
                if ingredient:
                    candidates = candidates.filter(Product.ingredient == ingredient)
                matches = candidates.limit(2).all()
                product = matches[0] if len(matches) == 1 else None
            if product is None:
                unmatched += 1
                continue

            source_price = _snapshot_float(row.get("price"))
            if source_price is None or product.price is None:
                unmatched += 1
                continue
            package_size = _snapshot_float(row.get("package_size"), product.package_size) or product.package_size
            package_unit = str(row.get("package_unit") or product.package_unit).strip()
            package_size = _snapshot_package_size(name, package_size, package_unit)
            pack_price, unit_price = _snapshot_pack_pricing(
                name, package_size, package_unit,
                row.get("price"), row.get("price_per_unit"),
            )
            if pack_price is None or unit_price is None:
                unmatched += 1
                continue

            current_price = float(product.price)
            if abs(current_price - source_price) <= 0.011:
                product.package_size = package_size
                product.package_unit = package_unit
                product.price = pack_price
                product.price_per_unit = unit_price
                repaired += 1
            elif (
                abs(current_price - pack_price) <= 0.011
                and abs(float(product.package_size or 0) - package_size) <= 0.001
                and product.price_per_unit is not None
                and abs(float(product.price_per_unit) - unit_price) <= 0.000011
            ):
                already_normalized += 1
            else:
                # A changed live price is not evidence of a legacy pricing bug.
                changed_live_prices += 1

        # Count both repaired and already-correct rows as verified source matches.
        verified = repaired + already_normalized
        if verified >= expected_reference_rows * 0.70:
            db.add(AppSetting(key="rewe_snapshot_price_repair_v1", value=str(repaired)))
            db.commit()
            if repaired:
                print(
                    f"Bitewise repaired {repaired} legacy REWE package prices "
                    f"({already_normalized} were already normalized)."
                )
            else:
                print(
                    f"Bitewise verified REWE snapshot pricing: "
                    f"{already_normalized} rows were already normalized."
                )
        else:
            # This is a one-time migration check. Persist its result to avoid a
            # misleading warning on every app/test startup; a future repair can
            # deliberately bump the versioned key after a new migration is added.
            db.add(AppSetting(
                key="rewe_snapshot_price_repair_attempt_v1",
                value=(
                    f"skipped; verified={verified}; expected={expected_reference_rows}; "
                    f"unmatched={unmatched}; changed_live_prices={changed_live_prices}"
                ),
            ))
            db.commit()
            print(
                "Bitewise skipped REWE snapshot price repair once: "
                f"{verified}/{expected_reference_rows} snapshot rows could be verified; "
                "existing live catalog prices were left untouched."
            )
    except Exception as exc:
        if db:
            db.rollback()
        print(f"Bitewise could not repair legacy REWE snapshot prices: {exc}")
    finally:
        if db:
            db.close()


_migrate_sqlite()
_auto_restore_local_rewe_snapshot()
_auto_import_rewe_csv_snapshot()
_repair_snapshot_unit_prices_once()
