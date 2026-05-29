import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import SessionLocal, Item
from sqlalchemy import func


def inspect():
    session = SessionLocal()
    try:
        total_items = session.query(Item).count()
        print(f"Total items: {total_items}")

        # Group by institution/ror
        inst_counts = (
            session.query(Item.institution, Item.ror, func.count(Item.id))
            .group_by(Item.institution, Item.ror)
            .all()
        )
        print("\nItems per institution:")
        for inst, ror, count in inst_counts:
            print(f"  - {inst} ({ror}): {count} papers")

        # African language papers
        african_lang_count = (
            session.query(func.count(Item.id))
            .filter(Item.is_african_language == True)
            .scalar()
        )
        print(f"\nAfrican language papers: {african_lang_count}")

        # TK vitality papers
        tk_count = (
            session.query(func.count(Item.id))
            .filter(
                (Item.tk_label.isnot(None))
                | (Item.content_type == "indigenous_knowledge")
            )
            .scalar()
        )
        print(f"Indigenous knowledge / TK papers: {tk_count}")

        # Patents
        patent_count = (
            session.query(func.count(Item.id))
            .filter(Item.patent_id.isnot(None))
            .scalar()
        )
        print(f"Patents: {patent_count}")

        # DocID coverage
        docid_count = (
            session.query(func.count(Item.id)).filter(Item.docid.isnot(None)).scalar()
        )
        print(f"DocID assigned papers: {docid_count}")

        # Access policy / PDFs
        from uraas.database import File

        pdf_count = session.query(File).count()
        print(f"Downloaded PDFs: {pdf_count}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    inspect()
