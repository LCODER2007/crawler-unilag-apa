"""
Schema migration: add special_collection_score + special_collection_categories
columns to items table. Idempotent.
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
    print(
        "Migration: adding special_collection_score + special_collection_categories to items"
    )

    dialect = engine.dialect.name
    print(f"Dialect: {dialect}")

    statements = []
    if not column_exists("items", "special_collection_score"):
        statements.append(
            "ALTER TABLE items ADD COLUMN special_collection_score FLOAT DEFAULT 0.0"
        )
    else:
        print("  special_collection_score already present, skipping")

    if not column_exists("items", "special_collection_categories"):
        # TEXT for both sqlite + postgres
        statements.append(
            "ALTER TABLE items ADD COLUMN special_collection_categories TEXT"
        )
    else:
        print("  special_collection_categories already present, skipping")

    if not statements:
        print("Nothing to do.")
        return 0

    with engine.begin() as conn:
        for stmt in statements:
            print(f"  -> {stmt}")
            conn.execute(text(stmt))

    # Index on score so ORDER BY score DESC is fast
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_items_special_collection_score "
                    "ON items (special_collection_score)"
                )
            )
            print("  -> index ix_items_special_collection_score ensured")
    except Exception as e:
        print(f"  (index creation skipped: {e})")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
