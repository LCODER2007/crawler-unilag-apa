"""
Backfill missing pdf_url via Unpaywall for items that have a DOI but no
open-access PDF link from their original source. Free, self-service API —
just an email param, no key/application needed.

Live-verified 2026-07-20: 13/34 real DB items missing a PDF got one filled
this way — several sources (AJOL in particular) don't surface a direct PDF
link even when the article is genuinely open access; Unpaywall aggregates
OA status/location across publishers and repository mirrors that individual
source APIs often miss.

Usage:
    python scripts/backfill_unpaywall_pdfs.py                # DRY RUN
    python scripts/backfill_unpaywall_pdfs.py --apply
    python scripts/backfill_unpaywall_pdfs.py --apply --limit 50
"""

import argparse
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.config import config
from uraas.database import Item, SessionLocal

_UNPAYWALL_API = "https://api.unpaywall.org/v2"
_TIMEOUT = 15


def fetch_pdf_url(doi: str) -> str | None:
    try:
        r = requests.get(
            f"{_UNPAYWALL_API}/{doi}",
            params={"email": config.OPENALEX_MAILTO},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        loc = data.get("best_oa_location") or {}
        return loc.get("url_for_pdf") or None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max items to check this run"
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        candidates = (
            session.query(Item)
            .filter(Item.doi.isnot(None))
            .filter((Item.pdf_url.is_(None)) | (Item.pdf_url == ""))
            .all()
        )
        print(f"Items with a DOI but no pdf_url: {len(candidates)}")
        if args.limit:
            candidates = candidates[: args.limit]
            print(f"Limited to first {len(candidates)} for this run")

        if not args.apply:
            print("[DRY RUN] Would query Unpaywall for these. Re-run with --apply.")
            return 0

        filled = 0
        for it in candidates:
            pdf_url = fetch_pdf_url(it.doi)
            if pdf_url:
                it.pdf_url = pdf_url
                filled += 1
                print(f"  OK  id={it.id} -> {pdf_url[:70]}")
            time.sleep(
                0.3
            )  # polite — Unpaywall has no published hard rate limit, but be reasonable
        session.commit()
        print(f"\nDONE. Filled: {filled}/{len(candidates)}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
