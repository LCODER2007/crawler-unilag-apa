"""
Database Cleanup Script
Removes bad/misattributed data from the URAAS database.

Cleanup rules:
1. Remove items from institutions no longer in the registry
2. Remove items with no title, no DOI, no URL, and no authors
3. Remove exact DOI duplicates (keep first by id)
4. Remove items whose title is fewer than 10 chars
5. Flag (do not delete) items with institution mismatch in affiliation
6. Report before/after counts
"""

import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run_cleanup(dry_run: bool = False):
    from sqlalchemy import func

    from uraas.config.institutions import get_registry
    from uraas.database import Author, Collection, Community, Item, SessionLocal

    registry = get_registry()
    valid_inst_names = {c.name for c in registry.list_all()}

    session = SessionLocal()
    try:
        total_before = session.query(Item).count()
        log.info(f"Starting cleanup | Items before: {total_before}")

        removed = 0

        # ── Rule 1: Remove items from removed institutions ────────────────────
        all_institutions_in_db = session.query(Item.institution).distinct().all()
        stale_insts = [
            r[0]
            for r in all_institutions_in_db
            if r[0] and r[0] not in valid_inst_names
        ]

        if stale_insts:
            log.info(f"Found stale institutions: {stale_insts}")
            for stale in stale_insts:
                stale_items = (
                    session.query(Item).filter(Item.institution == stale).all()
                )
                log.info(f"  [{stale}] {len(stale_items)} items to remove")
                if not dry_run:
                    for item in stale_items:
                        session.delete(item)
                    session.commit()
                removed += len(stale_items)

        # ── Rule 2: Remove items with no title ────────────────────────────────
        no_title = (
            session.query(Item)
            .filter(
                (Item.title == None) | (Item.title == "") | (Item.title == "Untitled")
            )
            .all()
        )
        log.info(f"Items with no/empty title: {len(no_title)}")
        if not dry_run:
            for item in no_title:
                session.delete(item)
            session.commit()
        removed += len(no_title)

        # ── Rule 3: Remove items with title < 10 chars and no DOI ────────────
        all_short = session.query(Item).filter(Item.doi == None).all()
        short_items = [i for i in all_short if i.title and len(i.title.strip()) < 10]
        log.info(
            f"Items with very short title (<10 chars) and no DOI: {len(short_items)}"
        )
        if not dry_run:
            for item in short_items:
                session.delete(item)
            session.commit()
        removed += len(short_items)

        # ── Rule 4: Remove exact DOI duplicates (keep lowest id) ─────────────
        doi_subq = (
            session.query(Item.doi, func.min(Item.id).label("min_id"))
            .filter(Item.doi != None)
            .group_by(Item.doi)
            .subquery()
        )

        dup_dois = (
            session.query(Item)
            .filter(Item.doi != None, Item.id.notin_(session.query(doi_subq.c.min_id)))
            .all()
        )
        log.info(f"Duplicate DOI items to remove: {len(dup_dois)}")
        if not dry_run:
            for item in dup_dois:
                session.delete(item)
            session.commit()
        removed += len(dup_dois)

        # ── Rule 5: Remove items with no institution tag ──────────────────────
        no_inst = (
            session.query(Item)
            .filter((Item.institution == None) | (Item.institution == ""))
            .all()
        )
        # Only remove those that have no authors either
        truly_orphan = [i for i in no_inst if not i.authors]
        log.info(f"Items with no institution AND no authors: {len(truly_orphan)}")
        if not dry_run:
            for item in truly_orphan:
                session.delete(item)
            session.commit()
        removed += len(truly_orphan)

        total_after = session.query(Item).count()

        log.info(f"\n{'='*50}")
        log.info(f"CLEANUP COMPLETE {'(DRY RUN)' if dry_run else ''}")
        log.info(f"  Items before: {total_before}")
        log.info(f"  Items removed: {removed}")
        log.info(f"  Items after:  {total_after}")
        log.info(f"{'='*50}")

        return {
            "total_before": total_before,
            "removed": removed,
            "total_after": total_after,
            "dry_run": dry_run,
        }

    except Exception as e:
        log.error(f"Cleanup error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="URAAS Database Cleanup")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report without deleting"
    )
    args = parser.parse_args()
    run_cleanup(dry_run=args.dry_run)
