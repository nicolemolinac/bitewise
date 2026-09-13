import os
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
    availability: Mapped[str] = mapped_column(String(30), default="unknown")
    postcode_context: Mapped[str] = mapped_column(String(12), default="13353")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)


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
            "package_size", "package_unit", "price", "price_per_unit", "currency", "product_url",
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


_migrate_sqlite()
_auto_restore_local_rewe_snapshot()
