"""
Database Initialization Script
Creates all tables and seeds Communities and Collections based on UNILAG structure.
"""

import os
import sys

# Add project root to path (parent of scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Collection, Community, SessionLocal, init_db, sync_schema_columns

# Import citation tracker models so SQLAlchemy registers their tables with
# Base.metadata before create_all() runs — otherwise citations,
# citation_metrics, and author_metrics are never created.
import uraas.services.citation_tracker  # noqa: F401

from uraas.utils.unilag_classifier import UNILAG_STRUCTURE

# Base.metadata.create_all() (called by init_db() below) only creates tables
# that don't exist yet — it never alters an EXISTING table to add a column a
# newer version of the ORM model expects. On a fresh DB that's a no-op (every
# table is new, so every column is already there); on a database that
# already existed before some column was added to the model (e.g. an HF
# Space's persistent /data/uraas.db surviving across deploys), the table is
# silently left on its old schema and the very next query touching that
# column crashes — confirmed live 2026-07-19: the Space failed to start
# entirely ("no such column: communities.unit_type") because its persistent
# DB predated that column and nothing ever ran the matching migration
# against it. Running every idempotent (column_exists()-guarded, ALTER-TABLE-
# only) migration here means any existing database — this one included —
# self-heals to the current schema on every startup, not just fresh ones.
# migrate_add_ror.py is deliberately excluded: unlike the others it also
# *writes* a default ROR value to existing NULL rows, and that default is
# the deprecated pre-2026 UNILAG ROR (03qcnxw14, since corrected to
# 05rk03822 by migrate_unilag_ror.py) — safe to run once by hand, not safe
# to run unconditionally on every boot.
_SCHEMA_MIGRATIONS = [
    "migrate_add_pid_source",
    "migrate_add_community_ace_columns",
    "migrate_add_author_isni",
    "migrate_add_item_funders",
    "migrate_2026_upgrade",
    "migrate_add_sc_columns",
]


def run_schema_migrations():
    import importlib

    print("Applying schema migrations (idempotent — safe to re-run)...")
    print("  Generic column sync:")
    sync_schema_columns()
    for mod_name in _SCHEMA_MIGRATIONS:
        try:
            mod = importlib.import_module(mod_name)
            mod.main()
        except Exception as e:
            # A migration failing shouldn't take down the whole app if the
            # underlying tables/columns it depends on genuinely aren't there
            # yet for some other reason — log and continue rather than abort
            # startup entirely (seeding below will surface the real error if
            # it still matters).
            print(f"  [WARN] {mod_name} failed (continuing): {e}")
    print()


def seed_communities_and_collections():
    """Seed the database with UNILAG faculty and department structure."""
    session = SessionLocal()

    try:
        print("Seeding Communities (Faculties) and Collections (Departments)...")

        for faculty_name, departments in UNILAG_STRUCTURE.items():
            # Check if community exists
            community = session.query(Community).filter_by(name=faculty_name).first()
            if not community:
                community = Community(name=faculty_name)
                session.add(community)
                session.flush()
                print(f"  Created Community: {faculty_name}")

            # Create collections (departments) under this community
            for dept_name, keywords in departments.items():
                collection = session.query(Collection).filter_by(name=dept_name).first()
                if not collection:
                    collection = Collection(
                        community_id=community.id,
                        name=dept_name,
                        keywords=", ".join(keywords),
                    )
                    session.add(collection)
                    print(f"    Created Collection: {dept_name}")

        session.commit()
        print("\n[OK] Database seeding completed successfully!")
        print(f"  Total Communities: {session.query(Community).count()}")
        print(f"  Total Collections: {session.query(Collection).count()}")

    except Exception as e:
        print(f"\n[ERR] Error seeding database: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def main():
    print("=" * 60)
    print("URAAS Database Initialization")
    print("=" * 60)
    print()

    # Create all tables
    print("Creating database tables...")
    init_db()
    print("[OK] Tables created successfully!")
    print()

    # Heal any existing database (e.g. a persistent volume surviving across
    # deploys) whose tables predate a column the current models expect.
    run_schema_migrations()

    # Seed communities and collections
    seed_communities_and_collections()
    print()
    print("=" * 60)
    print("Database is ready for use!")
    print("=" * 60)


if __name__ == "__main__":
    main()
