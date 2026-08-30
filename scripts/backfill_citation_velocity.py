"""
Backfill Pan-African citation share (and citation velocity for items missed
by the collaboration backfill).

The share is one OpenAlex request per item (filter=cites:W... grouped by
citing-country), so run it for the most-cited works first:

    python scripts/backfill_citation_velocity.py                  # DRY RUN
    python scripts/backfill_citation_velocity.py --apply --limit 200

Skips items whose share is already computed unless --force.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Item, SessionLocal
from uraas.services.citation_tracker import CitationTracker
from uraas.utils.analytics_cache import analytics_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    parser.add_argument(
        "--limit", type=int, default=200, help="Max items (most-cited first)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Recompute existing shares"
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        q = (
            session.query(Item)
            .filter(Item.openalex_id.isnot(None), Item.cited_by_count > 0)
            .order_by(Item.cited_by_count.desc())
        )
        if not args.force:
            q = q.filter(Item.african_citation_share.is_(None))
        items = q.limit(args.limit).all()

        print("=" * 64)
        print(f"Items to process (most-cited first): {len(items)}")
        print("=" * 64)
        if not args.apply:
            print("[DRY RUN] No API calls or writes. Re-run with --apply.")
            return 0

        updated = velocity_fixed = 0
        for i, it in enumerate(items, 1):
            share = CitationTracker.fetch_african_citation_share(it.openalex_id)
            if share is not None:
                it.african_citation_share = share
                updated += 1
            # Opportunistic velocity fix for items missing counts_by_year
            if not it.counts_by_year:
                vel = CitationTracker.fetch_work_velocity(it.openalex_id)
                if vel and vel["counts_by_year"]:
                    it.counts_by_year = json.dumps(vel["counts_by_year"])
                    it.cited_by_count = vel["cited_by_count"]
                    velocity_fixed += 1
            if i % 25 == 0:
                session.commit()
                print(f"  {i}/{len(items)} processed (share set: {updated})")
            time.sleep(1.0)
        session.commit()
        analytics_cache.invalidate_all()

        print("\n" + "=" * 64)
        print(f"DONE. shares set={updated}  velocity backfilled={velocity_fixed}")
        print("=" * 64)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
