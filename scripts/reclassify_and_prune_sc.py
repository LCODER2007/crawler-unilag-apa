"""
Re-classify every Item with the Special Collections decision engine and prune
everything that is not a genuine special collection.

The platform is Special-Collections-only: papers that the engine scores 0 are
research noise (STEM/medical/jargon) and must be removed.

Usage:
    python scripts/reclassify_and_prune_sc.py            # DRY RUN (default) — no writes
    python scripts/reclassify_and_prune_sc.py --apply    # re-score + delete non-SC

The --apply pass:
  1. Backs up uraas.db -> uraas.db.bak (SQLite only).
  2. Re-scores all items, writing special_collection_score / _categories.
  3. Deletes items with score == 0 (ORM delete so association/file rows cascade),
     then removes orphan authors / empty collections / empty communities.
  4. Flushes the analytics cache.

Run with the dashboard and any crawler STOPPED to avoid SQLite write locks.
"""

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from uraas.config import config
from uraas.database import (
    Author,
    Collection,
    Community,
    Item,
    SessionLocal,
    engine,
    item_authors,
)
from uraas.services.sc_engine import is_special_collection
from uraas.utils.analytics_cache import analytics_cache


def backup_sqlite():
    url = (config.DATABASE_URL or "").lower()
    if not url.startswith("sqlite"):
        print(f"[backup] Non-SQLite DB ({url[:30]}...) — skipping file backup.")
        return
    db_path = config.DATABASE_URL.split("///")[-1]
    if not os.path.exists(db_path):
        print(f"[backup] DB file not found at {db_path}; nothing to back up.")
        return
    bak = db_path + ".bak"
    shutil.copy2(db_path, bak)
    print(f"[backup] {db_path} -> {bak}")


def rescore(session, apply: bool):
    """Re-score every item. Returns (keep_ids, drop_ids)."""
    items = session.query(Item).all()
    keep_ids, drop_ids = [], []
    for it in items:
        is_sc, score, cats = is_special_collection(
            it.title or "", it.abstract or "", it.dc_subject or ""
        )
        if apply:
            it.special_collection_score = float(score)
            it.special_collection_categories = ",".join(cats) if is_sc else ""
        (keep_ids if is_sc else drop_ids).append(it.id)
    if apply:
        session.commit()
    return keep_ids, drop_ids


def prune(session, drop_ids):
    """Delete non-SC items + orphan authors/collections/communities."""
    # Enforce FK cascade for this SQLite connection (default is OFF).
    session.execute(text("PRAGMA foreign_keys=ON"))

    deleted = 0
    for chunk_start in range(0, len(drop_ids), 500):
        chunk = drop_ids[chunk_start : chunk_start + 500]
        for it in session.query(Item).filter(Item.id.in_(chunk)).all():
            session.delete(it)  # ORM delete -> association + file rows cascade
            deleted += 1
        session.commit()
    print(f"[prune] deleted {deleted} non-SC items")

    # Sweep stray association rows that referenced deleted items (SQLite FK
    # cascade is unreliable for raw association tables across chunked deletes).
    session.execute(
        text(
            "DELETE FROM item_authors WHERE item_id NOT IN (SELECT id FROM items) "
            "OR author_id NOT IN (SELECT id FROM authors)"
        )
    )
    session.execute(
        text(
            "DELETE FROM item_collections WHERE item_id NOT IN (SELECT id FROM items) "
            "OR collection_id NOT IN (SELECT id FROM collections)"
        )
    )
    session.commit()

    # Orphan authors: no remaining item associations.
    orphan_authors = (
        session.query(Author)
        .filter(~Author.id.in_(session.query(item_authors.c.author_id)))
        .all()
    )
    for a in orphan_authors:
        session.delete(a)
    print(f"[prune] deleted {len(orphan_authors)} orphan authors")

    # Empty collections (no items) and then empty communities (no collections).
    empty_colls = [c for c in session.query(Collection).all() if not c.items]
    for c in empty_colls:
        session.delete(c)
    session.commit()
    print(f"[prune] deleted {len(empty_colls)} empty collections")

    empty_comms = [c for c in session.query(Community).all() if not c.collections]
    for c in empty_comms:
        session.delete(c)
    session.commit()
    print(f"[prune] deleted {len(empty_comms)} empty communities")


def main():
    parser = argparse.ArgumentParser(description="Re-classify & prune non-SC papers")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually re-score and delete (default: dry run)",
    )
    parser.add_argument(
        "--samples", type=int, default=20, help="How many borderline drops to print"
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        total = session.query(Item).count()
        old_sc = session.query(Item).filter(Item.special_collection_score > 0).count()
        print("=" * 64)
        print(f"Total items: {total}   (old score>0: {old_sc})")
        print("=" * 64)

        if args.apply:
            backup_sqlite()

        keep_ids, drop_ids = rescore(session, apply=args.apply)
        print(f"\nKEEP (special collections): {len(keep_ids)}")
        print(f"DROP (not special collections): {len(drop_ids)}")

        # Show a sample of what would be / was dropped that previously scored > 0
        # (these are the meaningful changes to eyeball).
        prev_sc = (
            {
                i
                for (i,) in session.query(Item.id)
                .filter(Item.special_collection_score >= 0)
                .all()
            }
            if not args.apply
            else set()
        )
        sample = (
            session.query(Item.title)
            .filter(Item.id.in_(drop_ids[: args.samples]))
            .all()
        )
        print(f"\n--- sample of dropped titles (first {args.samples}) ---")
        for (t,) in sample:
            safe = (t or "").encode("ascii", "replace").decode()
            print("  DROP:", safe[:90])

        if not args.apply:
            print("\n[DRY RUN] No changes written. Re-run with --apply to prune.")
            return 0

        prune(session, drop_ids)
        analytics_cache.invalidate_all()

        remaining = session.query(Item).count()
        sc_remaining = (
            session.query(Item).filter(Item.special_collection_score > 0).count()
        )
        orphan_left = (
            session.query(Author)
            .filter(~Author.id.in_(session.query(item_authors.c.author_id)))
            .count()
        )
        print("\n" + "=" * 64)
        print(f"DONE. Items remaining: {remaining}  (score>0: {sc_remaining})")
        print(f"Orphan authors remaining: {orphan_left}")
        assert remaining == sc_remaining, "Mismatch: non-SC rows survived!"
        assert orphan_left == 0, "Orphan authors survived!"
        print("Invariants OK. Restart the dashboard to serve fresh data.")
        print("=" * 64)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
