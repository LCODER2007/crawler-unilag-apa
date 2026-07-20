"""
Schema migration: add pid_source column to items table, and backfill it for
existing rows. Idempotent.
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
    print("Migration: adding pid_source to items")

    dialect = engine.dialect.name
    print(f"Dialect: {dialect}")

    if not column_exists("items", "pid_source"):
        with engine.begin() as conn:
            print("  -> ALTER TABLE items ADD COLUMN pid_source VARCHAR(20)")
            conn.execute(text("ALTER TABLE items ADD COLUMN pid_source VARCHAR(20)"))
    else:
        print("  pid_source already present, skipping ALTER")

    with engine.begin() as conn:
        r1 = conn.execute(
            text(
                "UPDATE items SET pid_source = 'handle' "
                "WHERE pid_source IS NULL "
                "AND source_repository LIKE '%IR (OAI-PMH)%' "
                "AND url LIKE '%/handle/%'"
            )
        )
        print(f"  -> backfilled pid_source='handle' on {r1.rowcount} rows")

        r2 = conn.execute(
            text(
                "UPDATE items SET pid_source = 'ark' "
                "WHERE pid_source IS NULL AND ark IS NOT NULL"
            )
        )
        print(f"  -> backfilled pid_source='ark' on {r2.rowcount} rows")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
