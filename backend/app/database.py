from sqlalchemy import create_engine, String, Integer, Float, Boolean, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "grocery.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase): pass

class UserEvent(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meal_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(30))

class PantryItem(Base):
    __tablename__ = "pantry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingredient: Mapped[str] = mapped_column(String(100), unique=True)
    quantity: Mapped[float] = mapped_column(Float, default=1)
    unit: Mapped[str] = mapped_column(String(20), default="unit")

Base.metadata.create_all(engine)
