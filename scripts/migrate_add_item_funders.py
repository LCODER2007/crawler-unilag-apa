"""
Schema migration: add funders column to items table. Idempotent.

No backfill of existing rows here — populating funders for already-crawled
items needs a live re-fetch per item (OpenAlex work lookup by openalex_id),
which belongs in a separate backfill script, not this migration.
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
    print("Migration: adding funders to items")

    dialect = engine.dialect.name
    print(f"Dialect: {dialect}")

    if not column_exists("items", "funders"):
        with engine.begin() as conn:
            print("  -> ALTER TABLE items ADD COLUMN funders TEXT")
            conn.execute(text("ALTER TABLE items ADD COLUMN funders TEXT"))
    else:
        print("  funders already present, skipping ALTER")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
