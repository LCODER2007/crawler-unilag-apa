"""Backfill Item.publication_date for existing rows.

uraas/pipelines/database.py's date parser had a slicing bug (fixed
2026-07-19): it truncated every incoming date string to len(format_string)
characters before calling strptime, e.g. slicing "2024-06-15" (10 chars) to
"2024-06-" (8 chars, matching len("%Y-%m-%d")) — which then fails to parse,
for every format, for every item, always. Confirmed live: 0/54 items in the
production DB had publication_date set despite 40/54 having a valid
dc_date_issued string. Since Item.publication_date (not dc_date_issued, a
separate plain-string column that was never affected) is what analytics/
dashboard code actually sorts/filters/groups by (36 references across
uraas/analytics/engine.py, uraas/dashboard/app.py,
uraas/services/comparator_engine.py), every date-based chart or filter has
been silently empty/broken for every item ever crawled.

This re-derives publication_date from the already-correct dc_date_issued
string using the same (now-fixed) parsing logic, for every row currently
missing it. Idempotent — only touches rows where publication_date IS NULL.

Usage:
    python scripts/backfill_publication_dates.py            # DRY RUN
    python scripts/backfill_publication_dates.py --apply
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Item, SessionLocal

_FORMATS = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m", "%Y")


def _parse(date_str: str):
    date_str = (date_str or "").strip()
    if not date_str:
        return None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        candidates = (
            session.query(Item)
            .filter(Item.publication_date.is_(None))
            .filter(Item.dc_date_issued.isnot(None))
            .all()
        )
        print(f"Items with publication_date NULL but dc_date_issued present: {len(candidates)}")

        fixed = unparseable = 0
        for it in candidates:
            parsed = _parse(it.dc_date_issued)
            if parsed:
                fixed += 1
                if args.apply:
                    it.publication_date = parsed
            else:
                unparseable += 1
                print(f"  UNPARSEABLE id={it.id} dc_date_issued={it.dc_date_issued!r}")

        print(f"\nWould fix: {fixed}   Unparseable (left as-is): {unparseable}")

        if not args.apply:
            print("\n[DRY RUN] No changes written. Re-run with --apply.")
            return 0

        session.commit()
        print(f"\nDONE. {fixed} items backfilled.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
