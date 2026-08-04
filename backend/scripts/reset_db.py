"""
scripts/reset_db.py

Drop and recreate all tables. Required after schema changes such as adding
the users table and making Dataset.user_id a required foreign key.

Usage (from backend/):
    python scripts/reset_db.py
"""

from __future__ import annotations

from pathlib import Path

from app.db import Base, engine

DB_FILES = [
    Path("missingness_pipeline.db"),
    Path(__file__).parent.parent / "missingness_pipeline.db",
]


def main() -> None:
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)

    for db_file in DB_FILES:
        if db_file.exists():
            print(f"Database file: {db_file.resolve()}")

    print("Done. Restart the server if it is running.")


if __name__ == "__main__":
    main()
