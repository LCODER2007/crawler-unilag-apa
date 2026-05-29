"""
Backfill special_collection_score + special_collection_categories on existing items.

Runs classify_special_collections() over every Item (title + abstract + dc_subject)
and writes the score/categories. Idempotent — re-running on already-scored rows
produces the same values.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Item, SessionLocal
from uraas.utils.ai_classifier import classify_special_collections

BATCH_SIZE = 500


def main() -> int:
    session = SessionLocal()
    try:
        total = session.query(Item).count()
        print(f"Backfilling SC score for {total} items...")

        scored = 0
        hits = 0
        offset = 0
        while offset < total:
            batch = (
                session.query(Item)
                .order_by(Item.id)
                .offset(offset)
                .limit(BATCH_SIZE)
                .all()
            )
            if not batch:
                break

            for item in batch:
                sc = classify_special_collections(
                    item.title or "",
                    item.abstract or "",
                    item.dc_subject or "",
                )
                if sc:
                    item.special_collection_score = float(sum(h["score"] for h in sc))
                    item.special_collection_categories = ",".join(
                        h["category"] for h in sc
                    )
                    hits += 1
                else:
                    item.special_collection_score = 0.0
                    item.special_collection_categories = ""
                scored += 1

            session.commit()
            offset += len(batch)
            print(f"  {scored}/{total} scored ({hits} SC hits so far)")

        print()
        print(f"Done. {scored} items scored, {hits} matched a special collection.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
