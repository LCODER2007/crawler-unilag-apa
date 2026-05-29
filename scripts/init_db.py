"""
Database Initialization Script
Creates all tables and seeds Communities and Collections based on UNILAG structure.
"""

import os
import sys

# Add project root to path (parent of scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Collection, Community, SessionLocal, init_db
from uraas.utils.unilag_classifier import UNILAG_STRUCTURE


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

    # Seed communities and collections
    seed_communities_and_collections()
    print()
    print("=" * 60)
    print("Database is ready for use!")
    print("=" * 60)


if __name__ == "__main__":
    main()
