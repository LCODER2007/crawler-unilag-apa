"""Run once to add new APA columns to the existing SQLite database."""

import sys

sys.path.insert(0, ".")
from sqlalchemy import inspect, text

from uraas.database import engine

NEW_COLS = [
    ("items", "dc_type", "TEXT"),
    ("items", "dc_language", "TEXT"),
    ("items", "dc_subject", "TEXT"),
    ("items", "docid", "TEXT UNIQUE"),
    ("items", "docid_assigned_at", "DATETIME"),
    ("items", "content_type", 'TEXT DEFAULT "research_paper"'),
    ("items", "tk_label", "TEXT"),
    ("items", "tk_community", "TEXT"),
    ("items", "patent_id", "TEXT"),
    ("items", "patent_date", "DATETIME"),
    ("items", "language_code", "TEXT"),
    ("items", "is_african_language", "INTEGER DEFAULT 0"),
    ("items", "sdg_tags", "TEXT"),
    ("items", "ai_keywords", "TEXT"),
    ("authors", "orcid", "TEXT"),
    ("authors", "ror", "TEXT"),
    ("communities", "ror_id", "TEXT"),
    ("communities", "institution", "TEXT"),
]

inspector = inspect(engine)
with engine.connect() as conn:
    for table, col, col_type in NEW_COLS:
        existing = [c["name"] for c in inspector.get_columns(table)]
        if col not in existing:
            # SQLite doesn't support UNIQUE in ALTER TABLE — skip constraint
            safe_type = col_type.replace(" UNIQUE", "")
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {safe_type}"))
            print(f"  + {table}.{col}")
        else:
            print(f"  . {table}.{col} (exists)")
    conn.commit()

print("Migration complete.")
