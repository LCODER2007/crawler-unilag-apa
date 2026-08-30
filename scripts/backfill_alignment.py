"""
Backfill framework alignment scores for existing items and rebuild the
AlignmentAggregate table (per institution + global).

Usage:
    python scripts/backfill_alignment.py            # DRY RUN — counts only
    python scripts/backfill_alignment.py --apply
    python scripts/backfill_alignment.py --apply --force   # re-score current-version items

Safe to re-run: items already at ALIGNMENT_VERSION are skipped unless --force.
No network needed beyond the one-time embedding-model download.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.config.alignment_frameworks import ALIGNMENT_VERSION
from uraas.database import Item, SessionLocal
from uraas.services.alignment_engine import (
    recompute_aggregates,
    score_item_alignment,
    scoring_mode,
)
from uraas.utils.analytics_cache import analytics_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-score items already at current version"
    )
    parser.add_argument("--batch", type=int, default=500)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        q = session.query(Item)
        if not args.force:
            q = q.filter(
                (Item.alignment_version.is_(None))
                | (Item.alignment_version < ALIGNMENT_VERSION)
            )
        todo = q.count()
        total = session.query(Item).count()
        print("=" * 64)
        print(f"Scoring mode: {scoring_mode()}  |  version: {ALIGNMENT_VERSION}")
        print(f"Items to score: {todo} / {total}")
        print("=" * 64)
        if not args.apply:
            print("[DRY RUN] No writes. Re-run with --apply.")
            return 0

        scored = aligned = 0
        framework_hits = {}
        while True:
            batch = q.limit(args.batch).all()
            if not batch:
                break
            for it in batch:
                j, v = score_item_alignment(
                    it.title or "", it.abstract or "", it.dc_subject or ""
                )
                it.alignment_scores = j
                it.alignment_version = v
                scored += 1
                if j:
                    aligned += 1
                    for fk in json.loads(j):
                        framework_hits[fk] = framework_hits.get(fk, 0) + 1
            session.commit()
            print(f"  scored {scored}/{todo}")

        print("\nPer-framework items with alignment:")
        for fk, n in sorted(framework_hits.items(), key=lambda kv: -kv[1]):
            print(f"  {fk:24s} {n}")

        # Aggregates: global + each distinct institution
        rows = recompute_aggregates(session, None)
        institutions = [i for (i,) in session.query(Item.institution).distinct() if i]
        for inst in institutions:
            rows += recompute_aggregates(session, inst)
        print(f"\nAggregate rows written: {rows} ({1 + len(institutions)} scopes)")

        analytics_cache.invalidate_all()
        print("\n" + "=" * 64)
        print(f"DONE. scored={scored}  with_alignment={aligned}")
        print("=" * 64)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
