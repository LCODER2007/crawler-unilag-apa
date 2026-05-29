import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Author, Community, Item, SessionLocal


def migrate():
    session = SessionLocal()
    try:
        old_ror = "https://ror.org/03qcnxw14"
        new_ror = "https://ror.org/05rk03822"

        print("Migrating UNILAG RORs in database...")

        # 1. Update items
        item_count = (
            session.query(Item)
            .filter(Item.ror == old_ror)
            .update({Item.ror: new_ror}, synchronize_session=False)
        )
        print(f"[OK] Updated {item_count} items")

        # 2. Update communities
        comm_count = (
            session.query(Community)
            .filter((Community.ror == old_ror) | (Community.ror_id == old_ror))
            .update(
                {Community.ror: new_ror, Community.ror_id: new_ror},
                synchronize_session=False,
            )
        )
        print(f"[OK] Updated {comm_count} communities")

        # 3. Update authors
        author_count = (
            session.query(Author)
            .filter(Author.ror == old_ror)
            .update({Author.ror: new_ror}, synchronize_session=False)
        )
        print(f"[OK] Updated {author_count} authors")

        session.commit()
        print("Migration complete successfully!")

    except Exception as e:
        session.rollback()
        print(f"Error during migration: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    migrate()
