"""
Schema migration: 2026 UNESCO upgrade. Idempotent; safe on SQLite + Postgres.

Adds to items:
  - alignment_scores (JSON TEXT) + alignment_version  (framework alignment)
  - coauthor_countries / african_country_count / is_intra_african  (collaboration)
  - openalex_id / counts_by_year / cited_by_count / african_citation_share  (citations)
  - ark / ark_assigned_at  (ARK persistent identifiers)

New tables (item_affiliations, alignment_aggregates) are created by
scripts/init_db.py via Base.metadata.create_all — run init_db.py first.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from uraas.database import engine

# (column, DDL type clause) — types chosen to work on both SQLite and Postgres.
ITEMS_COLUMNS = [
    ("alignment_scores", "TEXT"),
    ("alignment_version", "INTEGER DEFAULT 0"),
    ("coauthor_countries", "TEXT"),
    ("african_country_count", "INTEGER DEFAULT 0"),
    ("is_intra_african", "BOOLEAN DEFAULT FALSE"),
    ("openalex_id", "VARCHAR(64)"),
    ("counts_by_year", "TEXT"),
    ("cited_by_count", "INTEGER DEFAULT 0"),
    ("african_citation_share", "FLOAT"),
    ("ark", "VARCHAR(128)"),
    ("ark_assigned_at", "TIMESTAMP"),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_items_is_intra_african ON items (is_intra_african)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_items_ark ON items (ark)",
]


def column_exists(insp, table: str, column: str) -> bool:
    return column in {c["name"] for c in insp.get_columns(table)}


def main() -> int:
    print("Migration: 2026 upgrade (alignment / collaboration / citations / ARK)")

    dialect = engine.dialect.name
    print(f"Dialect: {dialect}")

    insp = inspect(engine)
    statements = []
    for column, ddl_type in ITEMS_COLUMNS:
        if column_exists(insp, "items", column):
            print(f"  {column} already present, skipping")
            continue
        if dialect == "sqlite" and "BOOLEAN" in ddl_type:
            # SQLite stores booleans as integers
            ddl_type = ddl_type.replace("BOOLEAN", "INTEGER").replace("FALSE", "0")
        statements.append(f"ALTER TABLE items ADD COLUMN {column} {ddl_type}")

    if statements:
        with engine.begin() as conn:
            for stmt in statements:
                print(f"  -> {stmt}")
                conn.execute(text(stmt))
    else:
        print("  All columns already present.")

    for stmt in INDEXES:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
                print(
                    f"  -> {stmt.split(' ON ')[0].replace('CREATE ', '').strip()} ensured"
                )
        except Exception as e:
            print(f"  (index creation skipped: {e})")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
