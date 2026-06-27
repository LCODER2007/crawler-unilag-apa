"""
Backfill persistent identifiers: DocID™ + ARK for items missing them.

ARKs are minted deterministically from the item's DocID hash, so re-running
is idempotent. No network access needed.

Usage:
    python scripts/backfill_pids.py            # DRY RUN
    python scripts/backfill_pids.py --apply
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Item, SessionLocal
from uraas.utils.ark_generator import ark_generator
from uraas.utils.docid_generator import docid_generator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        need_docid = session.query(Item).filter(Item.docid.is_(None)).count()
        need_ark = session.query(Item).filter(Item.ark.is_(None)).count()
        print("=" * 64)
        print(f"Items missing DocID: {need_docid}   missing ARK: {need_ark}")
        print("=" * 64)
        if not args.apply:
            print("[DRY RUN] No writes. Re-run with --apply.")
            return 0

        minted_docid = minted_ark = 0
        now = datetime.utcnow()
        for it in session.query(Item).filter(
            (Item.docid.is_(None)) | (Item.ark.is_(None))
        ):
            if not it.docid:
                it.docid = docid_generator.generate_docid(
                    title=it.title or "",
                    doi=it.doi,
                    institution=it.institution or "Unknown",
                    timestamp=it.publication_date,
                )
                it.docid_assigned_at = now
                minted_docid += 1
            if not it.ark:
                it.ark = ark_generator.mint(it.docid)
                it.ark_assigned_at = now
                minted_ark += 1
        session.commit()

        print(f"DONE. DocIDs minted: {minted_docid}   ARKs minted: {minted_ark}")
        sample = session.query(Item.ark).filter(Item.ark.isnot(None)).first()
        if sample:
            print(f"Sample ARK: {sample[0]}  (valid: {ark_generator.validate(sample[0])})")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
