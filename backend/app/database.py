from datetime import datetime
from pathlib import Path
from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "grocery.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
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
    servings: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(30), default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)


def _migrate_sqlite() -> None:
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


_migrate_sqlite()
