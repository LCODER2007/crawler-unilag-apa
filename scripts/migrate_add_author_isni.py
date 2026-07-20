"""
Schema migration: add isni column to authors table. Idempotent.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from uraas.database import engine


def column_exists(table: str, column: str) -> bool:
    insp = inspect(engine)
    return column in {c["name"] for c in insp.get_columns(table)}


def main() -> int:
    print("Migration: adding isni to authors")

    dialect = engine.dialect.name
    print(f"Dialect: {dialect}")

    if not column_exists("authors", "isni"):
        with engine.begin() as conn:
            print("  -> ALTER TABLE authors ADD COLUMN isni VARCHAR(20)")
            conn.execute(text("ALTER TABLE authors ADD COLUMN isni VARCHAR(20)"))
    else:
        print("  isni already present, skipping ALTER")

    try:
        with engine.begin() as conn:
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_authors_isni ON authors (isni)")
            )
            print("  -> index ix_authors_isni ensured")
    except Exception as e:
        print(f"  (index creation skipped: {e})")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
