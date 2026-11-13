"""Build/update the local multilingual REWE semantic index.

Run from backend/: python index_rewe_semantics.py
First run downloads the compact multilingual model; no Gemini calls are made.
"""
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from app.database import SessionLocal
from app.semantic_catalog import index_rewe_products


def main():
    db = SessionLocal()
    try:
        def report_progress(processed, pending, total_products):
            print(
                f"Embedding REWE catalog: {processed}/{pending} changed products "
                f"({total_products} products in the full catalog)"
            )

        result = index_rewe_products(db, progress_callback=report_progress)
        print("REWE SEMANTIC INDEX")
        for key, value in result.items():
            print(f"{key}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
