"""
Schema migration: add unit_type, pmd, pmd_assigned_at columns to communities
table, so Africa Centres of Excellence (ACE) can be tracked as organisational
units alongside faculties, each with a self-minted persistent ID (PMD).
Idempotent.
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
    print("Migration: adding unit_type/pmd/pmd_assigned_at to communities")

    dialect = engine.dialect.name
    print(f"Dialect: {dialect}")

    statements = []
    if not column_exists("communities", "unit_type"):
        statements.append(
            "ALTER TABLE communities ADD COLUMN unit_type VARCHAR(30) DEFAULT 'faculty'"
        )
    else:
        print("  unit_type already present, skipping")

    if not column_exists("communities", "pmd"):
        statements.append("ALTER TABLE communities ADD COLUMN pmd VARCHAR(128)")
    else:
        print("  pmd already present, skipping")

    if not column_exists("communities", "pmd_assigned_at"):
        statements.append(
            "ALTER TABLE communities ADD COLUMN pmd_assigned_at TIMESTAMP"
        )
    else:
        print("  pmd_assigned_at already present, skipping")

    if statements:
        with engine.begin() as conn:
            for stmt in statements:
                print(f"  -> {stmt}")
                conn.execute(text(stmt))
    else:
        print("Nothing to add.")

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_communities_pmd "
                    "ON communities (pmd)"
                )
            )
            print("  -> index ux_communities_pmd ensured")
    except Exception as e:
        print(f"  (index creation skipped: {e})")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
