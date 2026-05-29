"""
Database migration: Add ROR support for multi-institution comparison
"""

from sqlalchemy import text

from uraas.database import Item, SessionLocal, engine


def migrate():
    print("Adding ROR columns to items table...")

    with engine.connect() as conn:
        try:
            # Add ror column
            conn.execute(text("ALTER TABLE items ADD COLUMN ror VARCHAR(128)"))
            conn.execute(text("CREATE INDEX ix_items_ror ON items(ror)"))
            print("✓ Added ror column and index")
        except Exception as e:
            if (
                "duplicate column" in str(e).lower()
                or "already exists" in str(e).lower()
            ):
                print("✓ ROR column already exists")
            else:
                print(f"Error: {e}")

        try:
            # Add institution column if not exists
            conn.execute(text("ALTER TABLE items ADD COLUMN institution VARCHAR(255)"))
            print("✓ Added institution column")
        except Exception as e:
            if (
                "duplicate column" in str(e).lower()
                or "already exists" in str(e).lower()
            ):
                print("✓ Institution column already exists")
            else:
                print(f"Error: {e}")

        conn.commit()

    # Set default ROR for UNILAG papers
    print("\nSetting default ROR for existing UNILAG papers...")
    session = SessionLocal()
    try:
        unilag_ror = "https://ror.org/03qcnxw14"
        count = (
            session.query(Item)
            .filter(Item.ror.is_(None))
            .update(
                {Item.ror: unilag_ror, Item.institution: "University of Lagos"},
                synchronize_session=False,
            )
        )
        session.commit()
        print(f"✓ Updated {count} papers with UNILAG ROR")
    finally:
        session.close()

    print("\nMigration complete!")
    print("\nNext steps:")
    print("1. Add Comparator tab to dashboard")
    print("2. Test multi-institution comparison")
    print("3. Add more institutions to database")


if __name__ == "__main__":
    migrate()
