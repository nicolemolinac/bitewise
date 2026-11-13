"""Build/update the local multilingual REWE semantic index.

Run from backend/: python index_rewe_semantics.py
First run downloads the compact multilingual model; no Gemini calls are made.
"""
from app.database import SessionLocal
from app.semantic_catalog import index_rewe_products


def main():
    db = SessionLocal()
    try:
        result = index_rewe_products(db)
        print("REWE SEMANTIC INDEX")
        for key, value in result.items():
            print(f"{key}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
