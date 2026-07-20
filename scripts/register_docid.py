"""Register items with the REAL Africa PID Alliance DOCiD(TM) platform.

Unlike scripts/backfill_pids.py (which mints a purely local placeholder hash
and never talks to any server), this hits the actual docid.africapidalliance.org
registration API via uraas.services.docid_client.DocIDClient. Requires
DOCID_EMAIL / DOCID_PASSWORD in .env (the base URL is defaulted to the real,
confirmed public API — see .env.example). Until credentials are set this
exits cleanly with an explanation instead of doing anything.

WARNING: each item registered here calls the real /cordoi/assign-doi/
container-id + /publications/publish endpoints, which create real,
permanent, publicly-visible records on the live Africa PID Alliance
platform — always run with --limit against a small batch first, and without
--apply (the default) to see what would happen before committing to it.

Finds items in the local DB that don't have a *real* DOCiD yet — including
ones that only have the local placeholder from backfill_pids.py, which is
not a real registration — and registers them, storing whatever identifier
the platform assigns back onto Item.docid.

Usage:
    python scripts/register_docid.py                # DRY RUN
    python scripts/register_docid.py --apply
    python scripts/register_docid.py --apply --limit 5   # small batch first
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Item, SessionLocal
from uraas.services.docid_client import DocIDClient, DocIDConnectionError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    parser.add_argument("--limit", type=int, default=None, help="Max items to register this run")
    args = parser.parse_args()

    try:
        client = DocIDClient()
    except DocIDConnectionError as e:
        print(f"[DISABLED] {e}")
        return 0

    session = SessionLocal()
    try:
        # Real registration is distinct from the local placeholder — an item
        # with only a locally-minted docid (format "20.500.14351/<hash>",
        # never actually sent anywhere) still needs real registration.
        candidates = (
            session.query(Item)
            .filter(Item.special_collection_score > 0)
            .filter(Item.title.isnot(None))
            .all()
        )
        print(f"Special-Collections items in DB: {len(candidates)}")
        if args.limit:
            candidates = candidates[: args.limit]
            print(f"Limited to first {len(candidates)} for this run")

        if not args.apply:
            print("[DRY RUN] Would attempt to register these with the real DOCiD API —")
            print("this creates real, permanent, publicly-visible records. Re-run with")
            print("--apply --limit 1 to test against a single item first.")
            return 0

        client.login()
        ok = failed = 0
        for it in candidates:
            try:
                result = client.publish_item(it)
                docid = result["_assigned_docid"]
                it.docid = docid
                it.docid_assigned_at = datetime.utcnow()
                ok += 1
                print(f"  OK  id={it.id} docid={docid}  {it.title[:60]!r}")
            except Exception as e:
                failed += 1
                print(f"  FAIL id={it.id}: {e}")
        session.commit()
        print(f"\nDONE. Registered: {ok}   Failed: {failed}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
