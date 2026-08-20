"""Register items with the REAL Africa PID Alliance DOCiD(TM) platform.

This is the ONLY thing that's allowed to set Item.docid to a real value.
uraas.utils.docid_generator (a purely local SHA-256 placeholder hash that
never talks to any server) must never be wired into the crawl pipeline or
any auto-run path — DocIDs are minted by DOCiD itself, not by us. This
script hits the actual docid.africapidalliance.org registration API via
uraas.services.docid_client.DocIDClient. Requires DOCID_EMAIL / DOCID_PASSWORD
in .env (the base URL is defaulted to the real, confirmed public API — see
.env.example). Until credentials are set this exits cleanly with an
explanation instead of doing anything.

WARNING: each item registered here calls the real /cordoi/assign-doi/
container-id + /publications/publish endpoints, which create real,
permanent, publicly-visible records on the live Africa PID Alliance
platform — always run with --limit against a small batch first, and without
--apply (the default) to see what would happen before committing to it.

Finds items in the local DB that don't have a *real* DOCiD yet AND have
affiliation_confidence == "strong" (roster match, verified employment
record, or a structured author-affiliation field from the source — never a
bare title/abstract text mention), and registers them, storing whatever
identifier the platform assigns back onto Item.docid.

Invoked automatically after each dashboard-triggered crawl (see
uraas/dashboard/app.py) with --apply --limit 5, so a single crawl can't
mass-create hundreds of live public records at once.

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
        # Skip anything that already has a real docid — local placeholder
        # minting was removed entirely, so any non-null Item.docid at this
        # point came from an actual prior registration with this platform.
        # Live-verified 2026-07-28: this filter was previously missing
        # entirely, which would have re-registered (and duplicated) already-
        # published items on every subsequent run.
        # affiliation_confidence == "strong" excludes items whose only
        # evidence of UNILAG authorship is a bare title/abstract text
        # mention (e.g. a paper ABOUT a UNILAG figure written by someone
        # else) — see the per-spider "strong" vs "weak" logic. Auto-pushing
        # a weak match to a permanent public registry under UNILAG's name
        # would be a real misattribution risk, not just noise.
        candidates = (
            session.query(Item)
            .filter(Item.special_collection_score > 0)
            .filter(Item.title.isnot(None))
            .filter(Item.docid.is_(None))
            .filter(Item.affiliation_confidence == "strong")
            .all()
        )
        print(f"Special-Collections items in DB without a real DocID yet (strong affiliation only): {len(candidates)}")
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
                # Commit immediately, not batched at the end — the record
                # already exists on the live platform the moment publish_item()
                # returns, so a crash before a final batched commit would
                # otherwise lose the local docid and risk a duplicate
                # registration on the next run.
                session.commit()
                ok += 1
                print(f"  OK  id={it.id} docid={docid}  {it.title[:60]!r}")
            except Exception as e:
                session.rollback()
                failed += 1
                print(f"  FAIL id={it.id}: {e}")
        print(f"\nDONE. Registered: {ok}   Failed: {failed}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
